"""Riddle rando: which riddle each riddle room shows.  Pure Python (no Archipelago imports), so it is unit-testable.

This mirrors ispy/ap/riddle_rando.make_assignment in the game repo.  The APWorld deals the riddles at generation time
and sends the result in slot_data['riddle_map'] -- the game uses that map as-is, so the two copies do not have to agree
bit for bit; the game only falls back to its own copy for slots generated before the map existed.

A *riddle* is identified by (wave, room): "the Clock Room riddle of wave 1".  Every room keeps its place in the mansion
(its token, its door / entrance logic, its level-2 hunt); only the riddle shown inside it changes.  Locations and unlock
items are named after the RIDDLE, so "Unlock Clock Room - Wave 1" opens the Clock Room riddle of wave 1 wherever it ends
up, and "Clock Room Clue 3 - Wave 1" is found while playing that riddle.

  * a riddle is used at most once across every selected wave (injective);
  * a room never keeps its own riddle when that can be avoided;
  * the two magnifying-glass rooms (MG, AT) only trade with each other (different kind of screen).
"""
import random

from . import Data as D

MAG_ROOMS = ('MG', 'AT')


def kind(code):
    return 'mag' if str(code).upper() in MAG_ROOMS else 'plain'


def all_riddles():
    """Every riddle that exists: [(ending, room code)] in stable order."""
    return [(e, c) for e in D.ENDINGS for c in D.RIDDLE_ROOMS_BY_ENDING[e]]


def _shuffled(rng, items):
    """Fisher-Yates built on rng.random() only, so the result is the same on every Python version."""
    items = list(items)
    for i in range(len(items) - 1, 0, -1):
        j = int(rng.random() * (i + 1))
        items[i], items[j] = items[j], items[i]
    return items


def make_assignment(rng, endings):
    """{ending: {room: [source ending, source room]}} for the riddle rooms of `endings`.  `rng` is a random.Random."""
    endings = tuple(e for e in D.ENDINGS if e in set(endings)) or D.ENDINGS
    slots = [(e, c) for e in endings for c in D.RIDDLE_ROOMS_BY_ENDING[e]]
    out = {e: {} for e in endings}
    for k in ('plain', 'mag'):
        mine = [s for s in slots if kind(s[1]) == k]
        pool = [r for r in all_riddles() if kind(r[1]) == k]
        deal = None
        for _ in range(300):                               # look for a deal where no room keeps its own riddle
            deal = _shuffled(rng, pool)[:len(mine)]
            if all(d != s for d, s in zip(deal, mine)):
                break
        for (e, c), (se, sc) in zip(mine, deal):
            out[e][c] = [se, sc]
    return out


def identity(assignment, ending, code):
    """(source ending, source room) of the riddle shown in room `code` of `ending` (itself without riddle rando)."""
    if assignment and code in D.RIDDLE_ROOMS_BY_ENDING.get(ending, ()):
        v = assignment.get(ending, {}).get(code)
        if v:
            return v[0], v[1]
    return ending, code
