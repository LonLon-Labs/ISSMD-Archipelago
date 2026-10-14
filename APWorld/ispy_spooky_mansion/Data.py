"""Item / location tables for the I Spy Spooky Mansion Deluxe APWorld.

This is the APWorld's own copy of ispy/ap/data.py (a world cannot import the game).  IDs come from the ordered tables,
so the two copies MUST stay identical -- tests/test_apworld_parity.py in the game repo compares them.  Append only.
No Archipelago imports here, so it can be unit-tested anywhere.
"""
ENDINGS = ('a', 'b', 'c')
MAX_MINIGAME_CHECKS = 32
MAX_ADVANCED_CHECKS = 10

GAME_NAME = 'I Spy Spooky Mansion Deluxe'
BASE_ID = 7_730_000

WAVE = {'a': 1, 'b': 2, 'c': 3}
ENDING_NAME = {'a': 'Painting Message', 'b': 'Shrinking Soup', 'c': 'Ghost Machine'}
TOKEN_KIND = {'a': 'Puzzle Piece', 'b': 'Stew Ingredient', 'c': 'Machine Part'}

MINIGAMES = ('MT', 'CC')
FILLER_NAME = 'You Found Me'

RIDDLE_ROOMS_BY_ENDING = {
    'a': ('fp', 'KT', 'ba', 'AR', 'CH', 'BK', 'MG', 'AT', 'KY', 'CL', 'PL', 'WI', 'IW'),
    'b': ('fp', 'SS', 'ba', 'AR', 'CH', 'BK', 'MG', 'AT', 'KY', 'CL', 'PL', 'WI', 'IW'),
    'c': ('fp', 'SS', 'ba', 'AR', 'CH', 'BK', 'MG', 'AT', 'KY', 'CL', 'PL', 'WI', 'KT'),
}
TOKEN_CODES_BY_ENDING = {e: RIDDLE_ROOMS_BY_ENDING[e] + MINIGAMES for e in ENDINGS}

CLUE_COUNT = {
    'a': {'fp': 10, 'KT': 10, 'ba': 10, 'AR': 10, 'CH': 10, 'BK': 8, 'MG': 10, 'AT': 12, 'KY': 10, 'CL': 10,
          'PL': 10, 'WI': 11, 'IW': 9},
    'b': {'fp': 10, 'ba': 10, 'AR': 10, 'KY': 10, 'PL': 11, 'WI': 10, 'CH': 11, 'BK': 9, 'SS': 9, 'MG': 10,
          'AT': 9, 'CL': 9, 'IW': 8},
    'c': {'MG': 9, 'AT': 10, 'fp': 11, 'WI': 11, 'CL': 11, 'AR': 11, 'CH': 10, 'PL': 10, 'BK': 10, 'ba': 9,
          'KT': 10, 'KY': 11, 'SS': 12},
}

ROOM_LABEL = {
    'fp': 'Fireplace', 'KT': 'Kitchen', 'ba': 'Bathroom', 'AR': 'Armoire', 'CH': 'Chest',
    'BK': 'Bookshelf', 'MG': 'Magnifying Glass', 'AT': 'Attic', 'KY': 'Cabinet', 'CL': 'Clock',
    'PL': 'Dining Table', 'WI': 'Window', 'IW': 'Workshop', 'SS': 'Study',
    'MT': 'Mystery Bins', 'CC': 'Creepy Collections',
}

# lockable doors -> nav destination
# (The 'Secret Room' (SE) is the Secret Message painting, not a room: it is never locked.)
DOORS = {
    'Dining Room': 'DM', 'Kitchen': 'KT', 'Attic': 'AT', 'Bedroom': 'BM',
    'Bathroom': 'ba', 'Library': 'SM', 'Ghost Machine': 'IW',
}
DOOR_BY_DESTINATION = {dest: door for door, dest in DOORS.items()}

