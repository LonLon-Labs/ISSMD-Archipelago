"""Core runtime: object model, registry, update loop, sprite channels, assets, input.

The original is a Director movie where *everything* is a parent-script object driven by:
  * the global gUpdateList  (call(#mUpdate, gUpdateList) every frame/idle)
  * sprite channels with scriptInstanceList behaviors (mouseDown/mouseUp/mouseEnter/...)
This module reproduces exactly those two mechanisms on top of pygame so the translated parent
scripts can stay structurally identical to the Lingo.
"""
import json
import os
import time

from .lingo import decode, Point, set_properties

# ----------------------------------------------------------------------------------------------
# object model
# ----------------------------------------------------------------------------------------------

REGISTRY = {}          # script name -> python class
SCRIPT_IDS = {}        # int id (castLib<<16|member) -> script name


def lingo_script(name):
    def deco(cls):
        REGISTRY[name.lower()] = cls
        cls.SCRIPT_NAME = name
        return cls
    return deco


class LObject:
    """Base for translated parent scripts. Supports Lingo's `ancestor` property chain."""
    ancestor = None

    def __getattr__(self, name):          # only called when normal lookup fails
        if name.startswith('__'):
            raise AttributeError(name)
        anc = self.__dict__.get('ancestor')
        if anc is not None and not isinstance(anc, (int, float)) and anc:
            return getattr(anc, name)
        # Lingo: calling a handler that doesn't exist is an error; reading an unset property is VOID
        import re
        if re.match(r'^m[A-Z]', name):
            raise AttributeError(name)
        return None

    def __setattr__(self, name, value):
        d = self.__dict__
        if name not in d and name != 'ancestor':
            anc = d.get('ancestor')
            if isinstance(anc, LObject) and (name in anc.__dict__ or hasattr(type(anc), name)):
                setattr(anc, name, value)
                return
        object.__setattr__(self, name, value)

    def __bool__(self):                    # objects are truthy like Lingo instances
        return True


def get_object(data, alloc):
    """getObject(theObjectData, theSpriteAlloc): non-propList values pass through untouched."""
    if not isinstance(data, dict):
        return data
    cls = resolve_type(data.get('pType'))
    obj = cls()
    obj.mInit(data, alloc)
    # `ancestor` is itself an object in Lingo.  A few classes (GAME, _GameDraft) convert it
    # inside their own mInit; the rest store the raw propList.  Convert it here so that any
    # code that walks `obj.ancestor` (e.g. Game._riddles) always sees a real object.
    anc = obj.__dict__.get('ancestor')
    if isinstance(anc, dict):
        object.__setattr__(obj, 'ancestor', get_object(anc, alloc))
    return obj


def get_object_list(items, alloc, depth=0):
    new = list(items)
    shared = None
    if depth:
        from .lingo import pop_list
        shared = pop_list(alloc, depth)
    for i, d in enumerate(items):
        new[i] = get_object(d, list(shared) if depth else alloc)
    return new


def resolve_type(ptype):
    name = SCRIPT_IDS.get(ptype, ptype) if isinstance(ptype, int) else ptype
    cls = REGISTRY.get(str(name).lower())
    if cls is None:
        from .stubs import MissingScript
        return lambda n=name: MissingScript(n)
    return cls


def destroy_object(obj, parent=None):
    if hasattr(obj, 'mDestroy'):
        try:
            obj.mDestroy()
        except Exception:
            pass


# ----------------------------------------------------------------------------------------------
# sprites / stage
# ----------------------------------------------------------------------------------------------

class Sprite:
    __slots__ = ('member', '_loc', 'ink', 'blend', 'behaviors', 'visible', 'stretch_rect',
                 '_cursor', 'mask_member')

    # sprite(n).cursor = [25, 26] / [27, 28] / [29, 30] / [31, 32] / [33, 34] / 200 / 0
    CURSOR_KINDS = {(25, 26): 'arrow', (27, 28): 'hand', (29, 30): 'grab', (31, 32): 'wait',
                    (33, 34): 'lips'}

    # Data like `#pLoc: 0` (the arrow/Go buttons) assigns an integer to `sprite.loc`. Director ignores
    # that and keeps the sprite where it already was (blankSprite parks it at point(320,240)); the
    # bitmaps' odd registration points (e.g. (-141, 77)) are built around that default position.
    @property
    def loc(self):
        return self._loc

    @loc.setter
    def loc(self, v):
        if isinstance(v, (tuple, list)) and len(v) == 2:
            self._loc = v

    @property
    def cursor(self):
        return self._cursor

    @cursor.setter
    def cursor(self, v):
        if isinstance(v, (list, tuple)):
            self._cursor = self.CURSOR_KINDS.get(tuple(v))
        elif v == 200:
            self._cursor = 'hidden'          # cursor 200 is Director's blank cursor
        else:
            self._cursor = None

    def __init__(self):
        self.reset()

    def reset(self):
        self.member = 0
        self.loc = Point(320, 240)
        self.ink = 0
        self.blend = 100
        self.behaviors = []
        self.visible = True
        self.stretch_rect = None
        self._cursor = None
        self.mask_member = 0         # port-only: the lens member a Mask-ink (9) sprite is clipped to


