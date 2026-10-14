"""Riddle rando: which riddle each riddle room shows.  Pure Python (no pygame, no game imports) so it is unit-testable.

A *riddle* is everything that makes up a riddle room's puzzle in one wave: the background picture, the clickable
objects, the riddle words / strip / audio, the skeleton's reward animation and, for the Magic Room and the Attic, the
magnifying-glass data.  There are 39 of them (13 riddle rooms x 3 waves; see data.RIDDLE_ROOMS_BY_ENDING).

Riddle rando deals the riddles out to the rooms again:
  * every room keeps its identity (its token, its locks, its checks, its place in the mansion and its level-2 hunt
    tokens); only the riddle shown inside it changes;
  * a riddle is used at most once per run ("no repeats"): the assignment is injective across every selected wave;
  * a room never shows its own riddle when it can be avoided;
  * the two magnifying-glass rooms (MG, AT) only trade with each other, because that screen is a different kind of
    screen (a different script with a lens); all the other rooms trade among themselves.

The assignment is a pure function of the slot's `riddle_seed` and the selected endings, and it is stored in the save
(APState.riddle_map) so it can never change under a running game.

Shape:  assignment = {ending: {room code: [source ending, source room code]}}   (JSON friendly)
"""
import random

from . import data

MAG_ROOMS = ('MG', 'AT')


def kind(code):
    return 'mag' if str(code).upper() in MAG_ROOMS else 'plain'


def all_riddles():
    """Every riddle that exists: [(ending, room code)] in stable order."""
    return [(e, c) for e in data.ENDINGS for c in data.RIDDLE_ROOMS_BY_ENDING[e]]


def _shuffled(rng, items):
    """Fisher-Yates built on rng.random() only, so the result is the same on every Python version."""
    items = list(items)
    for i in range(len(items) - 1, 0, -1):
        j = int(rng.random() * (i + 1))
        items[i], items[j] = items[j], items[i]
    return items


def make_assignment(seed, endings=data.ENDINGS):
    """Deal the riddles out to the riddle rooms of `endings`."""
    endings = tuple(e for e in data.ENDINGS if e in set(endings)) or data.ENDINGS
    rng = random.Random(int(seed))
    slots = [(e, c) for e in endings for c in data.RIDDLE_ROOMS_BY_ENDING[e]]
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


def lookup(assignment, ending, code):
    """(source ending, source room) for a room, falling back to the room's own riddle.  Room codes are compared
    case-insensitively (the game is not consistent about 'fp' / 'FP')."""
    rooms = (assignment or {}).get(str(ending).lower(), {})
    for k, v in rooms.items():
        if k.lower() == str(code).lower():
            return str(v[0]), str(v[1])
    return str(ending).lower(), str(code)


def is_valid(assignment):
    """No riddle used twice, every source exists, magnifier rooms only trade with each other."""
    seen, real = set(), set(all_riddles())
    for e, rooms in assignment.items():
        for c, (se, sc) in rooms.items():
            if (se, sc) not in real or kind(sc) != kind(c) or (se, sc) in seen:
                return False
            seen.add((se, sc))
    return True


# ---- applying an assignment to the game's data tables -----------------------------------------------------------
def _sym(x):
    return x.get('$sym', x) if isinstance(x, dict) else x


def _name(screen):
    return str(_sym(screen.get('pName')))


def _riddle_part(screen):
    """The dict that holds the riddle itself (the ancestor of a magnifier screen, else the screen)."""
    anc = screen.get('ancestor')
    return anc if isinstance(anc, dict) else screen


def is_riddle_screen(screen):
    return isinstance(screen, dict) and 'pRiddleObjectList' in _riddle_part(screen)


def clone(x):
    """Copy of nested dicts / lists; leaves (str / Sym / Point / Rect / numbers) are immutable and shared.
    (copy.deepcopy would mangle the tuple subclasses Point / Rect.)"""
    if isinstance(x, dict):
        return {k: clone(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clone(v) for v in x]
    return x


def _find(screens, code):
    for s in screens:
        if is_riddle_screen(s) and _name(s).lower() == str(code).lower():
            return s
    return None


# what a room keeps for itself when it takes another room's riddle
_KEEP = ('pName', 'pType', 'pSHTokenObjectList')


def transplant(slot, source):
    """New screen dict for the room `slot` that shows the riddle of `source` (both are screen dicts from
    handlers.json; neither is modified)."""
    new = clone(source)
    new['pName'] = slot['pName']
    new_part, slot_part = _riddle_part(new), _riddle_part(slot)
    if new_part is not new:                                # magnifier screen: the inner screen keeps the name too
        new_part['pName'] = slot_part['pName']
    for key in _KEEP:
        if key in slot_part:
            new_part[key] = clone(slot_part[key])
        else:
            new_part.pop(key, None)
    return new


def apply(version_data, ending, assignment, data_for):
    """The game data of `ending` with its riddle rooms swapped as `assignment` says.

    version_data = handlers['getSpookyData_<X>'] for `ending`;  data_for(e) returns the same for any ending.
    Returns a new top-level dict (version_data itself is left alone).  Rooms the assignment does not mention, and
    rooms whose source cannot be found, stay as they are."""
    rooms = (assignment or {}).get(ending)
    if not rooms:
        return version_data
    new = dict(version_data)
    screens = list(version_data['pLevelScreenList'])
    for i, slot in enumerate(screens):
        if not is_riddle_screen(slot):
            continue
        code = _name(slot)
        se, sc = lookup(assignment, ending, code)
        if (se, sc.lower()) == (ending, code.lower()):
            continue
        src = _find(data_for(se)['pLevelScreenList'], sc)
        if src is not None and kind(sc) == kind(code):
            screens[i] = transplant(slot, src)
    new['pLevelScreenList'] = screens
    return new
