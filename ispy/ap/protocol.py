"""Minimal Archipelago client: a stdlib-only WebSocket transport plus the AP packet handling.

Transport (`WebSocket`) and protocol (`APClient`) are separate so the protocol can be tested by feeding packets in
by hand.  Nothing here touches pygame or the game; call `client.pump()` once per frame from the game loop.
"""
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import uuid as _uuid
from urllib.parse import urlparse

from .data import GAME_NAME

DEFAULT_PORT = 38281
AP_VERSION = {'major': 0, 'minor': 6, 'build': 1, 'class': 'Version'}
ITEMS_HANDLING_ALL = 0b111           # remote + own-world + starting items all come through ReceivedItems
_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


# ---- WebSocket framing (pure) ----------------------------------------------------------------------------
def encode_frame(opcode, payload=b'', mask=True):
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    n = len(payload)
    head = bytearray([0x80 | opcode])
    mbit = 0x80 if mask else 0
    if n < 126:
        head.append(mbit | n)
    elif n < 65536:
        head.append(mbit | 126)
        head += struct.pack('>H', n)
    else:
        head.append(mbit | 127)
        head += struct.pack('>Q', n)
    if mask:
        key = os.urandom(4)
        head += key
        payload = bytes(b ^ key[i & 3] for i, b in enumerate(payload))
    return bytes(head) + payload


class FrameParser:
    """Feed raw bytes, get back complete messages as (opcode, payload); fragments are reassembled."""

    def __init__(self):
        self._buf = bytearray()
        self._frag_op = None
        self._frag = bytearray()

    def feed(self, data):
        self._buf += data
        out = []
        while True:
            b = self._buf
            if len(b) < 2:
                break
            fin, op = bool(b[0] & 0x80), b[0] & 0x0F
            masked, n = bool(b[1] & 0x80), b[1] & 0x7F
            pos = 2
            if n == 126:
                if len(b) < 4:
                    break
                n, pos = struct.unpack('>H', b[2:4])[0], 4
            elif n == 127:
                if len(b) < 10:
                    break
                n, pos = struct.unpack('>Q', b[2:10])[0], 10
            key = b''
            if masked:
                if len(b) < pos + 4:
                    break
                key, pos = bytes(b[pos:pos + 4]), pos + 4
            if len(b) < pos + n:
                break
            payload = bytes(b[pos:pos + n])
            del b[:pos + n]
            if masked:
                payload = bytes(x ^ key[i & 3] for i, x in enumerate(payload))
            if op >= 0x8:                       # control frames are never fragmented
                out.append((op, payload))
            elif op == OP_CONT:
                self._frag += payload
                if fin:
                    out.append((self._frag_op, bytes(self._frag)))
                    self._frag_op, self._frag = None, bytearray()
            elif fin:
                out.append((op, payload))
            else:
                self._frag_op, self._frag = op, bytearray(payload)
        return out


