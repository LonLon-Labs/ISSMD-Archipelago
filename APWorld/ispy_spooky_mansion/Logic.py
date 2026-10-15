"""Pure-Python world logic (no Archipelago imports, so it is unit-testable anywhere).

Everything the Archipelago-facing modules need is decided here:
  * which locations / items exist for a given option set,
  * which items are required to reach a room,
  * the entrance-rando permutation.
"""
from . import Data as D
from .RiddleRando import identity


class PoolError(ValueError):
    pass


# ---- locations / items -----------------------------------------------------------------------------------
# `assignment` = riddle rando's {ending: {room: [source ending, source room]}} (None / empty = every room shows its own
# riddle).  Riddle / clue LOCATIONS are named after the RIDDLE shown; the (ending, room) a location is placed in (and so
# the access rules) are those of the ROOM it is played in.  Unlock ITEMS belong to the ROOM, not the riddle in it.
FINALE = 'FINALE'            # pseudo room code: the 'Finish <wave>' location is not inside any room


def plan_locations(endings, every_object, match_checks, play_checks, assignment=None):
    """[(location name, ending, room code)] in priority order (highest first)."""
    solved, finish, clues, matches, plays = [], [], [], [], []
    for e in endings:
        for c in D.TOKEN_CODES_BY_ENDING[e]:
            se, sc = identity(assignment, e, c)
            solved.append((D.riddle_location_name(se, sc), e, c))
        finish.append((D.wave_complete_location_name(e), e, FINALE))
        if every_object:
            for c in D.RIDDLE_ROOMS_BY_ENDING[e]:
                se, sc = identity(assignment, e, c)
                clues += [(D.clue_location_name(se, sc, n), e, c) for n in range(1, D.CLUE_COUNT[se][sc] + 1)]
        for c in D.MINIGAMES:
            matches += [(D.minigame_match_location_name(e, c, n), e, c) for n in range(1, match_checks + 1)]
            plays += [(D.minigame_play_location_name(e, c, n), e, c) for n in range(1, play_checks + 1)]
    return solved + finish + clues + matches + plays


def plan_items(endings, item_shuffle, riddle_lock, door_locks, assignment=None):
    """Non-filler items (names)."""
    names = []
    if item_shuffle:
        for e in endings:
            names += [D.token_item_name(e, c) for c in D.TOKEN_CODES_BY_ENDING[e]]
    if riddle_lock:
        for e in endings:
            for c in D.RIDDLE_ROOMS_BY_ENDING[e]:
                names.append(D.unlock_item_name(c, e))
    if door_locks:
        names += [D.door_key_name(d) for d in D.DOORS]
    return names


def plan_pool(endings, item_shuffle, riddle_lock, door_locks, every_object, match_checks, play_checks, filler_items,
              assignment=None):
    """Returns (locations, items, filler_count).  Raises PoolError when the options cannot be satisfied."""
    locs = plan_locations(endings, every_object, match_checks, play_checks, assignment)
    items = plan_items(endings, item_shuffle, riddle_lock, door_locks, assignment)
    if not filler_items and len(locs) > len(items):
        locs = locs[:len(items)]                  # drop the lowest-priority checks instead of padding
    if len(items) > len(locs):
        raise PoolError(
            'These options create %d items but only %d locations. Pick more endings, set riddle_shuffle to '
            'every_object, raise the minigame check counts, or turn off one of item_shuffle / riddle_lock / '
            'door_locks.' % (len(items), len(locs)))
    if not items and not locs:
        raise PoolError('Nothing to randomize.')
    return locs, items, len(locs) - len(items)


# ---- entrance rando ---------------------------------------------------------------------------------------
def make_entrances(rng, endings, enabled):
    """{ending: {clicked destination: room actually entered}} for every leaf button (identity when disabled).

    Every room of a wave (all 13 riddle rooms plus the two minigames) is shuffled together, so any button can lead to
    any room, including one in a different hallway.  Door keys stay on the button / hallway that is clicked."""
    full = {}
    for e in endings:
        clicked_all = [c for leaves in D.LEAF_GROUPS[e].values() for c in leaves]
        targets = list(clicked_all)
        if enabled and len(targets) > 1:
            rng.shuffle(targets)
        full[e] = dict(zip(clicked_all, targets))
    return full


def slot_entrances(full):
    """Only the redirects that actually change something (what the client needs)."""
    return {e: {b: r for b, r in m.items() if b != r} for e, m in full.items()}


# ---- access requirements ---------------------------------------------------------------------------------
def room_requirements(ending, room, mapping, door_locks, riddle_lock, assignment=None):
    """Item names needed to be able to enter `room` in `ending`.

    Door keys AND riddle unlocks are checked on the button that is *clicked* (so with entrance rando: the clicked button
    that leads to `room`).  An unlock item belongs to the clicked riddle's own spot: clicking the Window needs
    'Unlock Window' even when entrance rando sends you to the Fireplace, and neither riddle rando nor entrance rando
    changes which unlock a button needs.
    """
    for group, leaves in D.LEAF_GROUPS[ending].items():
        clicked = next((b for b, r in mapping.get(ending, {}).items() if r == room and b in leaves), None)
        if clicked is None:
            continue
        req = set()
        parent_door = D.GROUP_PARENT_DOOR.get(group)
        if door_locks and parent_door:
            req.add(D.door_key_name(parent_door))
        door = D.DOOR_BY_DESTINATION.get(clicked)
        if door_locks and door:
            req.add(D.door_key_name(door))
        # The lock belongs to the SPOT that is clicked, whatever entrance rando put behind it (a riddle spot that now leads
        # to a minigame still needs its unlock).  The Mystery Bins / Creepy Collections spots themselves are never locked.
        if riddle_lock and clicked in D.RIDDLE_ROOMS_BY_ENDING[ending]:
            req.add(D.unlock_item_name(clicked, ending))
        return frozenset(req)
    return frozenset()


def finale_requirements(ending, mapping, item_shuffle, door_locks, riddle_lock, assignment=None):
    """Items needed to finish `ending` (all 15 tokens)."""
    if item_shuffle:
        return frozenset(D.token_item_name(ending, c) for c in D.TOKEN_CODES_BY_ENDING[ending])
    req = set()
    for c in D.TOKEN_CODES_BY_ENDING[ending]:
        req |= room_requirements(ending, c, mapping, door_locks, riddle_lock, assignment)
    return frozenset(req)
