"""Movie-script handlers (MAIN_MOVIE 23, General Handlers 24, Global 21), 1:1 with the Lingo.

Lingo `global gFoo` variables are module globals here. Handler names are unchanged so call sites
translate directly. Things Director did natively (cursor(), puppetSound, updateStage, ...) go through
the runtime in runtime.py / media.py.
"""
import os
import shutil

from . import runtime
from .lingo import Sym, get_range_list, pop_last, pop_last_range, pop_one, get_def, Point

# ---- globals ---------------------------------------------------------------------------------
gCursor = None
gInterruptableObject = 0
gScreenDaddy = 0
gCurScreen = 0
gPlayer = ''
gPlayerDir = ''
gSavedGameDir = ''
gSaveLoadObject = 0
gGlobalSaveLoadObject = 0
gAmbientSound = 0
gBlank = 1
gWordRectBlank = 6
gFlushSound = 4            # gMemberNumberList.tiny  (silent 'flush' sound in the main cast)
gEndFadeMember = 10        # gMemberNumberList.ENDFADE
gSoundObjectPool = []
gExSoundObjectPool = []
gSimpleButtPool = []
gWiggleObjectPool = []
gQuitDialogue = 0
gCreditDialogue = 0
gDragSprite = 0
gUserHasLamePC = 0
gPlayQueue = 0
gDissolveBlend = 0


def _rt():
    return runtime.rt


# ---- update list -----------------------------------------------------------------------------
def addUpdateList(o): _rt().add_update(o)
def removeUpdateList(o): _rt().remove_update(o)
def clearUpDateList(): _rt().clear_update()
def isUpdating(o): return o in _rt().update_list


# ---- cursor ----------------------------------------------------------------------------------
def _set_cursor(name):
    global gCursor
    if gCursor != name:
        gCursor = name
        rt = _rt()
        rt.set_cursor(rt._sprite_cursor or name)      # a sprite's own cursor wins while the mouse is over it


def waitCursor(): _set_cursor('wait')
def hidecursor(): _set_cursor('hidden')
def SetHandCursor(): _set_cursor('hand')
def setOpenhandCursor(): _set_cursor('hand')
def SetGrabCursor(): _set_cursor('grab')
def resetCursor(): _set_cursor('arrow')
def setLipsCursor(): _set_cursor('lips')


# ---- screens / navigation --------------------------------------------------------------------
def setCurScreen(s):
    global gCurScreen
    gCurScreen = s
    _rt().cur_screen = s


def getCurScreen(): return gCurScreen
def getCurGame(): return gScreenDaddy
def navigate(screen): gScreenDaddy.mNavigate(screen)
def navigateBack(): gScreenDaddy.mNavigateBack()
def getRegPoint(): return Point(320, 240)
def getOffScreenLoc(): return Point(-1000, -1000)
def getBlank(): return gBlank
def getWordRectBlank(): return gWordRectBlank
def getDragSprite(): return gDragSprite
def disableGame(): gScreenDaddy.mDisable()
def enableGame(): gScreenDaddy.mEnable()
def disableScreen(): gCurScreen.mDisable()
def enableScreen(): gCurScreen.mEnable()
def isPC(): return 1
def isMac(): return 0
def isLamePC(): return 0
def QuitKeyCheck(keycode, flag=0): return 0
def getVersion(): return 1
def getPV(pc, mac): return pc


def changeRiddleCast(cast_id):
    """ChangeCast(castID, 3): point castLib 3 at CASTS/<castID>.CXT. Returns 1 if it changed.
    In the port: castLib 3 == Exports/<castID>."""
    rt = _rt()
    room = str(cast_id).upper()
    if room == 'EXTERNAL':
        return 0
    if os.path.isdir(os.path.join(rt.exports_root, room)):
        if rt.current_room != room:
            rt.current_room = room
            return 1
    return 0


changeGameCast = changeRiddleCast


# ---- interrupt mode (mouseDownScript = "interruptHandler") -----------------------------------
def setInterruptMode(obj):
    global gInterruptableObject
    if obj is not None:
        gInterruptableObject = obj


