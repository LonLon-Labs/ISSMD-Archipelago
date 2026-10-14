"""Fill / logic tests, run by Archipelago's own test runner (needs an Archipelago checkout; the pure logic is also
covered without Archipelago by tests/test_apworld_logic.py in the game repo).  WorldTestBase additionally runs its
default tests (everything reachable with all items, something reachable with none, ...) for every class here."""
import random
import unittest

from . import ISpyTestBase
from .. import Data as D
from ..Logic import plan_locations, plan_items, room_requirements
from ..RiddleRando import MAG_ROOMS, identity, make_assignment


def names(endings):
    return [D.ENDING_NAME[e] for e in endings]


def real_locations(world):
    return [loc for loc in world.multiworld.get_locations(world.player) if loc.address is not None]


class TestDefault(ISpyTestBase):
    def test_pool_matches_locations(self):
        world = self.multiworld.worlds[1]
        self.assertEqual(len(real_locations(world)), 48)               # 45 riddle-solved + 3 'Finish <wave>'
        self.assertEqual(len(world.planned_items) + world.filler_count, 48)

    def test_goal_needs_nothing(self):
        self.assertBeatable(True)


class TestItemShuffle(ISpyTestBase):
    options = {'item_shuffle': True}

    def test_finish_locations_need_the_wave_tokens(self):
        tokens = [D.token_item_name('a', c) for c in D.TOKEN_CODES_BY_ENDING['a']]
        self.assertFalse(self.can_reach_location(D.wave_complete_location_name('a')))
        self.collect_by_name(tokens)
        self.assertTrue(self.can_reach_location(D.wave_complete_location_name('a')))
        self.assertFalse(self.can_reach_location(D.wave_complete_location_name('b')))

    def test_goal_needs_every_token(self):
        tokens = [D.token_item_name(e, c) for e in D.ENDINGS for c in D.TOKEN_CODES_BY_ENDING[e]]
        self.collect_all_but(tokens[:1])
        self.assertBeatable(False)
        self.collect_by_name(tokens[:1])
        self.assertBeatable(True)


class TestSingleEnding(ISpyTestBase):
    options = {'endings': names('b'), 'item_shuffle': True, 'riddle_shuffle': 1}

    def test_only_that_wave(self):
        for loc in real_locations(self.multiworld.worlds[1]):
            self.assertIn('Wave 2', loc.name)

    def test_goal_needs_its_tokens_only(self):
        self.collect_by_name([D.token_item_name('b', c) for c in D.TOKEN_CODES_BY_ENDING['b']])
        self.assertBeatable(True)


class TestTwoEndings(ISpyTestBase):
    options = {'endings': names('ac'), 'riddle_lock': True, 'item_shuffle': True, 'riddle_shuffle': 1}

    def test_unplayed_wave_has_no_locations(self):
        for loc in real_locations(self.multiworld.worlds[1]):
            self.assertNotIn('Wave 2', loc.name)


class TestDoorLocks(ISpyTestBase):
    options = {'door_locks': True, 'riddle_shuffle': 1}

    def test_bedroom_rooms_need_the_key(self):
        self.assertFalse(self.can_reach_location('Bathroom Riddle Solved - Wave 1'))
        self.collect_by_name([D.door_key_name('Bedroom'), D.door_key_name('Bathroom')])
        self.assertTrue(self.can_reach_location('Bathroom Riddle Solved - Wave 1'))

    def test_open_rooms_need_nothing(self):
        self.assertTrue(self.can_reach_location('Fireplace Riddle Solved - Wave 1'))


class TestRiddleLock(ISpyTestBase):
    options = {'riddle_lock': True, 'riddle_shuffle': 1, 'minigame_item_checks': 4}

    def test_riddle_needs_its_unlock(self):
        self.assertFalse(self.can_reach_location('Fireplace Riddle Solved - Wave 1'))
        self.collect_by_name(D.unlock_item_name('fp', 'a'))
        self.assertTrue(self.can_reach_location('Fireplace Riddle Solved - Wave 1'))

    def test_minigames_are_never_locked(self):
        self.assertTrue(self.can_reach_location('Mystery Bins Match 1 - Wave 1'))


class TestEverything(ISpyTestBase):
    options = {'riddle_lock': True, 'item_shuffle': True, 'door_locks': True, 'riddle_shuffle': 1,
               'entrance_rando': True, 'riddle_rando': True, 'minigame_item_checks': 3,
               'advanced_minigame_checks': 2}

    def test_slot_data(self):
        sd = self.multiworld.worlds[1].fill_slot_data()
        self.assertTrue(sd['options']['riddle_rando'] and sd['options']['entrance_rando'])
        self.assertIn('riddle_seed', sd)
        self.assertEqual(sd['options']['endings'], 'abc')
        for e, redirects in sd['entrances'].items():
            self.assertEqual(sorted(redirects), sorted(set(redirects.values())))   # a permutation: same buttons as rooms
        self.assertIn('riddle_map', sd)
        self.assertEqual(set(sd['riddle_map']), set('abc'))


