"""In-game Archipelago hooks.

`install(rt)` monkey-patches the running game.  Rules:
  * a bug in AP code must NEVER break normal play -> every wrapper falls back to the original behaviour on error;
  * when AP is not enabled (no slot ever connected) every wrapper is a no-op;
  * installing is idempotent and a patch that cannot be applied (class/method missing) is just logged.

Hooks (see README of the AP port for the feature list):
    HelpPlayer.mStartHelp          -> AP menu
    Game.mAddToken                 -> item shuffle (+ riddle solved check)
    ScreenRiddle.mRiddleButtonClicked / mPlayEndAnim -> per-object clue checks
    ScreenMM.mHandleMMObject / ScreenCC.mHandleCCObject -> minigame match checks
    ScreenMM.mPlayDone / ScreenCC.mHandleWINROUNDDone -> advanced (replay) checks
    ScreenNav / ScreenDoor.mButtonActivated -> door keys, riddle unlocks, entrance rando
    version_picker.pick_version, Game.mInitGameObjects, Game.mNextVersion -> ending selection
    Game.mPlayFinale               -> ending completed / goal
    movie.setPlayer                -> session().on_player
    movie.getGameData / changeRiddleCast -> riddle rando (swapped riddle data + the matching room cast)
"""
import functools
import traceback

from .session import session, log

_INSTALLED = False
_PATCHED = set()


def _guard(label):
    """Run `fn` and swallow (but log) any exception; returns (ok, value)."""
    def run(fn, *a, **k):
        try:
            return True, fn(*a, **k)
        except Exception:                                  # noqa: BLE001
            log('hook error in %s:\n%s' % (label, traceback.format_exc()))
            return False, None
    return run


def _patch(owner, name, make_wrapper, label=None):
    """Replace owner.<name> with make_wrapper(original).  Skips (and logs) when it does not exist or is patched."""
    label = label or '%s.%s' % (getattr(owner, '__name__', owner), name)
    key = (id(owner), name)
    if key in _PATCHED:
        return False
    orig = getattr(owner, name, None)
    if orig is None:
        log('cannot hook %s: not found' % label)
        return False
    wrapped = make_wrapper(orig)
    try:
        functools.update_wrapper(wrapped, orig)
    except Exception:                                      # noqa: BLE001
        pass
    setattr(owner, name, wrapped)
    _PATCHED.add(key)
    return True


# ---- helpers -------------------------------------------------------------------------------------------------
def _st():
    st = session().state
    return st if st.enabled else None


def _ver():
    return session().current_version()


def _movie():
    from .. import movie
    return movie


def _report(ids):
    if ids:
        session().report(ids)


def _same(a, b):
    return str(a).lower() == str(b).lower()


def _lookup_ci(table, key):
    for k, v in table.items():
        if _same(k, key):
            return v
    return None


def _riddle_room(ending, code):
    from . import data
    for c in data.RIDDLE_ROOMS_BY_ENDING.get(ending, ()):
        if _same(c, code):
            return c
    return None


# what the running game was actually built with: {ending: {room: [source ending, source room]}} (riddle rando)
_APPLIED = {}


def _bundle(ending, code):
    """(ending, room) whose riddle data room `code` of `ending` is showing (itself unless riddle rando swapped it)."""
    from . import riddle_rando
    return riddle_rando.lookup(_APPLIED, ending, code)


# ---- hook factories ------------------------------------------------------------------------------------------
def _open_menu(in_game):
    """Run the modal AP menu and leave the game's input state exactly as the original help player does when it ends
    (the menu's own event loop swallows the mouse-up of the click that opened it, so the game must be re-armed)."""
    from . import menu
    from .. import runtime
    rt = runtime.rt
    M = _movie()
    sess = session()
    sd = M.gScreenDaddy
    if in_game and sd:
        M.waitCursor()
        sd.mDisable()                                      # same as HelpPlayer.mStartHelp
    res = None
    try:
        sess.modal = True
        res = menu.open(rt)
    finally:
        sess.modal = False
        try:
            rt.flush_input()
            rt.down_b, rt.down_chan = [], None             # the click that opened the menu never saw its mouse-up
            rt.hover_key, rt.hover_b, rt.hover_chan = None, [], None
            rt.mouse = type(rt.mouse)(*rt._pg.mouse.get_pos())
            M.clearInterruptMode()
            if in_game and sd:
                sd.mEnable()                               # same as HelpPlayer.mStop
            M.resetCursor()
        except Exception:                                  # noqa: BLE001
            log('could not re-arm input after the AP menu:\n%s' % traceback.format_exc())
    return res


