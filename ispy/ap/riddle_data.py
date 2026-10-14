"""Per-room riddle object / clue tables (pure Python, no pygame).

`riddle_clues.json` (next to this file, so it ships with the package) was generated from data/handlers.json:
getSpookyData_<A|B|C> -> pLevelScreenList -> (screen | screen.ancestor for the Magic Room / Attic) ->
pRiddleObjectList + pRiddleWordRectList.
    objects : every clickable riddle object name, in game order
    clues   : the riddle words (pRiddleWordRectList minus the two GL_ words) in game order; a clue's 1-based position
              is the `n` used by data.clue_location_name(ending, room, n).  Len == data.CLUE_COUNT[ending][room].
Regenerate with:  python -m ispy.ap.riddle_data data/handlers.json
"""
import json
import os
import sys

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'riddle_clues.json')
_CACHE = None


def _sym(x):
    return x.get('$sym', x) if isinstance(x, dict) else x


def generate(handlers_path):
    """Build the table from a handlers.json file."""
    with open(handlers_path, encoding='utf-8') as f:
        handlers = json.load(f)
    out = {}
    for ver in 'abc':
        out[ver] = {}
        for scr in handlers['getSpookyData_' + ver.upper()]['pLevelScreenList']:
            src = scr['ancestor'] if isinstance(scr.get('ancestor'), dict) else scr
            if 'pRiddleObjectList' not in src:
                continue
            words = [str(_sym(w['pName'])) for w in src.get('pRiddleWordRectList', [])]
            out[ver][str(_sym(scr['pName']))] = {
                'objects': [str(_sym(o['pName'])) for o in src['pRiddleObjectList']],
                'clues': [w for w in words if not w.upper().startswith('GL_')],
                'gl': [w for w in words if w.upper().startswith('GL_')],
            }
    return out


def tables():
    global _CACHE
    if _CACHE is None:
        with open(_PATH, encoding='utf-8') as f:
            _CACHE = json.load(f)
    return _CACHE


def room(ending, code):
    """The table entry for a room (room code compared case-insensitively), or None."""
    rooms = tables().get(str(ending).lower(), {})
    if code in rooms:
        return rooms[code]
    for k, v in rooms.items():
        if k.lower() == str(code).lower():
            return v
    return None


def clues(ending, code):
    r = room(ending, code)
    return list(r['clues']) if r else []


def clue_index(ending, code, object_name):
    """1-based clue number of a riddle object/word name within its room, or 0 when it isn't a clue."""
    name = str(object_name).lower()
    for i, c in enumerate(clues(ending, code), 1):
        if c.lower() == name:
            return i
    return 0


if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join('data', 'handlers.json')
    with open(_PATH, 'w', encoding='utf-8') as f:
        json.dump(generate(src), f, separators=(',', ':'))
    print('wrote', _PATH)