class WebSocket:
    """Blocking connect + handshake, then non-blocking `poll()` / `send_text()`."""

    def __init__(self):
        self.sock = None
        self.parser = FrameParser()
        self.closed = True

    def connect(self, url, timeout=6.0):
        u = urlparse(url)
        secure = u.scheme == 'wss'
        host, port = u.hostname, u.port or (443 if secure else 80)
        raw = socket.create_connection((host, port), timeout=timeout)
        if secure:
            raw = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        path = (u.path or '/') + (('?' + u.query) if u.query else '')
        raw.sendall(('GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                     'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n' % (path, host, port, key)).encode())
        resp = b''
        while b'\r\n\r\n' not in resp:
            chunk = raw.recv(4096)
            if not chunk:
                raise ConnectionError('server closed during handshake')
            resp += chunk
            if len(resp) > 65536:
                raise ConnectionError('handshake too large')
        head, _, rest = resp.partition(b'\r\n\r\n')
        lines = head.decode('latin-1').split('\r\n')
        if ' 101 ' not in lines[0] + ' ':
            raise ConnectionError('websocket upgrade refused: ' + lines[0])
        want = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        hdrs = {l.split(':', 1)[0].strip().lower(): l.split(':', 1)[1].strip() for l in lines[1:] if ':' in l}
        if hdrs.get('sec-websocket-accept') != want:
            raise ConnectionError('bad Sec-WebSocket-Accept')
        raw.setblocking(False)
        self.sock, self.closed, self.parser = raw, False, FrameParser()
        self._pending = self.parser.feed(rest) if rest else []

    def send_text(self, text):
        if self.closed:
            return
        data = encode_frame(OP_TEXT, text)
        try:
            self.sock.setblocking(True)
            self.sock.sendall(data)
        except OSError:
            self.close()
        finally:
            if self.sock:
                self.sock.setblocking(False)

    def poll(self):
        """Return a list of received text messages (never blocks)."""
        out = []
        if self.closed:
            return out
        msgs = getattr(self, '_pending', [])
        self._pending = []
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    self.close()
                    break
                msgs += self.parser.feed(chunk)
        except (BlockingIOError, ssl.SSLWantReadError):
            pass
        except OSError:
            self.close()
        for op, payload in msgs:
            if op == OP_TEXT:
                out.append(payload.decode('utf-8', 'replace'))
            elif op == OP_PING and self.sock:
                try:
                    self.sock.send(encode_frame(OP_PONG, payload))
                except OSError:
                    pass
            elif op == OP_CLOSE:
                self.close()
        return out

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock, self.closed = None, True


# ---- Archipelago protocol -------------------------------------------------------------------------------
def render_json_parts(parts):
    """PrintJSON `data` -> plain text."""
    return ''.join(str(p.get('text', '')) for p in parts or [])


class APClient:
    """States: 'disconnected' -> 'connecting' -> 'connected' | 'refused'.

    Callbacks (all optional, all exceptions swallowed so a bad callback never breaks the game loop):
      on_connected(slot_data)            on_refused(errors)
      on_items(items, resync)            items = [(item_id, location_id, player_slot)]; on resync it is the FULL list
      on_text(str)                       on_status(str)
    """

    def __init__(self, transport_factory=WebSocket, uuid=None):
        self._factory = transport_factory
        self.ws = None
        self.state = 'disconnected'
        self.status = ''
        self.uuid = uuid or str(_uuid.uuid4())
        self.slot_name = self.password = ''
        self.slot = None
        self.team = 0
        self.slot_data = {}
        self.checked = set()
        self.missing = set()
        self.items_received = []           # [(item_id, location_id, player)] in server order
        self.outbox = set()                # location ids not yet confirmed to the server
        self.on_connected = self.on_refused = self.on_items = self.on_text = self.on_status = None
        self.on_item_send = None
        self.player_names = {}             # slot -> alias
        self.player_games = {}             # slot -> game name
        self.item_names = {}               # game -> {item id: name}   (from the DataPackage)
        self.location_names = {}           # game -> {location id: name}

    # -- helpers
    def _cb(self, name, *a):
        fn = getattr(self, name, None)
        if fn:
            try:
                fn(*a)
            except Exception as e:                      # noqa: BLE001 - never let UI code break networking
                print('[ap] callback %s failed: %s' % (name, e))

    def _set_status(self, s):
        self.status = s
        self._cb('on_status', s)

    def _send(self, packets):
        if self.ws and not self.ws.closed:
            self.ws.send_text(json.dumps(packets))

    # -- connecting
    @staticmethod
    def candidate_urls(address):
        address = (address or '').strip()
        if '://' in address:
            return [address]
        host, _, port = address.partition(':')
        port = port or str(DEFAULT_PORT)
        return ['wss://%s:%s' % (host, port), 'ws://%s:%s' % (host, port)]

    def connect(self, address, slot_name, password=''):
        self.disconnect()
        self.slot_name, self.password = slot_name, password or ''
        self.state = 'connecting'
        last = None
        for url in self.candidate_urls(address):
            ws = self._factory()
            try:
                ws.connect(url)
            except (OSError, ConnectionError, ssl.SSLError) as e:
                last = e
                continue
            self.ws = ws
            self._set_status('Connected to server, authenticating...')
            return True
        self.state = 'disconnected'
        self._set_status('Could not connect: %s' % last)
        return False

    def disconnect(self):
        if self.ws:
            self.ws.close()
        self.ws = None
        if self.state != 'refused':
            self.state = 'disconnected'

    @property
    def connected(self):
        return self.state == 'connected'

    # -- per-frame
    def pump(self):
        if not self.ws:
            return
        for text in self.ws.poll():
            try:
                packets = json.loads(text)
            except ValueError:
                continue
            for pkt in packets if isinstance(packets, list) else [packets]:
                self.handle_packet(pkt)
        if self.ws.closed and self.state in ('connected', 'connecting'):
            self.state = 'disconnected'
            self._set_status('Disconnected')

    # -- outgoing
    def send_checks(self, location_ids):
        ids = set(location_ids)
        self.outbox |= ids
        if self.connected and ids:
            self._send([{'cmd': 'LocationChecks', 'locations': sorted(ids)}])

    def send_goal_complete(self):
        if self.connected:
            self._send([{'cmd': 'StatusUpdate', 'status': 30}])      # CLIENT_GOAL

    def say(self, text):
        self._send([{'cmd': 'Say', 'text': text}])

    def _connect_packet(self):
        return {'cmd': 'Connect', 'password': self.password, 'game': GAME_NAME, 'name': self.slot_name,
                'uuid': self.uuid, 'version': AP_VERSION, 'items_handling': ITEMS_HANDLING_ALL,
                'tags': ['AP'], 'slot_data': True}

    # -- name lookup (PrintJSON carries ids; names come from the Connected player list + DataPackage)
    def item_name(self, iid, player):
        return self.item_names.get(self.player_games.get(player), {}).get(iid) or 'item %s' % iid

    def location_name(self, lid, player):
        return self.location_names.get(self.player_games.get(player), {}).get(lid) or 'location %s' % lid

    def player_name(self, slot):
        return self.player_names.get(slot) or 'Player %s' % slot

    def render_parts(self, parts):
        out = []
        for p in parts or []:
            t, txt = p.get('type'), str(p.get('text', ''))
            try:
                if t == 'player_id':
                    txt = self.player_name(int(txt))
                elif t == 'item_id':
                    txt = self.item_name(int(txt), p.get('player'))
                elif t == 'location_id':
                    txt = self.location_name(int(txt), p.get('player'))
            except ValueError:
                pass
            out.append(txt)
        return ''.join(out)

    # -- incoming
    def handle_packet(self, pkt):
        cmd = pkt.get('cmd')
        if cmd == 'RoomInfo':
            self._send([self._connect_packet()])
        elif cmd == 'Connected':
            self.state = 'connected'
            self.slot, self.team = pkt.get('slot'), pkt.get('team', 0)
            self.slot_data = pkt.get('slot_data') or {}
            self.checked = set(pkt.get('checked_locations') or [])
            self.missing = set(pkt.get('missing_locations') or [])
            self._set_status('Connected as %s' % self.slot_name)
            self.player_names = {p.get('slot'): p.get('alias') or p.get('name') for p in pkt.get('players') or []}
            self.player_games = {int(k): v.get('game') for k, v in (pkt.get('slot_info') or {}).items()}
            games = sorted({g for g in self.player_games.values() if g})
            if games:
                self._send([{'cmd': 'GetDataPackage', 'games': games}])
            self._cb('on_connected', self.slot_data)
            resend = self.outbox - self.checked        # checks made while offline
            if resend:
                self._send([{'cmd': 'LocationChecks', 'locations': sorted(resend)}])
        elif cmd == 'ConnectionRefused':
            self.state = 'refused'
            errs = pkt.get('errors') or []
            self._set_status('Refused: ' + ', '.join(errs))
            self._cb('on_refused', errs)
            if self.ws:
                self.ws.close()
        elif cmd == 'ReceivedItems':
            index = pkt.get('index', 0)
            items = [(i.get('item'), i.get('location'), i.get('player')) for i in pkt.get('items') or []]
            if index == 0:
                self.items_received = list(items)                # full resync: consumer rebuilds from the whole list
                self._cb('on_items', list(items), True)
            elif index == len(self.items_received):
                self.items_received += items
                self._cb('on_items', items, False)
            else:                                                 # out of step: ask for everything again
                self._send([{'cmd': 'Sync'}])
        elif cmd == 'RoomUpdate':
            self.checked |= set(pkt.get('checked_locations') or [])
        elif cmd == 'DataPackage':
            for game, gd in ((pkt.get('data') or {}).get('games') or {}).items():
                self.item_names[game] = {v: k for k, v in (gd.get('item_name_to_id') or {}).items()}
                self.location_names[game] = {v: k for k, v in (gd.get('location_name_to_id') or {}).items()}
        elif cmd == 'PrintJSON':
            self._cb('on_text', self.render_parts(pkt.get('data')))
            if pkt.get('type') == 'ItemSend':
                item = pkt.get('item') or {}
                s_slot, r_slot = item.get('player'), pkt.get('receiving')
                self._cb('on_item_send', {
                    'sender_slot': s_slot, 'receiver_slot': r_slot,
                    'sender': self.player_name(s_slot), 'receiver': self.player_name(r_slot),
                    'item': self.item_name(item.get('item'), r_slot),
                    'location': self.location_name(item.get('location'), s_slot)})
