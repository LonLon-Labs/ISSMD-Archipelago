# I Spy Spooky Mansion Deluxe

## What is randomized?

Pick any combination of the options in your YAML:

- **Riddle Lock** - each riddle room needs an "Unlock <room> - Wave N" item.
- **Item Shuffle** - the 15 puzzle pieces / stew ingredients / machine parts of each ending are multiworld items.
- **Riddle Shuffle** - checks come at the end of a riddle only, or for every clue found as well.
- **Minigame Item Checks / Advanced Minigame Checks** - each match (up to X) and each replay (up to X) in Mystery
  Bins and Creepy Collections is a check.
- **Endings** - choose 1, 2 or all 3 endings (Painting Message, Shrinking Soup, Ghost Machine). Your goal is to
  finish every ending you picked.
- **Riddle Rando / Entrance Rando** - riddle identities / room entrances are shuffled (done by the game client).
- **Door Locks** - eight doors need a key item.
- **Filler Items** - "You Found Me" pads the pool.

## Locations

Riddle solved (one per riddle room and minigame, per ending), clues (Riddle Shuffle: every_object), minigame matches
and replays.

## Item/location counts

Every item needs a location. For example one ending has 15 base locations, so item_shuffle (15) + riddle_lock (13)
+ door_locks (8) will not fit unless you add more checks (every_object, minigame checks) or more endings.
