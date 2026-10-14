"""Archipelago options for I Spy Spooky Mansion Deluxe.

The same option names are used by the APWorld (YAML), by `slot_data`, and here, so a slot's `slot_data['options']`
can be fed straight into `APOptions.from_slot_data`.  Pure Python, no pygame, no game imports (unit-testable).
"""
from dataclasses import dataclass, asdict

ENDINGS = ('a', 'b', 'c')          # version letters: a = Painting Message, b = Shrinking Soup, c = Ghost Machine

RIDDLE_SHUFFLE_END_ONLY = 0        # the item arrives only when the riddle is finished
RIDDLE_SHUFFLE_EVERY_OBJECT = 1    # an item for every object found, plus one for finishing the riddle

MAX_MINIGAME_CHECKS = 32           # hard cap on per-match checks per minigame per ending
MAX_ADVANCED_CHECKS = 10           # hard cap on extra replay checks per minigame per ending


def _bool(v, default=False):
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(v)


def _int(v, lo, hi, default=0):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _endings(v):
    """Accepts 'abc', ['a', 'c'], ('b',), a set, or None (all).  Always returns a non-empty, ordered tuple."""
    if v is None:
        return ENDINGS
    if isinstance(v, str):
        v = list(v.lower())
    picked = {str(x).strip().lower() for x in v}
    out = tuple(e for e in ENDINGS if e in picked)
    return out or ENDINGS


@dataclass
class APOptions:
    riddle_lock: bool = False               # riddles are locked behind "Unlock <room> - Wave n" items
    item_shuffle: bool = False              # pieces / ingredients / parts come from the multiworld, not the riddles
    riddle_shuffle: int = RIDDLE_SHUFFLE_END_ONLY
    minigame_item_checks: int = 0           # X: the first X matches in each minigame are locations
    advanced_minigame_checks: int = 0       # X: playing Creepy Collections / Mystery Bins X times gives extra checks
    endings: tuple = ENDINGS                # which endings (waves) are played; the rest are skipped
    riddle_rando: bool = False              # riddles are shuffled between rooms / endings
    entrance_rando: bool = False            # nav buttons lead somewhere else
    door_locks: bool = False                # the 8 doors need key items
    filler_items: bool = True               # "You Found Me" filler

    @classmethod
    def from_slot_data(cls, d):
        d = dict(d or {})
        return cls(
            riddle_lock=_bool(d.get('riddle_lock')),
            item_shuffle=_bool(d.get('item_shuffle')),
            riddle_shuffle=_int(d.get('riddle_shuffle'), 0, 1),
            minigame_item_checks=_int(d.get('minigame_item_checks'), 0, MAX_MINIGAME_CHECKS),
            advanced_minigame_checks=_int(d.get('advanced_minigame_checks'), 0, MAX_ADVANCED_CHECKS),
            endings=_endings(d.get('endings')),
            riddle_rando=_bool(d.get('riddle_rando')),
            entrance_rando=_bool(d.get('entrance_rando')),
            door_locks=_bool(d.get('door_locks')),
            filler_items=_bool(d.get('filler_items'), True),
        )

    def to_dict(self):
        d = asdict(self)
        d['endings'] = ''.join(self.endings)
        return d

    def plays(self, version):
        return str(version).lower() in self.endings