def _help_hook(orig):
    def mStartHelp(self, *a, **k):
        def go():
            res = _open_menu(True)
            if isinstance(res, str) and res.startswith('wave:'):
                session().pending_wave = res.split(':', 1)[1]
        ok, _ = _guard('help')(go)
        if not ok:
            return orig(self, *a, **k)
    return mStartHelp


def _add_token_hook(orig):
    def mAddToken(self, t, *a, **k):
        def decide():
            st = _st()
            if st is None:
                return True
            ver, code = _ver(), str(t)
            if not ver:
                return True
            _report(st.riddle_solved(ver, code))
            return st.may_award_token(ver, code)
        ok, allow = _guard('mAddToken')(decide)
        if ok and not allow:
            session().toast('Token withheld until its item is received')
            return None
        return orig(self, t, *a, **k)
    return mAddToken


def _riddle_click_hook(orig):
    def mRiddleButtonClicked(self, theObject, *a, **k):
        res = orig(self, theObject, *a, **k)

        def report():
            st = _st()
            if st is None or not st.wants_every_object():
                return
            if _is_multi(theObject):
                return                                     # several pieces: reported once the LAST one is found
            from . import riddle_data
            ver, code = _ver(), str(self.pName)
            n = riddle_data.clue_index(*_bundle(ver, code), getattr(theObject, 'pName', ''))
            if n:
                _report(st.clue_found(ver, code, n))
        _guard('riddle click')(report)
        return res
    return mRiddleButtonClicked


def _is_multi(o):
    try:
        return str(o.mGetType()).upper() == 'RIDDLE_MULTI'
    except Exception:                                      # noqa: BLE001
        return False


def _report_multi_if_complete(screen, multi):
    """A clue made of several pieces (the three horns, ...) is one check: sent when its last piece has been found.
    Safe to call more than once (a location is only ever marked once)."""
    st = _st()
    if st is None or not st.wants_every_object() or not _is_multi(multi) or not multi.mAllObjectsFound():
        return
    from . import riddle_data
    ver, code = _ver(), str(screen.pName)
    n = riddle_data.clue_index(*_bundle(ver, code), getattr(multi, 'pName', ''))
    if n:
        _report(st.clue_found(ver, code, n))


def _riddle_anim_done_hook(orig):
    def mRiddleAnimationDone(self, theObject, *a, **k):
        res = orig(self, theObject, *a, **k)
        _guard('riddle multi done')(_report_multi_if_complete, self, theObject)
        return res
    return mRiddleAnimationDone


def _riddle_queue_done_hook(orig):
    """The click's play queue finished: the clicked object's animation (all its pieces) has played."""
    def mHandlePlayQueue(self, theObject, *a, **k):
        cur = self.pCurrRiddleObject
        res = orig(self, theObject, *a, **k)
        _guard('riddle multi queue')(_report_multi_if_complete, self, cur)
        return res
    return mHandlePlayQueue


def _riddle_end_hook(orig):
    def mPlayEndAnim(self, *a, **k):
        def report():
            st = _st()
            if st is None or not st.wants_every_object():
                return
            from . import data
            ver, code = _ver(), str(self.pName)
            se, sc = st.identity(ver, code)                # the riddle shown here (itself unless riddle rando)
            for i in range(1, data.CLUE_COUNT.get(se, {}).get(sc, 0) + 1):
                _report(st.clue_found(ver, code, i))
        _guard('riddle end')(report)
        return orig(self, *a, **k)
    return mPlayEndAnim


