"""I Spy Spooky Mansion Deluxe -- Archipelago world."""
from BaseClasses import Tutorial
from Options import OptionError
from worlds.AutoWorld import WebWorld, World

from . import Data as D
from .Items import ISpyItem, classification_for, item_name_groups, item_name_to_id
from .Locations import location_name_groups, location_name_to_id
from .Logic import PoolError, make_entrances, plan_pool, slot_entrances
from .Options import ISpyOptions
from .RiddleRando import make_assignment
from .Regions import create_regions
from .Rules import set_rules


class ISpyWeb(WebWorld):
    theme = 'ocean'
    tutorials = [Tutorial(
        'Multiworld Setup Guide',
        'How to play I Spy Spooky Mansion Deluxe (the Python port) with Archipelago.',
        'English', 'setup_en.md', 'setup/en', ['Wesley'])]


class ISpySpookyWorld(World):
    """I Spy Spooky Mansion Deluxe: find the hidden objects in each riddle, win the minigames and collect all 15
    pieces to finish an ending. Riddles, door keys and the pieces themselves can be scattered across a multiworld."""
    game = D.GAME_NAME
    web = ISpyWeb()
    options_dataclass = ISpyOptions
    options: ISpyOptions
    topology_present = False

    item_name_to_id = item_name_to_id
    location_name_to_id = location_name_to_id
    item_name_groups = item_name_groups
    location_name_groups = location_name_groups

    endings: tuple
    entrance_map: dict
    riddle_map: dict
    planned_locations: list
    planned_items: list
    filler_count: int

    def generate_early(self):
        names = set(self.options.endings.value)
        self.endings = tuple(e for e in D.ENDINGS if D.ENDING_NAME[e] in names)
        if not self.endings:
            raise OptionError('%s: pick at least one ending.' % self.player_name)
        o = self.options
        self.entrance_map = make_entrances(self.random, self.endings, bool(o.entrance_rando))
        self.riddle_map = make_assignment(self.random, self.endings) if bool(o.riddle_rando) else {}
        try:
            self.planned_locations, self.planned_items, self.filler_count = plan_pool(
                self.endings, bool(o.item_shuffle), bool(o.riddle_lock), bool(o.door_locks),
                o.riddle_shuffle.value == 1, o.minigame_item_checks.value, o.advanced_minigame_checks.value,
                bool(o.filler_items), self.riddle_map)
        except PoolError as e:
            raise OptionError('%s: %s' % (self.player_name, e))

    def create_regions(self):
        create_regions(self)

    def create_item(self, name):
        return ISpyItem(name, classification_for(name), D.ITEM_ID.get(name), self.player)

    def create_items(self):
        self.multiworld.itempool += [self.create_item(n) for n in self.planned_items]
        self.multiworld.itempool += [self.create_item(D.FILLER_NAME) for _ in range(self.filler_count)]

    def set_rules(self):
        set_rules(self)

    def get_filler_item_name(self):
        return D.FILLER_NAME

    def fill_slot_data(self):
        o = self.options
        return {
            'options': {
                'riddle_lock': bool(o.riddle_lock),
                'item_shuffle': bool(o.item_shuffle),
                'riddle_shuffle': o.riddle_shuffle.value,
                'minigame_item_checks': o.minigame_item_checks.value,
                'advanced_minigame_checks': o.advanced_minigame_checks.value,
                'endings': ''.join(self.endings),
                'riddle_rando': bool(o.riddle_rando),
                'entrance_rando': bool(o.entrance_rando),
                'door_locks': bool(o.door_locks),
                'filler_items': bool(o.filler_items),
            },
            'entrances': slot_entrances(self.entrance_map) if o.entrance_rando else {},
            'riddle_map': self.riddle_map,                  # {ending: {room: [source ending, source room]}}
            'riddle_seed': self.random.getrandbits(32),     # fallback for older clients
        }
