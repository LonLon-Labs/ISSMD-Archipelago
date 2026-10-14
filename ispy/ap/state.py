"""Local Archipelago state: what has been received / checked, and the rules the in-game hooks ask about.

Pure Python.  `APState` is rebuilt from the server's full item list on every (re)connect (`apply_items(..., resync=True)`),
and persisted as JSON so the game still behaves sensibly offline.  The hooks only ever ask yes/no questions
(`riddle_unlocked`, `has_token`, `door_open`, ...) and report events (`minigame_match`, `riddle_solved`, ...) that
return the location ids to send.
"""
import json
import os
from collections import Counter

from . import data, riddle_rando
from .options import APOptions, RIDDLE_SHUFFLE_EVERY_OBJECT


class APState:
    # set by the in-game hooks: (ending, room) -> (source ending, source room) of the riddle the RUNNING game was built
    # with.  Checks follow what the player actually sees, even if the slot connected after the wave was built.
    applied_lookup = None

    def __init__(self, options=None):
        self.options = options or APOptions()
        self.enabled = False                  # True once a slot has connected at least once (AP mode on)
        self.received = []                    # item ids, server order
        self.checked = set()                  # location ids we have checked
        self.matches = {}                     # 'MT:a' -> matches counted so far
        self.plays = {}                       # 'CC:b' -> plays counted so far
        self.address = ''
        self.slot_name = ''
        self.password = ''
        self.filler_seen = 0                  # filler items already "played" (so a resync doesn't replay them)
        self.completed = []                   # endings whose finale has been played
        self.entrances = {}                   # entrance rando: {ending: {destination: destination actually entered}}
        self.riddle_seed = None               # riddle rando: the slot's seed ...
        self.riddle_map = {}                  # ... and the assignment dealt from it (frozen in the save)
        self.slot_riddle_map = {}             # riddle rando: the assignment the APWorld dealt (authoritative when present)

    # ---- items -------------------------------------------------------------------------------------
    def apply_items(self, items, resync):
        """items = [(item_id, location_id, player)].  Returns the list of item ids that are NEW to this state."""
        ids = [i[0] for i in items]
        if resync:
            old = Counter(self.received)
            self.received = list(ids)
            new = []
            for iid, n in Counter(ids).items():
                new += [iid] * max(0, n - old.get(iid, 0))
            return new
        self.received += ids
        return ids

    def _has(self, iid):
        return iid in self.received

    def has_token(self, ending, code):
        iid = data.ITEM_ID.get(data.token_item_name(ending, code)) if code in data.TOKEN_CODES_BY_ENDING.get(ending, ()) else None
        return iid is not None and self._has(iid)

    @staticmethod
    def _canon(ending, code):
        """The room code as data spells it (the game is not consistent about 'fp' / 'FP'), or None if `code` is not a
        riddle room of `ending`."""
        for c in data.RIDDLE_ROOMS_BY_ENDING.get(str(ending).lower(), ()):
            if c.lower() == str(code).lower():
                return c
        return None

    def identity(self, ending, code):
        """(wave, room) of the riddle that room `code` of `ending` really shows: itself, unless riddle rando swapped it.
        Checks and unlock items belong to the RIDDLE, so everything that names a riddle goes through here."""
        ending = str(ending).lower()
        canon = self._canon(ending, code)
        if canon is None:
            return ending, str(code)          # not a riddle room (minigame, ...)
        look = self.applied_lookup
        if look is not None:
            se, sc = look(ending, canon)
        else:
            m = self.riddle_assignment()
            se, sc = riddle_rando.lookup(m, ending, canon) if m else (ending, canon)
        return str(se).lower(), self._canon(se, sc) or str(sc)

    def unlock_item_for(self, ending, code):
        """Name of the unlock item for room `code` of `ending`.  It belongs to the ROOM (the spot), not to whichever
        riddle riddle rando dealt into it: 'Unlock Bookshelf - Wave 1' always opens the Bookshelf room of wave 1."""
        canon = self._canon(ending, code) or str(code)
        return data.unlock_item_name(canon, str(ending).lower())

    def riddle_unlocked(self, ending, code):
        if not self.enabled or not self.options.riddle_lock:
            return True
        if self._canon(ending, code) is None:
            return True                       # not a riddle room (hallway, minigame, ...)
        return self._has(data.ITEM_ID[self.unlock_item_for(ending, code)])

    def tokens_received(self, ending):
        """Token codes of `ending` whose item has arrived."""
        return [c for c in data.TOKEN_CODES_BY_ENDING.get(ending, ()) if self.has_token(ending, c)]

    def has_door_key(self, door):
        return self._has(data.ITEM_ID[data.door_key_name(door)])

    def door_open(self, destination):
        """May the player go through the nav destination?  Destinations that aren't lockable doors are always open."""
        if not self.enabled or not self.options.door_locks:
            return True
        door = data.DOOR_BY_DESTINATION.get(destination)
        return True if door is None else self.has_door_key(door)

    def door_for(self, destination):
        return data.DOOR_BY_DESTINATION.get(destination)

    def redirect(self, ending, destination):
        """Entrance rando: where does clicking `destination` really lead?"""
        if not self.enabled or not self.options.entrance_rando:
            return destination
        return (self.entrances.get(ending) or {}).get(destination, destination)

    def may_award_token(self, ending, code):
        """Item shuffle: the game only gives a token once the matching item has been received."""
        if not self.enabled or not self.options.item_shuffle:
            return True
        if code not in data.TOKEN_CODES_BY_ENDING.get(ending, ()):
            return True                       # level-2 hunt tokens are not shuffled
        return self.has_token(ending, code)

    def filler_pending(self):
        n = sum(1 for i in self.received if i == data.FILLER_ID)
        return max(0, n - self.filler_seen)

    # ---- events -> location ids to send ------------------------------------------------------------------
    def _mark(self, name):
        lid = data.LOCATION_ID.get(name)
        if lid is None or lid in self.checked:
            return []
        self.checked.add(lid)
        return [lid]

    def riddle_solved(self, ending, code):
        if not self.enabled:
            return []
        se, sc = self.identity(ending, code)
        return self._mark(data.riddle_location_name(se, sc))

    def clue_found(self, ending, code, index):
        """index is 1-based within the riddle's words (GL_ words excluded).  Named after the riddle shown."""
        se, sc = self.identity(ending, code)
        if not self.wants_every_object() or index < 1 or index > data.CLUE_COUNT.get(se, {}).get(sc, 0):
            return []
        return self._mark(data.clue_location_name(se, sc, index))

    def minigame_match(self, ending, code):
        if not self.enabled:
            return []
        key = '%s:%s' % (code, ending)
        n = self.matches[key] = self.matches.get(key, 0) + 1
        if n <= self.options.minigame_item_checks:
            return self._mark(data.minigame_match_location_name(ending, code, n))
        return []

    def minigame_played(self, ending, code):
        """A minigame run (3 wins) finished."""
        if not self.enabled:
            return []
        key = '%s:%s' % (code, ending)
        n = self.plays[key] = self.plays.get(key, 0) + 1
        if n <= self.options.advanced_minigame_checks:
            return self._mark(data.minigame_play_location_name(ending, code, n))
        return []

    # ---- riddle rando ------------------------------------------------------------------------------------
    def riddle_assignment(self):
        """{ending: {room: [source ending, source room]}} when riddle rando is on and the slot gave a seed, else {}.
        Dealt once and then kept in the save, so a later Python / seed change cannot reshuffle a running game."""
        if not (self.enabled and self.options.riddle_rando):
            return {}
        sm = self.slot_riddle_map or {}
        if sm and all(e in sm for e in self.options.endings):
            return sm                         # the APWorld dealt the riddles: its locations / items are named after them
        if self.riddle_seed is None:
            return {}
        m = self.riddle_map or {}
        want = ''.join(self.options.endings)
        if m.get('seed') != self.riddle_seed or m.get('endings') != want or not m.get('map'):
            m = {'seed': self.riddle_seed, 'endings': want,
                 'map': riddle_rando.make_assignment(self.riddle_seed, self.options.endings)}
            self.riddle_map = m
        return m['map']

    def wants_every_object(self):
        return self.enabled and self.options.riddle_shuffle == RIDDLE_SHUFFLE_EVERY_OBJECT

    def wave_complete(self, ending):
        """Location ids for beating `ending` (the 'Finish <ending>' check).  Only waves the slot plays have one."""
        ending = str(ending).lower()
        if not self.enabled or ending not in self.options.endings:
            return []
        return self._mark(data.wave_complete_location_name(ending))

    def ending_completed(self, ending):
        """Record a finished ending; True when every selected ending is now done (the AP goal)."""
        ending = str(ending).lower()
        if ending not in self.completed:
            self.completed.append(ending)
        return all(e in self.completed for e in self.options.endings)

    # ---- persistence ---------------------------------------------------------------------------------
    def to_dict(self):
        return {'enabled': self.enabled, 'options': self.options.to_dict(), 'received': self.received,
                'checked': sorted(self.checked), 'matches': self.matches, 'plays': self.plays,
                'address': self.address, 'slot_name': self.slot_name, 'password': self.password,
                'filler_seen': self.filler_seen, 'completed': self.completed, 'entrances': self.entrances,
                'riddle_seed': self.riddle_seed, 'riddle_map': self.riddle_map,
                'slot_riddle_map': self.slot_riddle_map}

    @classmethod
    def from_dict(cls, d):
        s = cls(APOptions.from_slot_data((d or {}).get('options')))
        d = d or {}
        s.enabled = bool(d.get('enabled'))
        s.received = [int(x) for x in d.get('received', [])]
        s.checked = {int(x) for x in d.get('checked', [])}
        s.matches = dict(d.get('matches', {}))
        s.plays = dict(d.get('plays', {}))
        s.address = str(d.get('address', ''))
        s.slot_name = str(d.get('slot_name', ''))
        s.password = str(d.get('password', ''))
        s.filler_seen = int(d.get('filler_seen', 0))
        s.completed = [str(x) for x in d.get('completed', [])]
        s.entrances = {str(k): dict(v) for k, v in (d.get('entrances') or {}).items()}
        seed = d.get('riddle_seed')
        s.riddle_seed = int(seed) if isinstance(seed, (int, float, str)) and str(seed).lstrip('-').isdigit() else None
        s.riddle_map = dict(d.get('riddle_map') or {})
        s.slot_riddle_map = dict(d.get('slot_riddle_map') or {})
        return s

    def save(self, path):
        try:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            tmp = path + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(self.to_dict(), f, indent=1)
            os.replace(tmp, path)
        except OSError as e:
            print('[ap] could not save state:', e)

    @classmethod
    def load(cls, path):
        try:
            with open(path) as f:
                return cls.from_dict(json.load(f))
        except (OSError, ValueError):
            return cls()