def _mm_match_hook(orig):
    def mHandleMMObject(self, theObject, *a, **k):
        def predict():
            cur = self.pCurrentButton
            return bool(cur) and not theObject.mGetSelected() and cur.pMatch == theObject.pMatch
        ok, matched = _guard('mm predict')(predict)
        res = orig(self, theObject, *a, **k)
        if ok and matched:
            _guard('mm match')(lambda: (_st() is not None) and _report(_st().minigame_match(_ver(), 'MT')))
        return res
    return mHandleMMObject


def _cc_match_hook(orig):
    def mHandleCCObject(self, theObject, *a, **k):
        def predict():
            return bool(theObject.mGetSelected()) and bool(theObject.pMatch)
        ok, matched = _guard('cc predict')(predict)
        res = orig(self, theObject, *a, **k)
        if ok and matched:
            _guard('cc match')(lambda: (_st() is not None) and _report(_st().minigame_match(_ver(), 'CC')))
        return res
    return mHandleCCObject


def _round_won_hook(code):
    """Advanced (replay) checks.  ScreenMM.mWon3 / ScreenCC.mWon3 only run when the win counter is EXACTLY 3, and the game
    never resets that counter between rounds (only when the screen loads), so every later round would be missed.
    Instead watch the round-complete handler: each round won once the counter is at 3 or more counts as one play."""
    def make(orig):
        def mRoundDone(self, theObject, *a, **k):
            def wins():
                wc = self.pWinCounter
                return int(wc.mGetWinCount()) if hasattr(wc, 'mGetWinCount') else 0
            ok_before, before = _guard('round before')(wins)
            res = orig(self, theObject, *a, **k)
            ok_after, after = _guard('round after')(wins)
            if ok_before and ok_after and after > before and after >= 3:
                _guard('round won')(lambda: (_st() is not None) and _report(_st().minigame_played(_ver(), code)))
            return res
        return mRoundDone
    return make


def _release_button(o):
    """A blocked (locked) click must leave the game exactly as if the player had let go outside the button.
    Pressing a nav button disables the whole game and the button, shows its pressed frame and sets the wait cursor;
    normally the screen change undoes all of that, so when we refuse the click we have to undo it ourselves."""
    M = _movie()
    try:
        if callable(getattr(o, 'mouseUpOutSide', None)):   # (LObject returns None, not AttributeError, for m[a-z]... names)
            o.pDownFlag = 1                                # mouseUpOutSide only acts on a held button
            o.mouseUpOutSide()                             # clears the pressed anim / activate flag + M.enableGame()
        else:
            M.enableGame()
        if hasattr(o, 'mEnable'):
            o.mEnable()                                    # mouseUp had removed the button's click behaviour
        M.resetCursor()
    except Exception:                                      # noqa: BLE001
        log('could not release the blocked button:\n%s' % traceback.format_exc())
        try:
            M.enableGame()
            M.resetCursor()
        except Exception:                                  # noqa: BLE001
            pass


def dest_name(o):
    return str(getattr(o, 'pDestination', ''))


def _nav_hook(is_door):
    def make(orig):
        def mButtonActivated(self, o, *a, **k):
            def check():
                """Returns (blocked, destination_override)."""
                st = _st()
                if st is None:
                    return False, None
                if o is self.pHelpButton or o is self.pBackButton:
                    return False, None
                dest = getattr(o, 'pDestination', None)
                in_nav = o in (self.pButtList or []) or (is_door and o is getattr(self, 'pTurnAroundButton', None))
                if not dest or not in_nav:
                    return False, None
                from . import data
                ver = _ver()
                door = _lookup_ci(data.DOOR_BY_DESTINATION, str(dest))
                if door and st.options.door_locks and not st.has_door_key(door):
                    session().show_locked('The %s is locked' % door, 'Find the %s' % data.door_key_name(door))
                    return True, None
                # the unlock item belongs to the riddle spot you CLICKED (like door keys), not to where entrance rando
                # sends you or whatever riddle riddle rando put there
                new = st.redirect(ver, str(dest)) if ver else str(dest)
                room = _riddle_room(ver, str(dest)) if ver else None
                if room and not st.riddle_unlocked(ver, room):
                    session().show_locked('This riddle is locked', 'Find "%s"' % st.unlock_item_for(ver, room))
                    return True, None
                return False, (new if new and not _same(new, dest) else None)
            ok, res = _guard('nav')(check)
            if ok and res:
                blocked, new = res
                if blocked:
                    _release_button(o)
                    return None
                if new:
                    shown = _guard('bundle')(_bundle, _ver(), new)[1]
                    extra = ''
                    if shown and (str(shown[0]).lower(), str(shown[1]).lower()) != (_ver(), new.lower()):
                        extra = ' (riddle rando: that room shows the %s riddle from wave %s)' % (shown[1], str(shown[0]).upper())
                    log('entrance rando: %s -> %s%s' % (dest_name(o), new, extra))
                    from ..lingo import Sym
                    old = o.pDestination
                    o.pDestination = Sym(new)
                    try:
                        return orig(self, o, *a, **k)
                    finally:
                        o.pDestination = old
            return orig(self, o, *a, **k)
        return mButtonActivated
    return make


