from BaseClasses import Item, ItemClassification

from . import Data as D


class ISpyItem(Item):
    game = D.GAME_NAME


def classification_for(name):
    if name == D.FILLER_NAME:
        return ItemClassification.filler
    return ItemClassification.progression          # tokens, riddle unlocks and door keys all gate something


item_name_to_id = dict(D.ITEM_ID)

item_name_groups = {
    'Tokens': {n for n in D.ITEM_NAMES if any(n == D.token_item_name(e, c) for e in D.ENDINGS
                                               for c in D.TOKEN_CODES_BY_ENDING[e])},
    'Riddle Unlocks': {n for n in D.ITEM_NAMES if n.startswith('Unlock ')},
    'Door Keys': {D.door_key_name(d) for d in D.DOORS},
}