class Runtime:
    STAGE_W, STAGE_H = 640, 480

    def __init__(self, project_root, exports_root, game_root=None):
        self.project_root = project_root
        self.exports_root = exports_root
        self.game_root = game_root
        self.update_list = []
        self.sprites = {c: Sprite() for c in range(1, 161)}
        self.t0 = time.monotonic()
        self.last_click = 0
        self.mouse = Point(0, 0)
        self.current_room = None        # which Exports/<ROOM> folder castLib 3 currently maps to
        self.screen_daddy = None
        self.cur_screen = None
        self.global_save = None
        self.player = ''
        self._img_cache = {}
        self._folder_index = {}
        self._pg = None
        self._fonts = {}
        self.fields = {}
        self.key = ''
        self.key_code = 0
        self.control_down = self.shift_down = self.option_down = False
        self.down_b = []
        self.down_chan = None
        self.hover_key = None
        self.hover_chan = None
        self._ink_cache = {}
        self.hover_b = []
        self._sprite_cursor = None
        self._lens_cache = {}
        from .media import SoundSystem
        self.sound = SoundSystem(self)
        self.members_main = {}
        self.handlers = {}

    # -- data ------------------------------------------------------------------------------
    def load_data(self, data_dir):
        global SCRIPT_IDS
        SCRIPT_IDS.update({int(k): v for k, v in json.load(open(os.path.join(data_dir, 'script_ids.json'))).items()})
        self.handlers = decode(json.load(open(os.path.join(data_dir, 'handlers.json'))))
        p = os.path.join(data_dir, 'members_main.json')
        if os.path.exists(p):
            self.members_main = {int(k): v for k, v in json.load(open(p)).items()}

    def get_data(self, handler, *a):
        v = self.handlers[handler]
        return v

    # -- time ------------------------------------------------------------------------------
    def milliseconds(self):
        return int((time.monotonic() - self.t0) * 1000)

    # -- update list (gUpdateList) ---------------------------------------------------------
    def add_update(self, obj):
        if obj not in self.update_list:
            self.update_list.append(obj)

    def remove_update(self, obj):
        if obj in self.update_list:
            self.update_list.remove(obj)

    def clear_update(self):
        self.update_list = []

    def tick(self):
        for o in list(self.update_list):          # call(#mUpdate, gUpdateList)
            if o in self.update_list:
                o.mUpdate()

    # -- members / assets ------------------------------------------------------------------
    def _old_member_path(self, num, exts=('png',)):
        """Map a Lingo member number to a ripped file.
        castLib = num >> 16  (0/1 = ISPYMAIN8 internal, 2 = BHP code, 3 = swapped room cast)."""
        cast, idx = (num >> 16) or 1, num & 0xFFFF
        if cast == 1:
            folder = os.path.join(self.exports_root, 'ISPYMAIN8')
        elif cast == 3 and self.current_room:
            folder = os.path.join(self.exports_root, self.current_room.upper())
        else:
            return None
        for e in exts:
            p = os.path.join(folder, '%d.%s' % (idx, e))
            if os.path.exists(p):
                return p
        return None

    def _old_image(self, num):
        if num in self._img_cache:
            return self._img_cache[num]
        img = None
        p = self.member_path(num, ('png',))
        if p and self._pg:
            img = self._pg.image.load(p).convert_alpha()
        self._img_cache[num] = img
        return img

    def _old_reg_point(self, num):
        cast, idx = (num >> 16) or 1, num & 0xFFFF
        m = self.members_main.get(idx) if cast == 1 else None
        if m:
            return tuple(m['reg'])
        img = self.image(num)
        return (img.get_width() // 2, img.get_height() // 2) if img else (0, 0)

    # Ripped files are named '<n>.<ext>' or '<n>_<name>.<ext>'; each folder also has Members.csv
    # with registration points (which matter: e.g. SI_UA_N has reg (-141, 77)).
    def _folder_for(self, num):
        cast = (num >> 16) or 1
        if cast == 1:
            return os.path.join(self.exports_root, 'ISPYMAIN8')
        if cast == 3 and self.current_room:
            return os.path.join(self.exports_root, self.current_room.upper())
        return None

    def _index(self, folder):
        idx = self._folder_index.setdefault(folder, None)
        if idx is not None:
            return idx
        import csv
        import re
        idx = {'files': {}, 'reg': {}, 'type': {}, 'name': {}}
        if os.path.isdir(folder):
            for fn in os.listdir(folder):
                m = re.match(r'^(\d+)(?:_.*)?\.(\w+)$', fn)
                if m:
                    idx['files'].setdefault(int(m.group(1)), {})[m.group(2).lower()] = os.path.join(folder, fn)
            mp = os.path.join(folder, 'Members.csv')
            if os.path.exists(mp):
                with open(mp, newline='', encoding='utf-8', errors='replace') as f:
                    for row in csv.DictReader(f):
                        try:
                            n = int(row['Number'])
                        except (KeyError, ValueError):
                            continue
                        r = re.findall(r'-?\d+', row.get('Registration Point') or '')
                        if len(r) >= 2:
                            idx['reg'][n] = (int(r[0]), int(r[1]))
                        idx['type'][n] = row.get('Type')
                        idx['name'][n] = row.get('Name') or ''
        self._folder_index[folder] = idx
        return idx

    def member_path(self, num, exts=('png',)):
        folder = self._folder_for(num)
        if not folder:
            return None
        files = self._index(folder)['files'].get(num & 0xFFFF, {})
        for e in exts:
            if e in files:
                return files[e]
        return None

    def member_path_by_name(self, name, exts=('png',)):
        """member("NAME") -> file, searching the room cast (castLib 3) then the main cast."""
        want = str(name).lower()
        folders = []
        if self.current_room:
            folders.append(os.path.join(self.exports_root, self.current_room.upper()))
        folders.append(os.path.join(self.exports_root, 'ISPYMAIN8'))
        for folder in folders:
            idx = self._index(folder)
            for n, nm in idx['name'].items():
                if nm.lower() == want:
                    files = idx['files'].get(n, {})
                    for e in exts:
                        if e in files:
                            return files[e]
        return None

    def member_name(self, num):
        folder = self._folder_for(num)
        return self._index(folder)['name'].get(num & 0xFFFF, '') if folder else ''

    def image(self, num):
        key = (self.current_room if (num >> 16) == 3 else None, num)
        if key in self._img_cache:
            return self._img_cache[key]
        img = None
        p = self.member_path(num, ('png',))
        if p and self._pg:
            img = self._pg.image.load(p).convert_alpha()
        self._img_cache[key] = img
        return img

    def reg_point(self, num):
        folder = self._folder_for(num)
        if folder:
            r = self._index(folder)['reg'].get(num & 0xFFFF)
            if r is not None:
                return r
        img = self.image(num)
        return (img.get_width() // 2, img.get_height() // 2) if img else (0, 0)

    # -- sprite channel API (the "sprite(n).member = x" idiom) -----------------------------
    def sprite(self, chan):
        return self.sprites[chan]

    def blank_sprite(self, chan):
        if isinstance(chan, (list, tuple)):
            for c in chan:
                self.blank_sprite(c)
        elif chan:
            self.sprites[chan].reset()

    def blank_sprite_range(self, a, b):
        for c in range(a, b + 1):
            self.blank_sprite(c)

    def set_behavior(self, chan, obj):
        self.sprites[chan].behaviors = [obj]

    def remove_behavior(self, chan, obj=None):
        self.sprites[chan].behaviors = []

    def _set_app_identity(self, pygame):
        """Window/taskbar icon + Windows taskbar identity. Done BEFORE set_mode so the window never shows pygame's logo."""
        if os.name == 'nt':
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ISpySpookyMansionPort.Game')
            except Exception:
                pass
        try:
            from .icon_data import load_icon_surface      # icon.png (bundled), else read from spooky2.exe
            icon = load_icon_surface(pygame, self.exports_root, self.game_root, self.project_root)
            if icon is not None:
                pygame.display.set_icon(icon)
        except Exception:
            pass

    # -- pygame loop -----------------------------------------------------------------------
    def init_pygame(self, headless=False):
        if headless:
            os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
            os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
        import pygame
        self._pg = pygame
        # smooth (linear) scaling when the 640x480 stage is stretched to a bigger window / the screen
        os.environ.setdefault('SDL_RENDER_SCALE_QUALITY', 'linear')
        pygame.init()
        self._set_app_identity(pygame)
        flags = 0
        if not headless:
            # SCALED | RESIZABLE: the window can be resized / maximized (maximize button) and toggled to
            # fullscreen; the 640x480 stage is letterboxed to the window and pygame maps the mouse back to
            # stage coordinates, so no other code has to know about the scaling
            flags = getattr(pygame, 'SCALED', 0) | pygame.RESIZABLE
        try:
            self.screen = pygame.display.set_mode((self.STAGE_W, self.STAGE_H), flags)
        except Exception as e:
            print('resizable window unavailable (%s); using a fixed 640x480 window' % e)
            self.screen = pygame.display.set_mode((self.STAGE_W, self.STAGE_H))
        pygame.display.set_caption('I SPY Spooky Mansion Deluxe (Python Port)')
        try:
            from .icon_data import load_icon_surface      # the original icon, read from spooky2.exe
            icon = load_icon_surface(pygame, self.exports_root, self.game_root, self.project_root)
            if icon is not None:
                pygame.display.set_icon(icon)
        except Exception:
            pass
        self.clock = pygame.time.Clock()
        try:
            pygame.mixer.init()
        except Exception:
            pass

    def _old_hit_test(self, pos):
        pg = self._pg
        for chan in sorted(self.sprites, reverse=True):
            s = self.sprites[chan]
            if not s.behaviors or not s.member:
                continue
            img = self.image(s.member)
            if not img:
                continue
            rx, ry = self.reg_point(s.member)
            x, y = pos[0] - (s.loc[0] - rx), pos[1] - (s.loc[1] - ry)
            if 0 <= x < img.get_width() and 0 <= y < img.get_height():
                if s.ink in (8, 36) and img.get_at((int(x), int(y))).a == 0:
                    continue
                return chan, s
        return None, None

    def _old_draw(self):
        self.screen.fill((0, 0, 0))
        for chan in sorted(self.sprites):
            s = self.sprites[chan]
            if not s.member or not s.visible:
                continue
            img = self.ink_image(s.member, s.ink)
            if not img:
                continue
            rx, ry = self.reg_point(s.member)
            if s.blend != 100:
                img = img.copy()
                img.set_alpha(int(255 * s.blend / 100))
            self.screen.blit(img, (s.loc[0] - rx, s.loc[1] - ry))
        self._pg.display.flip()

    def _old_dispatch_mouse(self, kind, pos):
        chan, s = self.hit_test(pos)
        if s:
            for b in list(s.behaviors):
                fn = getattr(b, kind, None)
                if fn:
                    fn()

    def _old_run(self):
        pg = self._pg
        running = True
        while running:
            for ev in pg.event.get():
                if ev.type == pg.QUIT:
                    running = False
                elif ev.type == pg.MOUSEMOTION:
                    self.mouse = Point(*ev.pos)
                elif ev.type == pg.MOUSEBUTTONDOWN:
                    self.last_click = self.milliseconds()
                    self.dispatch_mouse('mouseDown', ev.pos)
                elif ev.type == pg.MOUSEBUTTONUP:
                    self.dispatch_mouse('mouseUp', ev.pos)
                elif ev.type == pg.KEYDOWN:
                    if self.cur_screen is not None and hasattr(self.cur_screen, 'mCheckKey'):
                        self.cur_screen.mCheckKey(ev.key)
            self.tick()
            self.draw()
            self.clock.tick(60)
        pg.quit()

    # ---- members: types, text fields ---------------------------------------------------------
    def member_type(self, num):
        folder = self._folder_for(num)
        return (self._index(folder)['type'].get(num & 0xFFFF) or '') if folder else ''

    def is_text(self, num):
        return self.member_type(num) in ('field', 'text')

    def field(self, num):
        key = (self.current_room if (num >> 16) == 3 else None, num)
        f = self.fields.get(key)
        if f is None:
            from .media import Field
            f = self.fields[key] = Field(num, self.member_type(num))
        return f

    # The game's own font (SCHLHUDSTAR, a Scholastic face) is embedded in the cast and not exported;
    # substitute a similar friendly handwriting-style system font.
    FONT_FALLBACKS = {'schlhudstar': ('comicsansms', 'segoeprint', 'inkfree', 'arial')}

    def get_font(self, name, size):
        key = (name, size)
        f = self._fonts.get(key)
        if f is None:
            pg = self._pg
            n = str(name).replace('*', '').strip().lower().replace(' ', '')
            path = None
            for cand in self.FONT_FALLBACKS.get(n, (n, 'comicsansms', 'arial')):
                path = pg.font.match_font(cand)
                if path:
                    break
            px = int(size * (1.15 if n == 'schlhudstar' else 1.0))
            f = self._fonts[key] = pg.font.Font(path, px)
        return f

    # ---- ink modes ---------------------------------------------------------------------------
    # The ripped PNGs of matte (8) / background-transparent (36) sprites keep their white background.
    #   36: every white pixel is transparent.
    #   8 : only the white pixels connected to the image border (outside the outline) are transparent.
    def ink_image(self, num, ink):
        img = self.image(num)
        if img is not None and ink not in (8, 36):
            # Many sprites get their ink from the Score (not Lingo), so the port sees ink 0 for what
            # Director drew as Matte.  A small bitmap whose corner is pure white is a matte sprite.
            ink = self._guess_ink(num, img, ink)
        if img is None or ink not in (8, 36):
            return img
        key = (self.current_room if (num >> 16) == 3 else None, num, ink)
        out = self._ink_cache.get(key)
        if out is None:
            out = self._ink_cache[key] = self._apply_ink(img, ink)
        return out

    def _guess_ink(self, num, img, ink):
        if ink not in (0, None):
            return ink
        w, h = img.get_size()
        if w >= 600 and h >= 440:
            return ink                      # full-screen backdrop
        if self.is_text(num):
            return ink
        c = img.get_at((0, 0))
        if (c.r, c.g, c.b, c.a) == (255, 255, 255, 255):
            return 8
        return ink

    def _apply_ink(self, img, ink):
        pg = self._pg
        surf = img.copy()
        w, h = surf.get_size()
        white = pg.mask.from_threshold(surf, (255, 255, 255, 255), (3, 3, 3, 255))
        if ink == 8:
            border = pg.mask.Mask((w, h))
            for x in range(w):
                border.set_at((x, 0), 1)
                border.set_at((x, h - 1), 1)
            for y in range(h):
                border.set_at((0, y), 1)
                border.set_at((w - 1, y), 1)
            outside = pg.mask.Mask((w, h))
            for comp in white.connected_components():
                if comp.overlap(border, (0, 0)):
                    outside.draw(comp, (0, 0))
            white = outside
        cut = white.to_surface(setcolor=(0, 0, 0, 0), unsetcolor=(255, 255, 255, 255))
        surf.blit(cut, (0, 0), special_flags=pg.BLEND_RGBA_MIN)
        return surf

    def will_roll_over(self, num, loc, mouse):
        img = self.image(num)
        if not img:
            return False
        rx, ry = self.reg_point(num)
        l, t = loc[0] - rx, loc[1] - ry
        return l <= mouse[0] < l + img.get_width() and t <= mouse[1] < t + img.get_height()

    def sprite_box(self, s):
        if s.ink == 9 and s.mask_member and s.member:
            mk = self.image(s.mask_member)
            if mk is not None:
                rx, ry = self.reg_point(s.mask_member)
                return (s.loc[0] - rx, s.loc[1] - ry, mk.get_width(), mk.get_height(), None)
        if s.stretch_rect and s.member:
            l, t, r, b = s.stretch_rect
            return (l, t, r - l, b - t, None)
        if not s.member:
            return None
        if self.is_text(s.member):
            f = self.field(s.member)
            return (s.loc[0], s.loc[1], f.width, f.pageHeight, None)
        img = self.ink_image(s.member, s.ink)
        if not img:
            return None
        rx, ry = self.reg_point(s.member)
        return (s.loc[0] - rx, s.loc[1] - ry, img.get_width(), img.get_height(), img)

    # ---- hit testing / drawing -------------------------------------------------------------------
    def hit_test(self, pos):
        for chan in sorted(self.sprites, reverse=True):
            s = self.sprites[chan]
            if not s.behaviors:
                continue
            b = self.sprite_box(s)
            if not b:
                continue
            x, y = pos[0] - b[0], pos[1] - b[1]
            if not (0 <= x < b[2] and 0 <= y < b[3]):
                continue
            img = b[4]
            # Pixel-accurate test for image sprites: skip a sprite whose pixel under the cursor is
            # transparent, so an overlapping higher-channel sprite no longer steals clicks in its
            # empty corners (the SS "YUM" etchings and the lizard tails both hit this).
            # Fields / stretched sprites / Mask-ink sprites have img=None and stay box-only.
            if img is not None:
                try:
                    if img.get_at((int(x), int(y))).a == 0:
                        continue
                except Exception:
                    pass
            return chan, s
        return None, None

    def draw_text(self, s):
        pg = self._pg
        f = self.field(s.member)
        font = self.get_font(f.font, f.fontSize)
        lh = f.lineSpace or font.get_linesize()
        clip = pg.Rect(int(s.loc[0]), int(s.loc[1]), int(f.width), int(f.pageHeight))
        old = self.screen.get_clip()
        self.screen.set_clip(clip)
        for i, line in enumerate(f.lines, 1):
            y = s.loc[1] - f.scrollTop + (i - 1) * lh
            if y + lh < clip.top or y > clip.bottom:
                continue
            col = f.lineColors.get(i) or f.foreColor or (60, 30, 30)
            surf = font.render(line, True, col)
            if f.alignment == 'center':
                x = s.loc[0] + (f.width - surf.get_width()) // 2
            elif f.alignment == 'right':
                x = s.loc[0] + f.width - surf.get_width()
            else:
                x = s.loc[0]
            self.screen.blit(surf, (x, y))
        self.screen.set_clip(old)

    def draw(self):
        self.screen.fill((0, 0, 0))
        for chan in sorted(self.sprites):
            s = self.sprites[chan]
            if not s.member or not s.visible:
                continue
            if s.ink == 9 and s.mask_member:
                self.draw_masked(s)
                continue
            if self.is_text(s.member):
                self.draw_text(s)
                continue
            img = self.ink_image(s.member, s.ink)
            if not img:
                continue
            rx, ry = self.reg_point(s.member)
            if s.blend != 100:
                img = img.copy()
                img.set_alpha(int(255 * s.blend / 100))
            self.screen.blit(img, (s.loc[0] - rx, s.loc[1] - ry))
        v = getattr(self, 'video', None)           # Bink video plays over the stage
        if v is not None and v.frame is not None:
            self.screen.blit(v.frame, v.pos)
        self._pg.display.flip()

    def _draw_noink(self):
        self.screen.fill((0, 0, 0))
        for chan in sorted(self.sprites):
            s = self.sprites[chan]
            if not s.member or not s.visible:
                continue
            if self.is_text(s.member):
                self.draw_text(s)
                continue
            img = self.ink_image(s.member, s.ink)
            if not img:
                continue
            rx, ry = self.reg_point(s.member)
            if s.blend != 100:
                img = img.copy()
                img.set_alpha(int(255 * s.blend / 100))
            self.screen.blit(img, (s.loc[0] - rx, s.loc[1] - ry))
        self._pg.display.flip()

    def set_cursor(self, name):
        pg = self._pg
        if not pg:
            return
        try:
            pg.mouse.set_visible(name != 'hidden')
            if name == 'wait':
                from .hourglass import make_hourglass     # the old hourglass, not the blue busy ring
                hg = make_hourglass(pg)
                if hg is not None:
                    pg.mouse.set_cursor(hg)
                    return
            pg.mouse.set_cursor({'wait': pg.SYSTEM_CURSOR_WAIT, 'hand': pg.SYSTEM_CURSOR_HAND,
                                 'lips': pg.SYSTEM_CURSOR_HAND,
                                 'grab': pg.SYSTEM_CURSOR_HAND}.get(name, pg.SYSTEM_CURSOR_ARROW))
        except Exception:
            pass

    # ---- input -----------------------------------------------------------------------------------
    # ---- extras the room screens need ------------------------------------------------------------
    def cursor_kind_at(self, pos):
        for chan in sorted(self.sprites, reverse=True):
            s = self.sprites[chan]
            if not s._cursor:
                continue
            b = self.sprite_box(s)
            if not b:
                continue
            x, y = pos[0] - b[0], pos[1] - b[1]
            if 0 <= x < b[2] and 0 <= y < b[3]:
                return s._cursor
        return None

    def set_reg_point(self, num, pt):
        """member(n).regPoint = pt  (the magnifier shifts the registration point of its backdrop)."""
        folder = self._folder_for(num)
        if folder:
            self._index(folder)['reg'][num & 0xFFFF] = (int(pt[0]), int(pt[1]))

    def set_cursor_pos(self, pt):
        """dosSetCursorPos(x, y): warp the pointer (stage coordinates)."""
        from .lingo import Point as _P
        self.mouse = _P(int(pt[0]), int(pt[1]))
        if self._pg:
            try:
                self._pg.mouse.set_pos((int(pt[0]), int(pt[1])))
            except Exception:
                pass

    def toggle_fullscreen(self):
        """F11 / Alt+Enter: fullscreen (fit to screen) <-> the window it came from (maximized stays maximized)."""
        try:
            self._pg.display.toggle_fullscreen()
        except Exception:
            return
        self._sprite_cursor = False          # make update_hover() re-apply the current cursor

    def _window_hotkey(self, ev):
        pg = self._pg
        if ev.type != pg.KEYDOWN:
            return False
        if ev.key == pg.K_F11 or (ev.key in (pg.K_RETURN, pg.K_KP_ENTER) and (ev.mod & pg.KMOD_ALT)):
            self.toggle_fullscreen()
            return True
        return False

    def pump(self):
        """Keep the window alive inside the Lingo `repeat while ...` / wait() busy loops. Clicks that arrive
        meanwhile are dropped (Director queues them and the Lingo then calls flushInputEvents())."""
        pg = self._pg
        if not pg:
            return
        for ev in pg.event.get():
            if ev.type == pg.QUIT:
                raise SystemExit(0)
            if ev.type == pg.MOUSEMOTION:
                self.mouse = Point(*ev.pos)
            self._window_hotkey(ev)

    def update_stage(self):
        if self._pg:
            self.draw()

    def wait_ticks(self, n):
        """wait(n): n sixtieths of a second."""
        end = time.monotonic() + n / 60.0
        while time.monotonic() < end:
            self.pump()
            self.update_stage()
            time.sleep(0.004)

    def wait_sound(self, chan):
        """repeat while soundBusy(chan) ... end repeat"""
        while self.sound.busy(chan):
            self.pump()
            self.update_stage()
            time.sleep(0.004)

    def flush_input(self):
        """flushInputEvents()"""
        if self._pg:
            self._pg.event.clear([self._pg.MOUSEBUTTONDOWN, self._pg.MOUSEBUTTONUP, self._pg.KEYDOWN])

    def _lens_mask(self, num):
        """The opaque part of a lens-mask bitmap (ink 9 'Mask'): the blob containing the centre pixel."""
        m = self._lens_cache.get(num)
        if m is None:
            pg = self._pg
            img = self.image(num)
            w, h = img.get_size()
            ctr = (w // 2, h // 2)
            if img.get_at(ctr).a == 255 and img.get_at((0, 0)).a == 0:
                full = pg.mask.from_surface(img)
            else:
                full = pg.mask.from_threshold(img, img.get_at(ctr), (8, 8, 8, 255))
            m = full
            for comp in full.connected_components():
                if comp.get_at(ctr):
                    m = comp
                    break
            self._lens_cache[num] = m
        return m

    def stamp_pixels(self, dst_num, src_num, dst_rect, ink=36):
        """member(dst).image.copyPixels(member(src).image, dst_rect, member(src).rect, [#ink: ink]) -- the
        magnifier stamps the 'state change' bitmap of a found riddle object into its backdrop image."""
        pg = self._pg
        dst = self.image(dst_num)
        src = self.ink_image(src_num, ink)
        if not pg or dst is None or src is None:
            return
        l, t, r, b = [int(round(v)) for v in dst_rect]
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            return
        if src.get_size() != (w, h):
            src = pg.transform.scale(src, (w, h))
        dst.blit(src, (l, t))

    def drop_image(self, num):
        """unloadMem(member): forget the cached bitmap so the next image() reloads the pristine file
        (undoes stamp_pixels, as unloading the member does in Director)."""
        key = (self.current_room if (num >> 16) == 3 else None, num)
        self._img_cache.pop(key, None)
        for k in [k for k in self._ink_cache if k[1] == num]:
            del self._ink_cache[k]
        self._lens_cache.pop(num, None)

    def draw_masked(self, s):
        """Mask ink (9): in the original the member in the next Score channel is the mask. The port draws
        the sprite's member through the lens bitmap named by sprite.mask_member."""
        pg = self._pg
        bg, mk = self.image(s.member), self.image(s.mask_member)
        if bg is None or mk is None:
            return
        mrx, mry = self.reg_point(s.mask_member)
        rx, ry = self.reg_point(s.member)
        lx, ly = s.loc[0] - mrx, s.loc[1] - mry
        bx, by = s.loc[0] - rx, s.loc[1] - ry
        out = pg.Surface(mk.get_size(), pg.SRCALPHA)
        out.fill((0, 0, 0, 0))
        out.blit(bg, (bx - lx, by - ly))
        cut = self._lens_mask(s.mask_member).to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
        out.blit(cut, (0, 0), special_flags=pg.BLEND_RGBA_MIN)
        self.screen.blit(out, (lx, ly))

    @staticmethod
    def _call(behaviors, name):
        for b in list(behaviors):
            fn = getattr(b, name, None)
            if fn:
                fn()

    def update_hover(self):
        chan, s = self.hit_test(self.mouse)
        key = (chan, tuple(id(b) for b in s.behaviors)) if s else None
        if key != self.hover_key:
            old, old_chan = self.hover_b, self.hover_chan
            self.hover_b = list(s.behaviors) if s else []
            self.hover_chan = chan if s else None
            self.hover_key = key
            if old_chan is not None:
                # Director never sends mouseLeave to a behavior that was removed (e.g. a button that
                # was just hidden); doing so re-showed the Go spider after it was blanked.
                still = self.sprites[old_chan].behaviors
                self._call([b for b in old if b in still], 'mouseLeave')
            self._call(self.hover_b, 'mouseEnter')
        # the `cursor` property of the sprite under the mouse beats the global cursor()
        kind = self.cursor_kind_at(self.mouse)
        if kind != self._sprite_cursor:
            from . import movie
            self._sprite_cursor = kind
            self.set_cursor(kind or movie.gCursor or 'arrow')

    def press(self, pos):
        from . import movie
        movie.interruptHandler()                 # mouseDownScript, then pass()
        chan, s = self.hit_test(pos)
        self.down_chan = chan
        self.down_b = list(s.behaviors) if s else []
        self._call(self.down_b, 'mouseDown')

    def release(self, pos):
        chan, s = self.hit_test(pos)
        b, self.down_b = self.down_b, []
        if self.down_chan is not None and s is not None and chan != self.down_chan \
                and self.sprites[self.down_chan].member in (0, 1) \
                and s.behaviors:
            # the pressed sprite swapped its behaviors during mouseDown (e.g. drag-and-drop hands the
            # mouse to the drag sprite): Director delivers mouseUp to what is under the mouse now
            self._call(list(s.behaviors), 'mouseUp')
            return
        self._call(b, 'mouseUp' if (s and chan == self.down_chan) else 'mouseUpOutSide')

    def key_down(self, ev):
        pg = self._pg
        code = {pg.K_BACKSPACE: 51, pg.K_DELETE: 117, pg.K_RETURN: 36, pg.K_KP_ENTER: 76,
                pg.K_SPACE: 49, pg.K_ESCAPE: 53}.get(ev.key, 0)
        ch = ev.unicode or ''
        if ev.key == pg.K_RETURN:
            ch = '\r'
        elif ev.key == pg.K_KP_ENTER:
            ch = chr(3)
        self.key, self.key_code = ch, code
        mods = pg.key.get_mods()
        self.control_down = bool(mods & pg.KMOD_CTRL)
        self.shift_down = bool(mods & pg.KMOD_SHIFT)
        self.option_down = bool(mods & pg.KMOD_ALT)
        fn = getattr(self.cur_screen, 'mCheckKey', None) if self.cur_screen is not None else None
        if fn:
            fn(code)

    def run(self):
        pg = self._pg
        self.mouse = Point(*pg.mouse.get_pos())
        running = True
        while running:
            for ev in pg.event.get():
                if ev.type == pg.QUIT:
                    running = False
                elif ev.type == pg.MOUSEMOTION:
                    self.mouse = Point(*ev.pos)
                elif ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
                    self.mouse = Point(*ev.pos)
                    self.last_click = self.milliseconds()
                    self.press(ev.pos)
                elif ev.type == pg.MOUSEBUTTONUP and ev.button == 1:
                    self.mouse = Point(*ev.pos)
                    self.release(ev.pos)
                    self._save_due = True
                elif ev.type == pg.KEYDOWN:
                    if not self._window_hotkey(ev):
                        self.key_down(ev)
            self.update_hover()
            self.tick()
            self.draw()
            self.clock.tick(60)
            self._autosave()
        from . import movie
        movie.savegame_safe()
        pg.quit()

    # Autosave: after every click's consequences have played out (state settles a moment after the
    # click) and at least every 5 s. SaveLoad skips the write when nothing changed.
    def _autosave(self):
        now = self.milliseconds()
        last = getattr(self, '_last_save', 0)
        if (getattr(self, '_save_due', False) and now - last > 400) or now - last > 5000:
            self._save_due = False
            self._last_save = now
            from . import movie
            movie.savegame_safe()


rt = None


def init_runtime(*a, **k):
    global rt
    rt = Runtime(*a, **k)
    return rt