def clearInterruptMode(stopFlag=None):
    global gInterruptableObject
    if gInterruptableObject and stopFlag:
        gInterruptableObject.mStop()
    gInterruptableObject = 0


def interruptHandler():
    """Runs on every mouseDown while an interruptable object is set (then `pass()` lets the click through)."""
    global gInterruptableObject
    if gInterruptableObject:
        o = gInterruptableObject
        gInterruptableObject = 0
        o.mStop()


# ---- sound object pools ----------------------------------------------------------------------
def _new(name, *a):
    from .core import new_script
    return new_script(name, *a)


def getSoundObject(channel, sound, parent):
    if isinstance(sound, runtime.LObject):
        return sound
    o = gSoundObjectPool.pop(0) if gSoundObjectPool else _new('INTERNALSOUND', 'extra')
    o.pChannel, o.pSound, o.pParent = channel, sound, parent
    return o


def getExSoundObject(channel, sound, parent):
    if isinstance(sound, runtime.LObject):
        sound.pSound = sound
        return sound
    o = gExSoundObjectPool.pop(0) if gExSoundObjectPool else _new('EXTERNALSOUND', 'extra', '')
    o.pChannel, o.pSound, o.pParent = channel, sound, parent
    return o


def recycleSoundObject(obj):
    if isinstance(obj, runtime.LObject):
        t = str(obj.mGetType()).lower()
        snd = obj.pSound
        if t == 'internalsound' and obj not in gSoundObjectPool:
            obj.mRecycle()
            gSoundObjectPool.append(obj)
        elif t == 'externalsound' and obj not in gExSoundObjectPool:
            obj.mRecycle()
            gExSoundObjectPool.append(obj)
        return snd
    return obj


def getSimpleButt(sprite, member, parent, ink=None):
    o = gSimpleButtPool.pop(0) if gSimpleButtPool else _new('BUTT_SIMPLE')
    o.pSprite, o.pMember, o.pParent, o.pInk = sprite, member, parent, get_def(ink, 0)
    return o


def recycleSimpleButt(obj):
    if isinstance(obj, runtime.LObject):
        obj.pSprite = obj.pMember = obj.pParent = obj.pInk = 0
        if obj not in gSimpleButtPool:
            gSimpleButtPool.append(obj)


# ---- wiggle object pool (MAIN_MOVIE getWiggleObject / recycleWiggleObject / getWiggleSound) -------
def getWiggleObject(parent=None):
    o = gWiggleObjectPool.pop(0) if gWiggleObjectPool else _new('ANIM_WIGGLE')
    o.pParent = parent
    return o


def recycleWiggleObject(obj):
    obj.pParent = None
    obj.pSprite = 0
    obj.pAnimMembers = []
    obj.pSoundChannel = 0
    obj.pInk = 0
    obj.pBackMember = 0
    obj.pBackSprite = 0
    if obj not in gWiggleObjectPool:
        gWiggleObjectPool.append(obj)


def getWiggleSound():
    if str(gScreenDaddy.mGetType()).upper() == 'GAME':
        return gScreenDaddy.mGetWiggleSound()


# ---- ambient sound (channel 3) ---------------------------------------------------------------
def FadeOutAmbientSound(speed=None): _rt().sound.stop(3)
def ReStartAmbientSound():
    if gAmbientSound:
        _rt().sound.puppet(3, gAmbientSound)


def FadeInAmbientSound(snd=None, speed=None):
    global gAmbientSound
    if snd is not None and snd != gAmbientSound:
        gAmbientSound = snd
        _rt().sound.puppet(3, snd)


def clearAmbientSound():
    global gAmbientSound
    _rt().sound.stop(3)
    gAmbientSound = 0


# ---- save / load / players ---------------------------------------------------------------------
def addObjectGlob(obj):
    if gSaveLoadObject:
        gSaveLoadObject.mAddObjectGlob(obj)


