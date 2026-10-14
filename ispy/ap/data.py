"""Item / location tables shared by the game client and the APWorld.

IDs are assigned deterministically from the ordered tables below, so the client and the world always agree.
**Append only**: inserting or reordering entries renumbers everything after them.  Pure Python (no pygame).

The room/token tables come straight from data/handlers.json (getSpookyData_A/B/C):
  * level 1 of every ending has 15 tokens: 13 riddle rooms + the two minigames (MT = Mystery Bins/Memory Match,
    CC = Creepy Collections);
  * the rooms differ per ending: A has KT (riddle) + IW (riddle); B swaps KT for SS and keeps IW; C has SS and
    KT, and its 'IW' is the Ghost Machine workshop (not a riddle).
"""
from .options import ENDINGS, MAX_MINIGAME_CHECKS, MAX_ADVANCED_CHECKS

GAME_NAME = 'I Spy Spooky Mansion Deluxe'
BASE_ID = 7_730_000

WAVE = {'a': 1, 'b': 2, 'c': 3}
ENDING_NAME = {'a': 'Painting Message', 'b': 'Shrinking Soup', 'c': 'Ghost Machine'}
# what the 15 tokens physically are in each ending
TOKEN_KIND = {'a': 'Puzzle Piece', 'b': 'Stew Ingredient', 'c': 'Machine Part'}

MINIGAMES = ('MT', 'CC')
RIDDLE_ROOMS_BY_ENDING = {
    'a': ('fp', 'KT', 'ba', 'AR', 'CH', 'BK', 'MG', 'AT', 'KY', 'CL', 'PL', 'WI', 'IW'),
    'b': ('fp', 'SS', 'ba', 'AR', 'CH', 'BK', 'MG', 'AT', 'KY', 'CL', 'PL', 'WI', 'IW'),
    'c': ('fp', 'SS', 'ba', 'AR', 'CH', 'BK', 'MG', 'AT', 'KY', 'CL', 'PL', 'WI', 'KT'),
}
TOKEN_CODES_BY_ENDING = {e: RIDDLE_ROOMS_BY_ENDING[e] + MINIGAMES for e in ENDINGS}

# riddle words ("clues") per room, excluding the two GL_ words every riddle has; from pRiddleWordRectList
CLUE_COUNT = {
    'a': {'fp': 10, 'KT': 10, 'ba': 10, 'AR': 10, 'CH': 10, 'BK': 8, 'MG': 10, 'AT': 12, 'KY': 10, 'CL': 10,
          'PL': 10, 'WI': 11, 'IW': 9},
    'b': {'fp': 10, 'ba': 10, 'AR': 10, 'KY': 10, 'PL': 11, 'WI': 10, 'CH': 11, 'BK': 9, 'SS': 9, 'MG': 10,
          'AT': 9, 'CL': 9, 'IW': 8},
    'c': {'MG': 9, 'AT': 10, 'fp': 11, 'WI': 11, 'CL': 11, 'AR': 11, 'CH': 10, 'PL': 10, 'BK': 10, 'ba': 9,
          'KT': 10, 'KY': 11, 'SS': 12},
}

# Friendly names are best guesses (only the labels change if you edit them; the codes are what the game uses).
ROOM_LABEL = {
    'fp': 'Fireplace', 'KT': 'Kitchen', 'ba': 'Bathroom', 'AR': 'Armoire', 'CH': 'Chest',
    'BK': 'Bookshelf', 'MG': 'Magnifying Glass', 'AT': 'Attic', 'KY': 'Cabinet', 'CL': 'Clock',
    'PL': 'Dining Table', 'WI': 'Window', 'IW': 'Workshop', 'SS': 'Study',
    'MT': 'Mystery Bins', 'CC': 'Creepy Collections',
}

# lockable doors -> nav destination handed to movie.navigate()
# (The 'Secret Room' (SE) is the Secret Message painting, not a room: it is never locked.)
DOORS = {
    'Dining Room': 'DM', 'Kitchen': 'KT', 'Attic': 'AT', 'Bedroom': 'BM',
    'Bathroom': 'ba', 'Library': 'SM', 'Ghost Machine': 'IW',
}

FILLER_NAME = 'You Found Me'


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
    for e in ENDINGS:                                   # appended last (added after the first release of the tables)
        for c in RIDDLE_ROOMS_BY_ENDING[e]:
            names += [clue_location_name(e, c, n) for n in range(1, CLUE_COUNT[e][c] + 1)]
    names += [wave_complete_location_name(e) for e in ENDINGS]       # appended after the clue checks
    return names


ITEM_NAMES = _item_names()
LOCATION_NAMES = _location_names()
ITEM_ID = {n: BASE_ID + i for i, n in enumerate(ITEM_NAMES)}
LOCATION_ID = {n: BASE_ID + i for i, n in enumerate(LOCATION_NAMES)}
ITEM_NAME_BY_ID = {v: k for k, v in ITEM_ID.items()}
LOCATION_NAME_BY_ID = {v: k for k, v in LOCATION_ID.items()}

# --- reverse lookups the in-game hooks use -------------------------------------------------------------
TOKEN_ITEM_LOOKUP = {ITEM_ID[token_item_name(e, c)]: (e, c) for e in ENDINGS for c in TOKEN_CODES_BY_ENDING[e]}
UNLOCK_ITEM_LOOKUP = {ITEM_ID[unlock_item_name(c, e)]: (e, c) for e in ENDINGS for c in RIDDLE_ROOMS_BY_ENDING[e]}
DOOR_KEY_LOOKUP = {ITEM_ID[door_key_name(d)]: d for d in DOORS}
FILLER_ID = ITEM_ID[FILLER_NAME]
DOOR_BY_DESTINATION = {dest: door for door, dest in DOORS.items()}
