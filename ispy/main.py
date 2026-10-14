"""Entry point.

    python -m ispy.main --exports ..\\Exports --data data            # run
    python -m ispy.main --exports ..\\Exports --data data --report   # boot headless, list unported scripts
"""
import argparse
import os
import sys

from . import runtime, movie


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--exports', required=True, help='path to DirectorCastRipper Exports folder')
    ap.add_argument('--data', default='data', help='folder produced by tools/convert_data.py')
    ap.add_argument('--report', action='store_true', help='boot headless for a few seconds and list unported scripts')
    ap.add_argument('--game', default=None, help='installed game folder (for AIFF voice-overs); default: <exports>/../ispy_spooky_mansion_deluxe')
    ap.add_argument('--seconds', type=float, default=3.0)
    a = ap.parse_args(argv)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    exports = os.path.abspath(a.exports)
    game = a.game or os.path.join(os.path.dirname(exports), 'ispy_spooky_mansion_deluxe')
    rt = runtime.init_runtime(root, exports, game)
    rt.load_data(a.data)
    rt.init_pygame(headless=a.report)
    movie.INIT_MAIN()
    try:
        from .ap import hooks
        hooks.install(rt)             # Archipelago: pump/overlay + in-game hooks (no-op until a slot connects)
    except Exception as e:            # noqa: BLE001  AP must never stop the game from starting
        print('[ap] hooks not installed:', e)

    if a.report:
        import time
        from .stubs import MISSING
        end = time.time() + a.seconds
        while time.time() < end:
            rt.tick()
            time.sleep(0.01)
        print('Unported scripts that were touched during boot:')
        for name in sorted(MISSING):
            print('  %-22s %s' % (name, ', '.join(sorted(MISSING[name])) or '(constructed only)'))
        return 0
    try:
        rt.run()
    finally:
        movie.savegame_safe()          # window closed, Ctrl+C or a crash: keep the progress
    return 0


if __name__ == '__main__':
    sys.exit(main())