def setSaveLoadObject(o):
    global gSaveLoadObject
    gSaveLoadObject = o


def getPlayerDir(): return gPlayerDir
def getPlayer(): return gPlayer
def getSavedGamesDir(): return gSavedGameDir


def setPlayer(name):
    global gPlayer, gPlayerDir
    gPlayer = name
    gPlayerDir = os.path.join(gSavedGameDir, name) + os.sep
    os.makedirs(gPlayerDir, exist_ok=True)
    gSaveLoadObject.pFileDir = gPlayerDir
    gSaveLoadObject.mSetCurFile('GLOBAL')
    gSaveLoadObject.mRestore()


def getSavedGamesList():
    if not os.path.isdir(gSavedGameDir):
        return []
    return sorted(d for d in os.listdir(gSavedGameDir) if os.path.isdir(os.path.join(gSavedGameDir, d)))


def deleteGame(user):
    if user != '':
        d = os.path.join(gSavedGameDir, user)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)


def savegame():
    if gPlayer != '':
        if gGlobalSaveLoadObject:
            gGlobalSaveLoadObject.mSave()
        if gScreenDaddy:
            gScreenDaddy.mSave()


def savegame_safe():
    """savegame() that can never take the game down (used by the autosave hooks)."""
    try:
        savegame()
    except Exception as e:
        print('[save] failed:', e)


# ---- game helpers ----------------------------------------------------------------------------
def tokenFound(t):
    return gScreenDaddy.mTokenFound(t) if str(gScreenDaddy.mGetType()).upper() == 'GAME' else 0


def addGameToken(t):
    return gScreenDaddy.mAddToken(t) if str(gScreenDaddy.mGetType()).upper() == 'GAME' else 0


def riddlePlayed(): return gScreenDaddy.pRiddlePlayed
def setRiddlePlayed(): gScreenDaddy.pRiddlePlayed = 1


def getGlobalGameData(): return _rt().handlers['getGlobalGameData']


def getGameData(version):
    return _rt().handlers['getSpookyData_%s' % str(version).upper()]


def getHandlerData(name):
    return _rt().handlers.get(name)


def GlobalPlayDone(obj):
    if str(obj.pName).lower() == 'primer':
        runtime.destroy_object(obj)
        _rt().blank_sprite(160)           # take the LOADING... splash down
        gScreenDaddy.mShow()


# ---- sprite / game helpers used by the screens ------------------------------------------------
def setMember(chan, num):
    if isinstance(chan, (list, tuple)):
        for c, m in zip(chan, num):
            setMember(c, m)
        return
    s = _rt().sprites[chan]
    s.member = num
    s.loc = Point(320, 240)


def _game_attr(name):
    if str(gScreenDaddy.mGetType()).upper() == 'GAME':
        return getattr(gScreenDaddy, name)
    return None


def getGameHomeButton(): return _game_attr('pHomeButton')
def getGameHelpButton(): return _game_attr('pHelpButton')
def getGameBackButton(): return _game_attr('pBackButton')
def getGameRiddleStrip(): return _game_attr('pRiddleStripObject')
def getGameClueStrip(): return _game_attr('pClueStripObject')
def getGameCongratsAudio(): return _game_attr('pCongratsAudio')


def getPlayQueueObject(parent=None):
    if isinstance(parent, runtime.LObject):
        gPlayQueue.pParent = parent
    return gPlayQueue


def recyclePlayStack():
    gPlayQueue.pParent = 0
    gPlayQueue.pObjectList = []


def getBlendDissolveObject(parent=None):
    if isinstance(parent, runtime.LObject):
        gDissolveBlend.pParent = parent
    return gDissolveBlend


def recycleBlendDissolve():
    gDissolveBlend.pParent = 0
    gDissolveBlend.pSpriteList = []


class _PrimerParent:
    def mPlayDone(self, o):
        GlobalPlayDone(o)


