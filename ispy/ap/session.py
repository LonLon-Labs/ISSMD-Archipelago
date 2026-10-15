"""The live Archipelago session: owns the APState + APClient and glues them to the running game.

Everything the game hooks need goes through the module-level `session()` singleton.  Nothing in here may raise into
the game: callers wrap calls, and the networking callbacks are already isolated by APClient._cb.
"""
import json
import os
import shutil
import threading
import time

from .data import FILLER_ID, ITEM_NAME_BY_ID, TOKEN_ITEM_LOOKUP, UNLOCK_ITEM_LOOKUP, DOOR_KEY_LOOKUP, ENDING_NAME
from .options import APOptions
from .protocol import APClient
from .state import APState

_SESSION = None


def session():
    global _SESSION
    if _SESSION is None:
        _SESSION = Session()
    return _SESSION


def log(*a):
    print('[ap]', *a)


def _movie():
    from .. import movie
    return movie


def _app_root():
    from ..version_picker import _app_data_root
    return _app_data_root()


class Session:
    TOAST_MS = 3500
    LOCKED_MS = 3200

    def __init__(self):
        self.state = APState()
        self.client = APClient()
        self.client.on_connected = self._on_connected
        self.client.on_items = self._on_items
        self.client.on_item_send = self._on_item_send
        self.client.on_refused = lambda errs: self.toast('Connection refused: ' + ', '.join(errs))
        self.toasts = []                  # [(text, expire_ms)]
        self.locked = None                # (title, line2, expire_ms)
        self.modal = False                # True while the AP menu owns the event loop
        self.pending_wave = None          # wave to switch to once it is safe
        self._connect_thread = None
        self._font = None
        self.filler_sound = None
        self._last_tokens_sync = 0
        self.riddle_applied = False       # set by the hooks: the current game was built with swapped riddles

    # ---- paths ---------------------------------------------------------------------------------------
    def state_path(self):
        pd = _movie().getPlayerDir()
        return os.path.join(pd, 'AP.json') if pd else None

    def last_path(self):
        return os.path.join(_app_root(), 'AP_last.json')

    def save(self):
        p = self.state_path()
        if p:
            self.state.save(p)

    # ---- player / game lifecycle ------------------------------------------------------------------------
    def on_player(self, name):
        """A player signed in: load that save's AP state (new saves inherit the last-used slot) and reconnect."""
        p = self.state_path()
        if p and os.path.exists(p):
            self.state = APState.load(p)
        else:
            st = APState()
            try:
                with open(self.last_path()) as f:
                    last = json.load(f)
                st.enabled = bool(last.get('enabled'))
                st.options = APOptions.from_slot_data(last.get('options'))
                st.address, st.slot_name = last.get('address', ''), last.get('slot_name', '')
                st.password = last.get('password', '')
                st.entrances = last.get('entrances') or {}
                st.riddle_seed = last.get('riddle_seed')
                st.slot_riddle_map = last.get('riddle_map') or {}
            except (OSError, ValueError):
                pass
            self.state = st
        self.client.disconnect()
        self.client.items_received = []
        if self.state.enabled and self.state.address and self.state.slot_name:
            self.connect(self.state.address, self.state.slot_name, self.state.password)

    def current_version(self):
        try:
            sd = _movie().gScreenDaddy
            if sd and str(sd.mGetType()).upper() == 'GAME':
                return str(sd.mGetCurrentVersion()).lower()
        except Exception:                                  # noqa: BLE001
            pass
        return None

    def game_ready(self):
        try:
            sd = _movie().gScreenDaddy
            return bool(sd) and str(sd.mGetType()).upper() == 'GAME' and bool(sd.pTokenCollectorList)
        except Exception:                                  # noqa: BLE001
            return False

    # ---- connecting ------------------------------------------------------------------------------------
    def connect(self, address, slot, password=''):
        st = self.state
        st.address, st.slot_name, st.password = address.strip(), slot.strip(), password
        if self._connect_thread and self._connect_thread.is_alive():
            return
        self.client.state = 'connecting'
        self.client.status = 'Connecting...'

        def work():
            try:
                self.client.connect(st.address, st.slot_name, st.password)
            except Exception as e:                         # noqa: BLE001
                self.client.state = 'disconnected'
                self.client.status = 'Error: %s' % e

        self._connect_thread = threading.Thread(target=work, daemon=True)
        self._connect_thread.start()

    def disconnect(self, disable=False):
        self.client.disconnect()
        if disable:
            self.state.enabled = False
            self.save()
            try:
                os.remove(self.last_path())
            except OSError:
                pass
            self.client.status = 'Archipelago mode off'

    def _on_connected(self, slot_data):
        st = self.state
        sid = '%s|%s|%s' % (self.client.seed_name or st.address.lower(), self.client.team, self.client.slot)
        if st.bind_server(sid):
            log('connected to a different multiworld / slot than this save was using: progress reset')
            self.client.outbox.clear()                     # nothing earned on the old server goes to the new one
            st.riddle_map = {}
            self.toast('New server: starting this slot from scratch')
        st.options = APOptions.from_slot_data(slot_data.get('options', slot_data))
        st.entrances = slot_data.get('entrances') or {}
        seed = slot_data.get('riddle_seed')
        if seed != st.riddle_seed:
            st.riddle_map = {}                             # a different slot / seed: deal the riddles again
        st.riddle_seed = seed
        new_map = slot_data.get('riddle_map') or {}
        if new_map != st.slot_riddle_map:
            st.riddle_map = {}
        st.slot_riddle_map = new_map                       # dealt by the APWorld: checks / unlocks are named after it
        st.enabled = True
        st.checked |= set(self.client.checked)
        unsent = st.checked - set(self.client.checked)
        if unsent:
            self.client.send_checks(unsent)
        self.save()
        try:
            os.makedirs(_app_root(), exist_ok=True)
            with open(self.last_path(), 'w') as f:
                json.dump({'enabled': True, 'options': st.options.to_dict(), 'address': st.address,
                           'slot_name': st.slot_name, 'password': st.password, 'entrances': st.entrances,
                           'riddle_seed': st.riddle_seed, 'riddle_map': st.slot_riddle_map}, f)
        except OSError as e:
            log('could not save last connection:', e)
        ver = self.current_version()
        if ver and not st.options.plays(ver):
            self.pending_wave = st.options.endings[0]
        self.toast('Connected to Archipelago')
        if st.options.entrance_rando:
            n = sum(len(v) for v in st.entrances.values())
            log('entrance rando: %d redirects from the slot (%s)' % (n, st.entrances))
            self.toast('Entrance rando: %d doors redirected' % n if n else 'Entrance rando is on but the slot sent no redirects')
        if st.options.riddle_rando and self.game_ready() and not self.pending_wave and not self.riddle_applied:
            self.toast('Riddle rando starts with the next wave or a new game')

    # ---- items ---------------------------------------------------------------------------------------
    def _on_item_send(self, info):
        """Someone's item was found: show it when it came from OUR world and goes to another player."""
        log('%s sent %s to %s (%s)' % (info['sender'], info['item'], info['receiver'], info['location']))
        me = self.client.slot
        if info['sender_slot'] == me and info['receiver_slot'] != me:
            self.toast('Sent %s to %s' % (info['item'], info['receiver']))

    def _on_items(self, items, resync):
        new = self.state.apply_items(items, resync)
        for iid in new[:6]:
            self.toast('Received: %s' % ITEM_NAME_BY_ID.get(iid, 'item %s' % iid))
            if iid == FILLER_ID:
                self.play_filler()
        if len(new) > 6:
            self.toast('...and %d more items' % (len(new) - 6))
        self.sync_tokens()
        self.save()

    def sync_tokens(self):
        """Item shuffle: make the current ending's token collector match the token items received so far."""
        st = self.state
        if not (st.enabled and st.options.item_shuffle and self.game_ready()):
            return
        ver = self.current_version()
        if not ver:
            return
        from ..lingo import Sym
        sd = _movie().gScreenDaddy
        tc = sd.pTokenCollectorList[0]
        for code in st.tokens_received(ver):
            if not any(str(t).lower() == code.lower() for t in tc.pCollectedTokenList):
                tc.mAddToken(Sym(code))

    def play_filler(self):
        """'You Found Me' sound: drop AP Menu/you_found_me.(wav|ogg) next to the artwork and it plays."""
        try:
            if self.filler_sound is None:
                self.filler_sound = False
                import pygame
                for d in self.asset_dirs():
                    for ext in ('wav', 'ogg'):
                        p = os.path.join(d, 'you_found_me.' + ext)
                        if os.path.isfile(p):
                            self.filler_sound = pygame.mixer.Sound(p)
            if self.filler_sound:
                self.filler_sound.play()
        except Exception as e:                             # noqa: BLE001
            log('filler sound failed:', e)

    # ---- locations -----------------------------------------------------------------------------------
    def report(self, location_ids):
        if location_ids:
            self.client.send_checks(location_ids)
            self.save()

    def goal_check(self, ending):
        """A wave's finale was played: send its 'Finish <wave>' check, and the goal once every selected wave is done."""
        st = self.state
        if not st.enabled:
            return
        locs = st.wave_complete(ending)
        if locs:
            self.report(locs)
            self.toast('%s complete!' % ENDING_NAME.get(str(ending).lower(), 'Wave'))
        if st.ending_completed(ending):
            self.client.send_goal_complete()
            self.toast('All selected waves complete!')
        self.save()

    # ---- waves ---------------------------------------------------------------------------------------
    def change_wave(self, new):
        """Switch the running game to ending `new` ('a'/'b'/'c').  Each wave keeps its own save (MAIN_<v>.LST)."""
        from .. import version_picker as vp
        from ..lingo import Sym
        from ..runtime import LObject
        M = _movie()
        new = str(new).lower()
        old = self.current_version()
        if not old or new == old or (self.state.enabled and not self.state.options.plays(new)):
            return False
        sd = M.gScreenDaddy
        pdir, name = M.getPlayerDir(), str(sd.pName)
        base = vp._base(pdir, name)
        try:
            sd.mSave()
        except Exception as e:                             # noqa: BLE001
            log('save before wave change failed:', e)
        for ext in ('.LST', '.VER'):                       # stash the wave we are leaving
            if os.path.exists(base + ext):
                shutil.copy2(base + ext, '%s_%s%s' % (base, old, ext))
        stash = '%s_%s.LST' % (base, new)
        if os.path.exists(stash):                          # bring the target wave's progress back...
            shutil.copy2(stash, base + '.LST')
        elif os.path.exists(base + '.LST'):                # ...or start it fresh
            os.remove(base + '.LST')
        vp.write_version(pdir, name, new)
        cs = sd.ancestor.pCurrentScreen
        if isinstance(cs, LObject):
            cs.mUnload()
            cs.mHide()
            cs.mReleasePoolObjects()
        sd.ancestor.pCurrentScreen = 0
        sd.mDestroy()
        sd.mSetVersion(new)
        sd.pIsSolved = 0
        sd.pCurrentCollectorIndex = 1
        sd.mInitGameObjects(None if os.path.exists(base + '.LST') else 1)
        sd.mSetDisableUpdateMode()
        door = sd.mGetScreen(Sym('DOOR'))
        entered = (door.pHouseEntered or 0) if isinstance(door, LObject) else 0
        M.navigate(Sym('DOOR') if entered else Sym('MAIN'))
        M.resetCursor()
        self.sync_tokens()
        self.toast('Wave changed: %s' % ENDING_NAME[new])
        return True

    # ---- per-frame -------------------------------------------------------------------------------------
    def pump(self):
        self.client.pump()
        now = time.monotonic() * 1000
        self.toasts = [t for t in self.toasts if t[1] > now]
        if self.locked and self.locked[2] <= now:
            self.locked = None
        if self.pending_wave and not self.modal and self.game_ready():
            wave, self.pending_wave = self.pending_wave, None
            try:
                self.change_wave(wave)
            except Exception as e:                         # noqa: BLE001
                log('wave change failed:', e)

    # ---- overlay (toasts + "locked" box), drawn just before every display flip ----------------------------
    def toast(self, text):
        self.toasts.append((text, time.monotonic() * 1000 + self.TOAST_MS))
        self.toasts = self.toasts[-4:]

    def show_locked(self, line1, line2=''):
        self.locked = (line1, line2, time.monotonic() * 1000 + self.LOCKED_MS)

    def asset_dirs(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return [os.path.join(_app_root(), 'AP Menu'), os.path.join(here, 'AP Menu')]

    def draw_overlay(self, screen):
        if not (self.toasts or self.locked):
            return
        import pygame
        if self._font is None:
            self._font = (pygame.font.Font(pygame.font.match_font('comicsansms,arial') or None, 17),
                          pygame.font.Font(pygame.font.match_font('comicsansms,arial') or None, 22))
        small, big = self._font
        if self.locked:
            l1, l2, _ = self.locked
            lines = [big.render(l1, True, (60, 30, 10))] + ([small.render(l2, True, (90, 50, 20))] if l2 else [])
            w = max(s.get_width() for s in lines) + 40
            h = sum(s.get_height() for s in lines) + 30
            r = pygame.Rect(0, 0, w, h)
            r.center = (screen.get_width() // 2, screen.get_height() // 2)
            pygame.draw.rect(screen, (233, 220, 178), r, border_radius=8)
            pygame.draw.rect(screen, (70, 40, 20), r, 4, border_radius=8)
            y = r.y + 15
            for s in lines:
                screen.blit(s, (r.centerx - s.get_width() // 2, y))
                y += s.get_height()
        y = screen.get_height() - 8
        for text, _ in reversed(self.toasts):
            s = small.render(text, True, (255, 255, 255))
            bg = pygame.Surface((s.get_width() + 14, s.get_height() + 6), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 160))
            y -= bg.get_height() + 3
            screen.blit(bg, (8, y))
            screen.blit(s, (15, y + 3))
