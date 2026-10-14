from BaseClasses import Region

from . import Data as D
from .Items import ISpyItem
from .Locations import ISpyLocation
from .Logic import FINALE, room_requirements
from BaseClasses import ItemClassification


def room_region_name(ending, code):
    return '%s (Wave %d)' % (D.label(code), D.WAVE[ending])


def create_regions(world):
    player, mw = world.player, world.multiworld
    menu = Region('Menu', player, mw)
    foyer = Region('Foyer', player, mw)
    mw.regions += [menu, foyer]
    menu.connect(foyer)

    rooms = {}
    for e in world.endings:
        for code in D.TOKEN_CODES_BY_ENDING[e]:
            region = Region(room_region_name(e, code), player, mw)
            rooms[(e, code)] = region
            mw.regions.append(region)
            req = room_requirements(e, code, world.entrance_map, world.options.door_locks.value,
                                    world.options.riddle_lock.value, world.riddle_map)
            foyer.connect(region, rule=(lambda state, req=req: state.has_all(req, player)) if req else None)

    for name, e, code in world.planned_locations:
        if code == FINALE:                                     # 'Finish <wave>': sits in the foyer, gated in Rules.py
            foyer.locations.append(ISpyLocation(player, name, D.LOCATION_ID[name], foyer))
            continue
        loc = ISpyLocation(player, name, D.LOCATION_ID[name], rooms[(e, code)])
        rooms[(e, code)].locations.append(loc)

    for e in world.endings:                                    # goal events
        loc = ISpyLocation(player, D.ending_event_location_name(e), None, foyer)
        loc.place_locked_item(ISpyItem(D.ending_event_item_name(e), ItemClassification.progression, None, player))
        foyer.locations.append(loc)
