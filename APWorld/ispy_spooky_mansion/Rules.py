from . import Data as D
from .Logic import finale_requirements


def set_rules(world):
    player, mw = world.player, world.multiworld
    opts = world.options
    planned = {n for n, _e, _c in world.planned_locations}
    for e in world.endings:
        req = finale_requirements(e, world.entrance_map, opts.item_shuffle.value, opts.door_locks.value,
                                  opts.riddle_lock.value, world.riddle_map)
        names = [D.ending_event_location_name(e)]
        if D.wave_complete_location_name(e) in planned:        # the real 'Finish <wave>' check needs the same as the goal
            names.append(D.wave_complete_location_name(e))
        if req:
            for n in names:
                mw.get_location(n, player).access_rule = lambda state, req=req: state.has_all(req, player)
    goal_items = [D.ending_event_item_name(e) for e in world.endings]
    mw.completion_condition[player] = lambda state: state.has_all(goal_items, player)
