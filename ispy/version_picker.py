"""'Choose an Ending' screen, shown right after the sign-in rocket for a NEW game.

Picking an ending picks the whole game version (a / b / c): the version decides the game data, the room
variants (MESSAGE_A / KITCHEN_B / MACHINE_C ...) and the finale.

    left   Secret Room (Skeleton's Study)   -> version a
    middle Shrinking Soup (Kitchen)         -> version b
    right  Ghost Machine (Inventor's Shop)  -> version c

The artwork is loose PNGs in  <ispy_port>/Version Picker/Done/  (VP_Back, <XX>_Image, <XX>_Button_R,
<XX>_Button_D).  The screen runs its own little event loop, so it needs nothing from the sprite channels /
member tables.  The chosen version is remembered per player in '<save name>.VER' next to the player's save
file, so a returning player gets the game data of the version they picked.
"""
import os
from collections import deque

ASSET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Version Picker')
FOLDER_NAME = 'Version Picker'


def _app_data_root():
    """Same per-user folder the launcher uses (launcher.config.default_root); ISPY_PORT_HOME overrides it."""
    env = os.environ.get('ISPY_PORT_HOME')
    if env:
        return env
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
    else:
        base = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(base, 'ISpySpookyMansionArchipelago')


def asset_dirs():
    """Folders searched for the artwork, in order: the app-data folder (e.g. %LOCALAPPDATA%\\ISpySpookyMansionArchipelago\\
    Version Picker), then the folder next to the code (the repo's ispy_port\\Version Picker)."""
    return [os.path.join(_app_data_root(), FOLDER_NAME), ASSET_DIR]


def find_asset_dir():
    """First searched folder that contains VP_Back.png, else None."""
    for d in asset_dirs():
        if os.path.isfile(os.path.join(d, 'VP_Back.png')):
            return d
    return None

# which button frame is which: Complete.png shows the _R frames at rest, so _R = normal, _D = hover.
# (swap these two letters if the hover/normal look is the wrong way round)
NORMAL_FRAME = 'R'
HOVER_FRAME = 'D'

# (version, picture prefix, picture top-left, button top-left) -- positions taken from Complete.png
ITEMS = (
    ('a', 'SR', (133, 221), (142, 293)),
    ('b', 'SS', (275, 201), (272, 293)),
    ('c', 'GM', (397, 200), (404, 294)),
)

# a pixel counts as the picture's white backdrop when every channel is at least this bright
_WHITE = 252
# anti-aliased fringe next to the backdrop that is still this light is removed too (no white halo)
_FRINGE = 222
_FRINGE_PASSES = 2
# enclosed pockets of backdrop white (letter counters, gaps between the ghost's legs) up to this many pixels are
# removed too; bigger enclosed white areas are real artwork and stay
_MAX_HOLE = 80


def _matte(pg, surf):
    """Make the white backdrop transparent: only white connected to the image border (so white INSIDE the
    picture stays), plus a thin light fringe along it."""
    w, h = surf.get_size()
    px = [[tuple(surf.get_at((x, y)))[:3] for x in range(w)] for y in range(h)]
    gone = [[False] * w for _ in range(h)]
    q = deque()

    def white(x, y):
        return min(px[y][x]) >= _WHITE

    for x in range(w):
        for y in (0, h - 1):
            if white(x, y) and not gone[y][x]:
                gone[y][x] = True
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if white(x, y) and not gone[y][x]:
                gone[y][x] = True
                q.append((x, y))
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not gone[ny][nx] and white(nx, ny):
                gone[ny][nx] = True
                q.append((nx, ny))
    # small enclosed pockets of backdrop white
    seen = [[False] * w for _ in range(h)]
    for sy in range(h):
        for sx in range(w):
            if seen[sy][sx] or gone[sy][sx] or not white(sx, sy):
                continue
            comp = [(sx, sy)]
            seen[sy][sx] = True
            q.append((sx, sy))
            while q:
                x, y = q.popleft()
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and not gone[ny][nx] and white(nx, ny):
                        seen[ny][nx] = True
                        comp.append((nx, ny))
                        q.append((nx, ny))
            if len(comp) <= _MAX_HOLE:
                for x, y in comp:
                    gone[y][x] = True
    for _ in range(_FRINGE_PASSES):
        add = []
        for y in range(h):
            for x in range(w):
                if gone[y][x] or min(px[y][x]) < _FRINGE:
                    continue
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and gone[ny][nx]:
                        add.append((x, y))
                        break
        for x, y in add:
            gone[y][x] = True
    out = surf.convert_alpha()
    for y in range(h):
        for x in range(w):
            if gone[y][x]:
                out.set_at((x, y), (0, 0, 0, 0))
    return out


