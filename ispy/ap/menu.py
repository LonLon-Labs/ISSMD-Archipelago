"""The Archipelago menu (replaces the help button's help player).

A modal screen with its own little event loop (same approach as version_picker): the game is paused behind it.
Artwork lives in  AP Menu/  (AP_Back.png, <PM|SS|GM>_Button_<R|D>.png; Complete.png is only the layout reference).
The backdrop already has the ADDRESS / SLOT / PASSWORD labels and the CHANGE WAVE heading drawn on it, so this
module only draws the typed text, the Connect / Disconnect buttons and the status line on top.

open(rt) returns None, or 'wave:<a|b|c>' when the player clicked a wave button.
"""
import os

from .data import ENDING_NAME
from .session import session

NORMAL_FRAME, HOVER_FRAME = 'R', 'D'
MENU_SIZE = (408, 306)

# positions inside the 408x306 menu image (measured from Complete.png)
FIELDS = {'address': (115, 64, 266, 24), 'slot': (83, 86, 298, 24), 'password': (232, 109, 150, 24)}
WAVE_BUTTONS = (('a', 'PM', (25, 233)), ('b', 'SS', (155, 233)), ('c', 'GM', (287, 234)))
CONNECT_RECT = (92, 148, 100, 28)
DISCONNECT_RECT = (214, 148, 100, 28)
CLOSE_RECT = (372, 6, 28, 24)
STATUS_Y = 182
INK = (50, 30, 15)


def _find_dir():
    for d in session().asset_dirs():
        if os.path.isfile(os.path.join(d, 'AP_Back.png')):
            return d
    return None


class _Assets:
    def __init__(self, pg, folder):
        def load(n):
            return pg.image.load(os.path.join(folder, n + '.png')).convert_alpha()
        self.back = load('AP_Back')
        self.waves = []
        for ver, pre, pos in WAVE_BUTTONS:
            n, h = load(pre + '_Button_' + NORMAL_FRAME), load(pre + '_Button_' + HOVER_FRAME)
            self.waves.append((ver, n, h, pg.Rect(pos, n.get_size())))


def _clipboard():
    try:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        try:
            return r.clipboard_get()
        finally:
            r.destroy()
    except Exception:                                      # noqa: BLE001
        return ''