# ---- mansion layout (world-only; from the pButtList destinations in getSpookyData_A/B/C) ---------------------
# nav screen -> the rooms behind its buttons that are leaves (rooms, not further nav screens).  Entrance rando
# shuffles leaves within one group; a group's parent screen may itself sit behind a door.
LEAF_GROUPS = {
    'a': {'FOYER': ('KY', 'IW'), 'PM': ('WI', 'fp', 'MT'), 'HM': ('AT', 'CC'), 'DM': ('CL', 'PL', 'KT'),
          'BM': ('ba', 'AR', 'CH'), 'SM': ('BK', 'MG')},
    'b': {'FOYER': ('KY', 'IW'), 'PM': ('WI', 'fp', 'MT'), 'HM': ('AT', 'CC'), 'DM': ('CL', 'PL', 'KT'),
          'BM': ('ba', 'AR', 'CH'), 'SM': ('BK', 'SS', 'MG')},
    'c': {'FOYER': ('KY', 'IW'), 'PM': ('WI', 'fp', 'MT'), 'HM': ('AT', 'CC'), 'DM': ('CL', 'PL', 'KT'),
          'BM': ('ba', 'AR', 'CH'), 'SM': ('BK', 'SS', 'MG')},
}
# the door key needed to get to a group's parent screen (None = always reachable)
GROUP_PARENT_DOOR = {'FOYER': None, 'PM': None, 'HM': None, 'SM': 'Library', 'DM': 'Dining Room', 'BM': 'Bedroom'}


def label(code):
    return ROOM_LABEL.get(code, code)


def token_item_name(ending, code):
    return '%s %s - %s' % (ENDING_NAME[ending], TOKEN_KIND[ending], label(code))


def unlock_item_name(code, ending):
    return 'Unlock %s - Wave %d' % (label(code), WAVE[ending])


def door_key_name(door):
    return '%s Key' % door


def riddle_location_name(ending, code):
    return '%s Riddle Solved - Wave %d' % (label(code), WAVE[ending])


def clue_location_name(ending, code, n):
    return '%s Clue %d - Wave %d' % (label(code), n, WAVE[ending])


def minigame_match_location_name(ending, code, n):
    return '%s Match %d - Wave %d' % (label(code), n, WAVE[ending])


def minigame_play_location_name(ending, code, n):
    return '%s Play %d - Wave %d' % (label(code), n, WAVE[ending])


def wave_complete_location_name(ending):
    """The check you get for finishing (beating) a wave."""
    return 'Finish %s - Wave %d' % (ENDING_NAME[ending], WAVE[ending])


def ending_event_location_name(ending):
    return 'Complete %s' % ENDING_NAME[ending]


def ending_event_item_name(ending):
    return 'Ending Complete - %s' % ENDING_NAME[ending]


def _item_names():
    names = []
    for e in ENDINGS:
        names += [token_item_name(e, c) for c in TOKEN_CODES_BY_ENDING[e]]
    for e in ENDINGS:
        names += [unlock_item_name(c, e) for c in RIDDLE_ROOMS_BY_ENDING[e]]
    names += [door_key_name(d) for d in DOORS]
    names.append(FILLER_NAME)
    return names


def _location_names():
    names = []
    for e in ENDINGS:
        names += [riddle_location_name(e, c) for c in TOKEN_CODES_BY_ENDING[e]]
    for e in ENDINGS:
        for c in MINIGAMES:
            names += [minigame_match_location_name(e, c, n) for n in range(1, MAX_MINIGAME_CHECKS + 1)]
    for e in ENDINGS:
        for c in MINIGAMES:
            names += [minigame_play_location_name(e, c, n) for n in range(1, MAX_ADVANCED_CHECKS + 1)]
    for e in ENDINGS:
        for c in RIDDLE_ROOMS_BY_ENDING[e]:
            names += [clue_location_name(e, c, n) for n in range(1, CLUE_COUNT[e][c] + 1)]
    names += [wave_complete_location_name(e) for e in ENDINGS]
    return names


ITEM_NAMES = _item_names()
LOCATION_NAMES = _location_names()
ITEM_ID = {n: BASE_ID + i for i, n in enumerate(ITEM_NAMES)}
LOCATION_ID = {n: BASE_ID + i for i, n in enumerate(LOCATION_NAMES)}