class TestRiddleRando(ISpyTestBase):
    options = {'riddle_lock': True, 'riddle_rando': True, 'riddle_shuffle': 1, 'minigame_item_checks': 4}

    def test_slot_data_has_riddle_map(self):
        sd = self.multiworld.worlds[1].fill_slot_data()
        self.assertTrue(sd['riddle_map'])
        for e, rooms in sd['riddle_map'].items():
            self.assertEqual(sorted(rooms), sorted(D.RIDDLE_ROOMS_BY_ENDING[e]))
            for src in rooms.values():
                self.assertEqual(len(src), 2)

    def test_each_riddle_used_once_and_mag_rooms_trade_together(self):
        rmap = self.multiworld.worlds[1].riddle_map
        used = [tuple(v) for rooms in rmap.values() for v in rooms.values()]
        self.assertEqual(len(used), len(set(used)))
        for e, rooms in rmap.items():
            for room, (_se, sc) in rooms.items():
                self.assertEqual(room in MAG_ROOMS, sc in MAG_ROOMS)

    def test_locations_and_items_are_named_after_the_shown_riddle(self):
        world = self.multiworld.worlds[1]
        placed = {n: (e, c) for n, e, c in world.planned_locations}
        for e, rooms in world.riddle_map.items():
            for room, (se, sc) in rooms.items():
                self.assertEqual(placed[D.riddle_location_name(se, sc)], (e, room))
                self.assertIn(D.unlock_item_name(sc, se), world.planned_items)

    def test_unlock_of_the_shown_riddle_gates_the_room(self):
        world = self.multiworld.worlds[1]
        se, sc = identity(world.riddle_map, 'a', 'fp')
        shown_unlock = D.unlock_item_name(sc, se)
        loc = D.riddle_location_name(se, sc)                   # lives in the Fireplace room, named after the shown riddle
        self.assertFalse(self.can_reach_location(loc))
        self.collect_by_name(shown_unlock)
        self.assertTrue(self.can_reach_location(loc))


class TestRiddleRandoLogic(unittest.TestCase):
    """Pure logic (no Archipelago world): the entrance rando MT -> fp + riddle rando Clock-in-Fireplace scenario."""
    SWAP = {'a': {'fp': ['a', 'CL'], 'CL': ['a', 'fp']}}
    MAPPING = {'a': {'MT': 'fp', 'fp': 'MT'}}

    def test_clicking_mt_enters_fireplace_which_shows_the_clock_riddle(self):
        self.assertEqual(identity(self.SWAP, 'a', 'fp'), ('a', 'CL'))
        req = room_requirements('a', 'fp', self.MAPPING, True, True, self.SWAP)
        self.assertEqual(req, frozenset({'Unlock Clock Room - Wave 1'}))

    def test_checks_are_clock_room_not_fireplace_for_that_room(self):
        locs = plan_locations(('a',), True, 0, 0, self.SWAP)
        placed = {n: (e, c) for n, e, c in locs}
        for n in range(1, D.CLUE_COUNT['a']['CL'] + 1):
            self.assertEqual(placed['Clock Room Clue %d - Wave 1' % n], ('a', 'fp'))
        for n in range(1, D.CLUE_COUNT['a']['fp'] + 1):
            self.assertEqual(placed['Fireplace Clue %d - Wave 1' % n], ('a', 'CL'))   # the swapped riddle lives in CL
        self.assertEqual(placed['Clock Room Riddle Solved - Wave 1'], ('a', 'fp'))
        items = plan_items(('a',), False, True, False, self.SWAP)
        self.assertIn('Unlock Clock Room - Wave 1', items)

    def test_without_riddle_rando_identity_is_the_room(self):
        self.assertEqual(identity({}, 'a', 'fp'), ('a', 'fp'))
        self.assertEqual(identity(None, 'b', 'CL'), ('b', 'CL'))

    def test_make_assignment_properties(self):
        for seed in range(50):
            amap = make_assignment(random.Random(seed), ('a', 'b', 'c'))
            used = [tuple(v) for rooms in amap.values() for v in rooms.values()]
            self.assertEqual(len(used), len(set(used)))
            for e, rooms in amap.items():
                for room, (_se, sc) in rooms.items():
                    self.assertEqual(room in MAG_ROOMS, sc in MAG_ROOMS)