def open(rt):                                              # noqa: A001 - module API
    sess = session()
    pg = rt._pg
    folder = _find_dir()
    if folder is None:
        sess.toast('AP Menu artwork not found (AP Menu/AP_Back.png)')
        return None
    try:
        assets = _Assets(pg, folder)
    except (OSError, pg.error) as e:
        sess.toast('Could not load AP Menu artwork: %s' % e)
        return None
    st = sess.state
    values = {'address': st.address, 'slot': st.slot_name, 'password': st.password}
    focus = 'address' if not values['address'] else ('slot' if not values['slot'] else 'address')
    ox, oy = (rt.screen.get_width() - MENU_SIZE[0]) // 2, (rt.screen.get_height() - MENU_SIZE[1]) // 2
    snap = rt.screen.copy()
    dim = pg.Surface(rt.screen.get_size(), pg.SRCALPHA)
    dim.fill((0, 0, 0, 150))
    font = pg.font.Font(pg.font.match_font('comicsansms,arial') or None, 18)
    small = pg.font.Font(pg.font.match_font('comicsansms,arial') or None, 15)

    def rect(t):
        return pg.Rect(ox + t[0], oy + t[1], t[2], t[3])

    field_rects = {k: rect(v) for k, v in FIELDS.items()}
    connect_r, disc_r, close_r = rect(CONNECT_RECT), rect(DISCONNECT_RECT), rect(CLOSE_RECT)
    wave_rects = [(ver, n, h, pg.Rect(ox + r.x, oy + r.y, r.w, r.h)) for ver, n, h, r in assets.waves]
    order = ['address', 'slot', 'password']
    clock = pg.time.Clock()
    result = None
    cursor = None
    sess.modal = True
    rt.set_cursor('arrow')

    def do_connect():
        if values['address'].strip() and values['slot'].strip():
            sess.connect(values['address'], values['slot'], values['password'])
        else:
            sess.client.status = 'Enter an address and a slot name'

    try:
        while result is None:
            mouse = pg.mouse.get_pos()
            for ev in pg.event.get():
                if ev.type == pg.QUIT:
                    raise SystemExit(0)
                if rt._window_hotkey(ev):
                    continue
                if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
                    hit = next((k for k, r in field_rects.items() if r.collidepoint(ev.pos)), None)
                    if hit:
                        focus = hit
                    elif close_r.collidepoint(ev.pos):
                        result = ''
                    elif connect_r.collidepoint(ev.pos):
                        do_connect()
                    elif disc_r.collidepoint(ev.pos):
                        sess.disconnect(disable=True)
                    else:
                        for ver, _n, _h, r in wave_rects:
                            if r.collidepoint(ev.pos):
                                if st.enabled and not st.options.plays(ver):
                                    sess.client.status = '%s is not part of this multiworld' % ENDING_NAME[ver]
                                elif ver == sess.current_version():
                                    sess.client.status = 'Already on %s' % ENDING_NAME[ver]
                                else:
                                    result = 'wave:' + ver
                elif ev.type == pg.KEYDOWN:
                    if ev.key == pg.K_ESCAPE:
                        result = ''
                    elif ev.key == pg.K_TAB:
                        focus = order[(order.index(focus) + (-1 if ev.mod & pg.KMOD_SHIFT else 1)) % 3]
                    elif ev.key in (pg.K_RETURN, pg.K_KP_ENTER):
                        do_connect()
                    elif ev.key == pg.K_BACKSPACE:
                        values[focus] = values[focus][:-1]
                    elif ev.key == pg.K_v and ev.mod & pg.KMOD_CTRL:
                        values[focus] += _clipboard().strip().replace('\n', '')[:120]
                    elif ev.unicode and ev.unicode.isprintable() and not (ev.mod & pg.KMOD_CTRL):
                        values[focus] += ev.unicode
            sess.pump()
            over_btn = (connect_r.collidepoint(mouse) or disc_r.collidepoint(mouse) or close_r.collidepoint(mouse)
                        or any(r.collidepoint(mouse) for *_x, r in wave_rects))
            over_field = any(r.collidepoint(mouse) for r in field_rects.values())
            want = 'hand' if over_btn else ('arrow' if not over_field else 'arrow')
            if want != cursor:
                cursor = want
                rt.set_cursor(want)

            s = rt.screen
            s.blit(snap, (0, 0))
            s.blit(dim, (0, 0))
            s.blit(assets.back, (ox, oy))
            tick = (pg.time.get_ticks() // 450) % 2
            for k, r in field_rects.items():
                txt = values[k] if k != 'password' else '*' * len(values[k])
                img = font.render(txt, True, INK)
                area = pg.Rect(0, 0, r.w - 6, r.h)
                s.blit(img, (r.x + 3, r.y + 2), area=area if img.get_width() <= r.w - 6 else
                       pg.Rect(img.get_width() - (r.w - 6), 0, r.w - 6, r.h))
                if k == focus and tick:
                    cx = r.x + 3 + min(img.get_width(), r.w - 6)
                    pg.draw.line(s, INK, (cx + 1, r.y + 3), (cx + 1, r.y + r.h - 3), 2)
            for ver, n, h, r in wave_rects:
                on = r.collidepoint(mouse) or ver == sess.current_version()
                s.blit(h if on else n, r.topleft)
            for r, label in ((connect_r, 'Connect'), (disc_r, 'Disconnect')):
                hov = r.collidepoint(mouse)
                pg.draw.rect(s, (120, 70, 35) if hov else (92, 52, 26), r, border_radius=5)
                pg.draw.rect(s, (40, 22, 10), r, 2, border_radius=5)
                t = small.render(label, True, (245, 232, 200))
                s.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))
            xt = font.render('X', True, (150, 30, 20) if close_r.collidepoint(mouse) else INK)
            s.blit(xt, (close_r.centerx - xt.get_width() // 2, close_r.centery - xt.get_height() // 2))
            status = sess.client.status or ('Connected' if sess.client.connected else 'Not connected')
            if st.enabled and not sess.client.status:
                status = 'Archipelago on (offline)'
            stt = small.render(status[:58], True, INK)
            s.blit(stt, (ox + MENU_SIZE[0] // 2 - stt.get_width() // 2, oy + STATUS_Y))
            sess.draw_overlay(s)
            pg.display.flip()
            clock.tick(60)
    finally:
        sess.modal = False
        rt.set_cursor('arrow')
        rt.flush_input()
        st.address, st.slot_name, st.password = values['address'].strip(), values['slot'].strip(), values['password']
        sess.save()
    return result or None