class Assets:
    def __init__(self, pg, folder=None):
        folder = folder or find_asset_dir()
        if folder is None:
            raise OSError('no Version Picker folder with VP_Back.png in: ' + '; '.join(asset_dirs()))

        def load(name):
            return pg.image.load(os.path.join(folder, name + '.png')).convert_alpha()

        self.back = load('VP_Back')
        self.items = []
        for ver, pre, pic_pos, btn_pos in ITEMS:
            pic = _matte(pg, load(pre + '_Image'))
            btn_n = load(pre + '_Button_' + NORMAL_FRAME)
            btn_h = load(pre + '_Button_' + HOVER_FRAME)
            pic_rect = pg.Rect(pic_pos, pic.get_size())
            btn_rect = pg.Rect(btn_pos, btn_n.get_size())
            self.items.append({'ver': ver, 'pic': pic, 'pic_pos': pic_pos, 'btn_n': btn_n, 'btn_h': btn_h,
                               'btn_pos': btn_pos, 'hit': pic_rect.union(btn_rect)})

    def hit(self, pos):
        for i, it in enumerate(self.items):
            if it['hit'].collidepoint(pos):
                return i
        return None

    def draw(self, screen, hover=None):
        screen.blit(self.back, (0, 0))
        for i, it in enumerate(self.items):
            screen.blit(it['pic'], it['pic_pos'])
            screen.blit(it['btn_h'] if i == hover else it['btn_n'], it['btn_pos'])


def pick_version(rt):
    """Show the screen on the runtime's stage and block until an ending is chosen. Returns 'a', 'b' or 'c', or None
    when the artwork isn't there (it is not part of the repo; see .gitignore) -- the caller then keeps the default.
    Click a picture or its button (or press A / B / C).  F11 / Alt+Enter still toggle fullscreen."""
    pg = rt._pg
    try:
        assets = Assets(pg)
    except (OSError, pg.error) as e:
        print('[version_picker] artwork not found, skipping the ending picker:', e)
        return None
    clock = pg.time.Clock()
    hover = None
    pressed = None
    cursor = None
    keys = {pg.K_a: 0, pg.K_b: 1, pg.K_c: 2}
    while True:
        for ev in pg.event.get():
            if ev.type == pg.QUIT:
                raise SystemExit(0)
            if rt._window_hotkey(ev):
                continue
            if ev.type == pg.MOUSEMOTION:
                hover = assets.hit(ev.pos)
            elif ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
                hover = pressed = assets.hit(ev.pos)
            elif ev.type == pg.MOUSEBUTTONUP and ev.button == 1:
                if pressed is not None and assets.hit(ev.pos) == pressed:
                    rt.set_cursor('arrow')
                    return assets.items[pressed]['ver']
                pressed = None
            elif ev.type == pg.KEYDOWN and ev.key in keys:
                rt.set_cursor('arrow')
                return assets.items[keys[ev.key]]['ver']
        want = 'hand' if hover is not None else 'arrow'
        if want != cursor:
            cursor = want
            rt.set_cursor(want)
        assets.draw(rt.screen, hover)
        pg.display.flip()
        clock.tick(60)


# ---- remembering the choice per player --------------------------------------------------------------
def _base(player_dir, save_name):
    name = str(save_name)
    return os.path.join(player_dir or '', name[:-4] if name.lower().endswith('.lst') else name)


def save_exists(player_dir, save_name):
    """True when this player already has a saved game (same file name SaveLoad.mSetCurFile builds)."""
    return os.path.exists(_base(player_dir, save_name) + '.LST')


def read_version(player_dir, save_name):
    try:
        with open(_base(player_dir, save_name) + '.VER') as f:
            v = f.read().strip().lower()
        return v if v in ('a', 'b', 'c') else None
    except OSError:
        return None


def write_version(player_dir, save_name, version):
    try:
        os.makedirs(player_dir or '.', exist_ok=True)
        with open(_base(player_dir, save_name) + '.VER', 'w') as f:
            f.write(str(version).lower())
    except OSError as e:
        print('[version_picker] could not remember the version:', e)