def quitDialogue():
    name = str(gCurScreen.pName).upper()
    ver = str(gScreenDaddy.pCurrentVersion).lower()
    dlg = gCreditDialogue if (name == 'DOOR' or (name == 'MAIN' and ver != 'a')) else gQuitDialogue
    dlg.mLoad()
    dlg.mShow()


def doshutDown():
    try:
        savegame()
    finally:
        raise SystemExit(0)


# ---- INIT_MAIN -------------------------------------------------------------------------------
def _saved_games_dir(project_root):
    """Per-user save folder, under the same root the launcher uses: %LOCALAPPDATA%\\ISpySpookyMansionArchipelago\\SAVED GAMES
    (ISPY_PORT_HOME overrides the root; XDG data dir on non-Windows). Saves from the old in-project 'SAVED GAMES'
    folder are copied over the first time (the old folder is left alone)."""
    root = os.environ.get('ISPY_PORT_HOME')
    if not root:
        if os.name == 'nt':
            base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
        else:
            base = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
        root = os.path.join(base, 'ISpySpookyMansionArchipelago')
    new = os.path.join(root, 'SAVED GAMES')
    old = os.path.join(project_root, 'SAVED GAMES')
    if not os.path.isdir(new) and os.path.isdir(old):
        try:
            shutil.copytree(old, new)
            print('[saves] copied existing saves from', old, 'to', new)
        except OSError as e:
            print('[saves] could not copy the old saves:', e)
    os.makedirs(new, exist_ok=True)
    return new


def INIT_MAIN():
    global gScreenDaddy, gSavedGameDir, gGlobalSaveLoadObject, gSaveLoadObject
    global gQuitDialogue, gCreditDialogue, gDragSprite, gPlayQueue, gDissolveBlend
    from . import core, ui, game, screens, screens2, riddles, rooms, video, hunts  # noqa: F401  (registers the parent scripts)
    rt = _rt()
    loadStart = rt.milliseconds()
    gSavedGameDir = _saved_games_dir(rt.project_root)
    print('[saves] saved games in', gSavedGameDir)
    rt.clear_update()
    # LOADING... splash (main-cast member 9, which the Score showed while the movie booted)
    ls = rt.sprites[160]
    ls.member, ls.loc, ls.ink = 9, Point(320, 240), 8
    rt.draw()
    for i in range(1, 31):
        gSoundObjectPool.append(_new('INTERNALSOUND', Sym(str(i))))
        gExSoundObjectPool.append(_new('EXTERNALSOUND', Sym(str(i)), 'AIFF'))
        gWiggleObjectPool.append(_new('ANIM_WIGGLE'))
    for _ in range(20):
        gSimpleButtPool.append(runtime.get_object({'pType': 'BUTT_SIMPLE', 'pName': Sym('POOL')}, [0]))
    gPlayQueue = _new('PLAY_QUEUE')
    gDissolveBlend = _new('DISSOLVE_BLEND')
    gGlobalSaveLoadObject = _new('SAVELOAD', '')
    gSaveLoadObject = gGlobalSaveLoadObject
    alloc = get_range_list(1, 160)
    gDragSprite = pop_last(alloc)
    credit_range = pop_last_range(alloc, 5)
    gQuitDialogue = runtime.get_object(getHandlerData('getQuitDialogue'), list(credit_range))
    gCreditDialogue = runtime.get_object(getHandlerData('getCreditQuitDialogue'), credit_range)
    gScreenDaddy = runtime.get_object(getGlobalGameData(), alloc)
    rt.screen_daddy = gScreenDaddy
    gScreenDaddy.mLoad()
    # PC path of INIT_MAIN: hold the LOADING... splash for at least 3 s (the Mac-only getPrimerBumpData
    # bump is an off-screen BH-logo animation that just primes a sound, so it is not used here)
    if (rt.milliseconds() - loadStart) < 3000:
        t = _new('TIMER')
        t.pName = Sym('Primer')
        t.mSetTimeOutLength(3000 - (rt.milliseconds() - loadStart))
        t.mPlay()
    else:
        rt.blank_sprite(160)
        gScreenDaddy.mShow()
