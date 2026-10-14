from BaseClasses import Location

from . import Data as D


class ISpyLocation(Location):
    game = D.GAME_NAME


location_name_to_id = dict(D.LOCATION_ID)

location_name_groups = {
    'Riddles Solved': {n for n in D.LOCATION_NAMES if ' Riddle Solved - ' in n},
    'Clues': {n for n in D.LOCATION_NAMES if ' Clue ' in n},
    'Minigame Matches': {n for n in D.LOCATION_NAMES if ' Match ' in n},
    'Minigame Replays': {n for n in D.LOCATION_NAMES if ' Play ' in n},
    'Wave Completions': {D.wave_complete_location_name(e) for e in D.ENDINGS},
}
