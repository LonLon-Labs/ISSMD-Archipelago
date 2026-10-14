from dataclasses import dataclass

from Options import Choice, DefaultOnToggle, OptionSet, PerGameCommonOptions, Range, Toggle

from .Data import ENDING_NAME, MAX_ADVANCED_CHECKS, MAX_MINIGAME_CHECKS


class RiddleLock(Toggle):
    """Riddles are locked until you receive their "Unlock <room> - Wave N" item."""
    display_name = "Riddle Lock"


class ItemShuffle(Toggle):
    """The puzzle pieces / stew ingredients / machine parts become multiworld items.
    The game only gives you a token once you have received the matching item."""
    display_name = "Item Shuffle"


class RiddleShuffle(Choice):
    """When riddle checks are sent.
    end_only: one check when a riddle is finished.
    every_object: one check for every clue you find, plus one for finishing the riddle."""
    display_name = "Riddle Shuffle"
    option_end_only = 0
    option_every_object = 1
    default = 0


class MinigameItemChecks(Range):
    """The first X matches in Mystery Bins and in Creepy Collections are each a check (per wave)."""
    display_name = "Minigame Item Checks"
    range_start = 0
    range_end = MAX_MINIGAME_CHECKS
    default = 0


class AdvancedMinigameChecks(Range):
    """Each round won in Mystery Bins / Creepy Collections from the third win of a visit onward is a check, up to X per
    minigame (per wave): the win that solves the riddle is the first, every extra round after it is another."""
    display_name = "Advanced Minigame Checks"
    range_start = 0
    range_end = MAX_ADVANCED_CHECKS
    default = 0


class Endings(OptionSet):
    """Which endings (waves) you play; the others are skipped. Your goal is to complete every one you pick."""
    display_name = "Endings"
    valid_keys = frozenset(ENDING_NAME.values())
    default = frozenset(ENDING_NAME.values())


class RiddleRando(Toggle):
    """Riddle identities are swapped between rooms (no repeats within a run). Handled by the game client."""
    display_name = "Riddle Rando"


class EntranceRando(Toggle):
    """Clicking a door/object inside a room can lead to a different room of the same area."""
    display_name = "Entrance Rando"


class DoorLocks(Toggle):
    """Eight doors need their key item ("Bedroom Key", ...) before you can go through them."""
    display_name = "Door Locks"


class FillerItems(DefaultOnToggle):
    """Pad the item pool with "You Found Me" filler. When off, the lowest-priority checks (replays, then matches,
    then clues) are removed instead so no filler is needed."""
    display_name = "Filler Items"


@dataclass
class ISpyOptions(PerGameCommonOptions):
    riddle_lock: RiddleLock
    item_shuffle: ItemShuffle
    riddle_shuffle: RiddleShuffle
    minigame_item_checks: MinigameItemChecks
    advanced_minigame_checks: AdvancedMinigameChecks
    endings: Endings
    riddle_rando: RiddleRando
    entrance_rando: EntranceRando
    door_locks: DoorLocks
    filler_items: FillerItems