def _pick_version_hook(orig):
    def pick_version(*a, **k):
        # pick_version only runs for a brand-new save: show the AP menu first so the slot's endings are known
        def first_open():
            import time
            _open_menu(False)
            sess, end = session(), time.monotonic() + 4
            while getattr(sess.client, 'state', '') == 'connecting' and time.monotonic() < end:
                sess.pump()                                # give a just-clicked Connect a moment to finish
                time.sleep(0.05)
        _guard('first open')(first_open)
        v = orig(*a, **k)
        ok, fixed = _guard('pick_version')(lambda: _fix_version(v))
        return fixed if ok else v
    return pick_version


def _fix_version(v):
    st = _st()
    if st is None:
        return v
    allowed = st.options.endings
    if len(allowed) == 1:
        return allowed[0]
    return v if v and str(v).lower() in allowed else allowed[0]


def _init_objects_hook(orig):
    def mInitGameObjects(self, noRestore=None, *a, **k):
        beaten = [False]

        def fix():
            st = _st()
            ver = str(self.pCurrentVersion).lower()
            if st is not None and ver not in st.options.endings:
                from . import data  # noqa: F401
                self.mSetVersion(st.options.endings[0])
                from .. import version_picker
                pd = _movie().getPlayerDir()
                if pd:
                    version_picker.write_version(pd, self.pName, self.pCurrentVersion)
            if st is not None and self.pIsSolved:
                # open world: a beaten wave is NOT deleted and the game does not jump to the next wave (vanilla does
                # both when it re-inits after the finale).  Keep the wave's save and restore it, finished.
                self.pIsSolved = 0
                beaten[0] = True
        _guard('init objects')(fix)
        res = orig(self, None if beaten[0] else noRestore, *a, **k)

        def after():
            if _st() is not None and self.pIsSolved:       # the restored save may carry the finale flag
                self.pIsSolved = 0
                self.mSave()
        _guard('init objects after')(after)
        return res
    return mInitGameObjects


def _next_version_hook(orig):
    def mNextVersion(self, *a, **k):
        res = orig(self, *a, **k)

        def fix():
            st = _st()
            if st is None:
                return
            allowed = st.options.endings
            cur = str(self.pCurrentVersion).lower()
            if cur in allowed:
                return
            # the next selected ending after the one the original picked, wrapping round (a single ending repeats)
            order = 'abc'
            start = order.index(cur) if cur in order else -1
            for step in range(1, 4):
                cand = order[(start + step) % 3]
                if cand in allowed:
                    self.mSetVersion(cand)             # also rebuilds the version pool so mNextVersion keeps rotating
                    self._remember_version()
                    return
        _guard('next version')(fix)
        return res
    return mNextVersion


def _finale_hook(orig):
    def mPlayFinale(self, *a, **k):
        ver = _ver()
        res = orig(self, *a, **k)
        if ver:
            _guard('finale')(lambda: session().goal_check(ver))
        return res
    return mPlayFinale


def _set_player_hook(orig):
    def setPlayer(name, *a, **k):
        res = orig(name, *a, **k)
        _guard('on_player')(lambda: session().on_player(name))
        return res
    return setPlayer


