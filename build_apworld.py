"""Pack APWorld/ispy_spooky_mansion into release/ispy_spooky_mansion.apworld and (optionally) install it.

    python build_apworld.py                       # build + install to C:\\ProgramData\\Archipelago\\custom_worlds
    python build_apworld.py --no-install          # only build
    python build_apworld.py --dest <folder>       # install somewhere else
"""
import argparse
import os
import shutil
import sys
import zipfile

NAME = 'ispy_spooky_mansion'
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'APWorld', NAME)
OUT = os.path.join(HERE, 'release', NAME + '.apworld')
DEFAULT_DEST = r'C:\ProgramData\Archipelago\custom_worlds'
SKIP_DIRS = {'__pycache__', 'test', '.git', '.vscode'}      # the in-world test/ folder needs Archipelago's source tree
SKIP_EXT = {'.pyc', '.pyo'}


def build():
    if not os.path.isfile(os.path.join(SRC, '__init__.py')):
        sys.exit('ERROR: %s not found' % os.path.join(SRC, '__init__.py'))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    count = 0
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(SRC):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                if os.path.splitext(f)[1] in SKIP_EXT:
                    continue
                full = os.path.join(root, f)
                z.write(full, (NAME + '/' + os.path.relpath(full, SRC)).replace(os.sep, '/'))
                count += 1
    with zipfile.ZipFile(OUT) as z:
        names = z.namelist()
        if z.testzip() is not None or NAME + '/__init__.py' not in names or NAME + '/archipelago.json' not in names:
            sys.exit('ERROR: the built apworld is incomplete')
    print('Packed %d files -> %s' % (count, OUT))


def install(dest):
    os.makedirs(dest, exist_ok=True)
    target = os.path.join(dest, NAME + '.apworld')
    shutil.copy2(OUT, target)
    print('Installed: ' + target)
    if os.path.isdir(os.path.join(dest, NAME)):
        print("WARNING: an unpacked folder '%s' also exists and may override the .apworld; delete it if Archipelago "
              "does not pick up this build." % os.path.join(dest, NAME))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-install', action='store_true')
    ap.add_argument('--dest', default=os.environ.get('AP_CUSTOM_WORLDS') or DEFAULT_DEST)
    a = ap.parse_args()
    build()
    if not a.no_install:
        install(a.dest)


if __name__ == '__main__':
    main()