def _game_data_hook(orig):
    """Riddle rando: hand the game the data of a wave with its riddle rooms dealt out again."""
    cache = {}

    def getGameData(version, *a, **k):
        data = orig(version, *a, **k)

        def swap():
            from . import riddle_rando
            ver = str(version).lower()
            st = _st()
            assign = st.riddle_assignment() if st is not None and st.options.riddle_rando else {}
            _APPLIED.pop(ver, None)
            if not assign or ver not in assign:
                session().riddle_applied = False
                return data
            key = (ver, id(data), repr(sorted(assign[ver].items())))
            if key not in cache:
                cache[key] = riddle_rando.apply(data, ver, assign, lambda e: orig(e, *a, **k))
            _APPLIED[ver] = assign[ver]
            session().riddle_applied = True
            return cache[key]
        ok, res = _guard('getGameData')(swap)
        if not ok:
            _APPLIED.pop(str(version).lower(), None)
        return res if ok else data
    return getGameData


def _cast_hook(orig):
    """Riddle rando: a room showing another room's riddle needs that room's cast (castLib 3) loaded."""
    def changeRiddleCast(cast_id, *a, **k):
        def mapped():
            ver = _ver()
            if not ver or not _APPLIED.get(ver):
                return cast_id
            se, sc = _bundle(ver, str(cast_id))
            return sc if se is not None else cast_id
        ok, room = _guard('cast')(mapped)
        return orig(room if ok else cast_id, *a, **k)
    return changeRiddleCast


# ---- install -------------------------------------------------------------------------------------------------
def install(rt):
    """Call once after movie.INIT_MAIN() (and after the runtime exists)."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    try:
        from .state import APState
        APState.applied_lookup = staticmethod(_bundle)
        rt.ap_tick = session().pump
        rt.ap_draw = session().draw_overlay
        from .. import movie, version_picker
        from ..game import Game
        from ..screens import ScreenNav, ScreenDoor
        from ..screens2 import HelpPlayer
        from ..riddle_screens import ScreenRiddle
        from ..room_screens3 import ScreenMM, ScreenCC
        from ..ui import ScreenSignin  # noqa: F401  (imported so a broken ui module is noticed here)
    except Exception:                                      # noqa: BLE001
        log('could not import the game modules for hooks:\n%s' % traceback.format_exc())
        return
    _guard('patch')(_patch, HelpPlayer, 'mStartHelp', _help_hook)
    _guard('patch')(_patch, Game, 'mAddToken', _add_token_hook)
    _guard('patch')(_patch, Game, 'mInitGameObjects', _init_objects_hook)
    _guard('patch')(_patch, Game, 'mNextVersion', _next_version_hook)
    _guard('patch')(_patch, Game, 'mPlayFinale', _finale_hook)
    _guard('patch')(_patch, ScreenRiddle, 'mRiddleButtonClicked', _riddle_click_hook)
    _guard('patch')(_patch, ScreenRiddle, 'mPlayEndAnim', _riddle_end_hook)
    _guard('patch')(_patch, ScreenRiddle, 'mRiddleAnimationDone', _riddle_anim_done_hook)
    _guard('patch')(_patch, ScreenRiddle, 'mHandlePlayQueue', _riddle_queue_done_hook)
    _guard('patch')(_patch, ScreenMM, 'mHandleMMObject', _mm_match_hook)
    _guard('patch')(_patch, ScreenCC, 'mHandleCCObject', _cc_match_hook)
    _guard('patch')(_patch, ScreenMM, 'mPlayDone', _round_won_hook('MT'))
    _guard('patch')(_patch, ScreenCC, 'mHandleWINROUNDDone', _round_won_hook('CC'))
    _guard('patch')(_patch, ScreenNav, 'mButtonActivated', _nav_hook(False))
    _guard('patch')(_patch, ScreenDoor, 'mButtonActivated', _nav_hook(True))
    _guard('patch')(_patch, version_picker, 'pick_version', _pick_version_hook)
    _guard('patch')(_patch, movie, 'setPlayer', _set_player_hook)
    _guard('patch')(_patch, movie, 'getGameData', _game_data_hook)
    _guard('patch')(_patch, movie, 'changeRiddleCast', _cast_hook)
    _guard('patch')(_patch, movie, 'changeGameCast', _cast_hook)
    log('hooks installed (%d patches)' % len(_PATCHED))
