#!/usr/bin/env python3
"""Build the launcher into ONE self-contained app for the machine you run this on.

    python packaging/build.py                      # build for this OS + CPU
    python packaging/build.py --expect-arch arm64  # fail unless this Python is arm64 (used by CI)
    python packaging/build.py --version v1.0       # put a version in the file names

PyInstaller cannot cross-compile, so each target is built on its own kind of machine. The GitHub workflow in
.github/workflows/build-launcher.yml does that for all five targets:

    Windows x86_64   ->  release/ISpyLauncher-windows-x86_64.exe            (single file)
    Windows ARM64    ->  release/ISpyLauncher-windows-arm64.exe             (single file)
    macOS Intel      ->  release/ISpyLauncher-macos-x86_64.app / .dmg / .app.zip
    macOS Apple Si.  ->  release/ISpyLauncher-macos-arm64.app  / .dmg / .app.zip
    Linux x86_64     ->  release/ISpyLauncher-linux-x86_64.AppImage

What is inside every build (nothing to install on the player's machine): the Python interpreter, tkinter, pygame,
pycdlib, the `ispy` game runtime, the `launcher`, the pure-Python `dirtools` extractor, tools/convert_data.py +
lingo_data.py, and ffmpeg for the Bink videos. NO game files are bundled; nothing is downloaded at first-time setup.

After building, the app is started once with --selftest (imports every module, loads the bundled data files) and
the build fails if that fails.
"""
import argparse
import ast
import os
import platform
import shutil
import stat
import struct
import subprocess
import sys
import urllib.request
import venv
import zipfile
import zlib
from pathlib import Path

APP = "ISpyLauncher"
BUNDLE_ID = "io.github.ispyport.launcher"
DISPLAY_NAME = "I SPY Spooky Mansion Port"

PKG = Path(__file__).resolve().parent            # ispy_port/packaging
ROOT = PKG.parent                                # ispy_port
WORK = PKG / ".work"                             # scratch (git-ignored)
CACHE = PKG / ".cache"                           # downloaded helpers (git-ignored)
OUT = ROOT / "release"                           # finished files (git-ignored)

HOST = {"win32": "windows", "darwin": "macos", "linux": "linux"}.get(sys.platform, sys.platform)
ARCH = {"amd64": "x86_64", "x86_64": "x86_64", "x64": "x86_64",
        "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())


def run(cmd, **kw):
    print("\n> " + " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def die(msg):
    print("\nERROR: " + msg, file=sys.stderr)
    sys.exit(1)


# ------------------------------------------------------------------------------------------------
# environment
# ------------------------------------------------------------------------------------------------

def make_venv(fresh):
    vdir = PKG / ".venv"
    if fresh and vdir.exists():
        shutil.rmtree(vdir)
    py = vdir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        print("Creating build environment in %s" % vdir)
        venv.EnvBuilder(with_pip=True).create(vdir)
    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-r", PKG / "requirements-build.txt"])
    return py


def check_tkinter(py):
    r = subprocess.run([str(py), "-c", "import tkinter"], capture_output=True)
    if r.returncode != 0:
        hint = {"linux": "Install it with your package manager, e.g. `sudo apt install python3-tk`.",
                "macos": "Use the python.org installer or `brew install python-tk`.",
                "windows": "Re-run the Python installer and tick 'tcl/tk and IDLE'."}.get(HOST, "")
        die("This Python has no tkinter, and the launcher's setup window needs it. " + hint)


# ------------------------------------------------------------------------------------------------
# things to bundle
# ------------------------------------------------------------------------------------------------

def hidden_imports_for_tools():
    """tools/convert_data.py is loaded from a file at run time, so PyInstaller can't see what it imports."""
    found = {"pycdlib"}
    for f in ("convert_data.py", "lingo_data.py"):
        tree = ast.parse((ROOT / "tools" / f).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    found.discard("lingo_data")                                  # our own file, shipped as data
    return sorted(m for m in found if m in sys.stdlib_module_names or m == "pycdlib")


def make_placeholder_png(path, size=256):
    """A plain generated icon so no game artwork is needed. Drop your own packaging/icon.png|ico|icns to replace it."""
    cx = cy = size / 2
    r2 = (size * 0.36) ** 2
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            inside = (x - cx) ** 2 + (y - cy) ** 2 <= r2
            row += bytes((235, 120, 30, 255) if inside else (40, 24, 64, 255))
        rows.append(bytes(row))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def get_icon():
    native = {"windows": "icon.ico", "macos": "icon.icns"}.get(HOST)
    for name in filter(None, (native, "icon.png")):
        if (PKG / name).is_file():
            return PKG / name
    p = WORK / "placeholder-icon.png"
    make_placeholder_png(p)
    return p


def fetch_win_x64_ffmpeg(py):
    """Windows-on-ARM fallback: imageio-ffmpeg may have no ARM64 wheel, but x64 ffmpeg runs fine under emulation."""
    tmp = CACHE / "ffmpeg-x64-wheel"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    r = subprocess.run([str(py), "-m", "pip", "download", "imageio-ffmpeg", "--no-deps", "--only-binary=:all:",
                        "--platform", "win_amd64", "--python-version", "%d.%d" % sys.version_info[:2],
                        "-d", str(tmp)])
    wheels = list(tmp.glob("*.whl"))
    if r.returncode != 0 or not wheels:
        return None
    with zipfile.ZipFile(wheels[0]) as z:
        names = [n for n in z.namelist() if "/binaries/" in n and n.lower().endswith(".exe")]
        if not names:
            return None
        z.extract(names[0], tmp)
        return tmp / names[0]


def get_ffmpeg(py, skip):
    """Return a path to an ffmpeg executable (copied to a predictable name), or None with --no-ffmpeg."""
    if skip:
        return None
    subprocess.run([str(py), "-m", "pip", "install", "imageio-ffmpeg"])           # best effort
    r = subprocess.run([str(py), "-c", "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"],
                       capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    src = Path(lines[-1]) if r.returncode == 0 and lines else None
    if (src is None or not src.is_file()) and HOST == "windows" and ARCH == "arm64":
        print("No ffmpeg for Windows ARM64 from imageio-ffmpeg; using the x64 build (runs under emulation).")
        src = fetch_win_x64_ffmpeg(py)
    if src is None or not src.is_file():
        die("Couldn't get an ffmpeg binary for the Bink videos. Install one yourself and try again, "
            "or build without video support using --no-ffmpeg.")
    dst = CACHE / "ffmpeg" / ("ffmpeg.exe" if HOST == "windows" else "ffmpeg")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print("Bundling ffmpeg: %s" % src)
    return dst


# ------------------------------------------------------------------------------------------------
# PyInstaller
# ------------------------------------------------------------------------------------------------

def pyinstaller(py, onefile, icon, ffmpeg):
    dist = WORK / "dist"
    sep = os.pathsep
    cmd = [py, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--name", APP,
           "--distpath", dist, "--workpath", WORK / "pyi-build", "--specpath", WORK,
           "--paths", ROOT,
           "--onefile" if onefile else "--onedir",
           "--collect-submodules", "ispy", "--collect-submodules", "ispy.ap", "--collect-submodules", "launcher",
           "--collect-submodules", "dirtools",
           "--collect-data", "ispy.ap",                          # riddle_clues.json lives inside the package
           "--collect-data", "pygame", "--collect-binaries", "pygame",
           "--collect-data", "certifi",                           # cacert.pem for the Archipelago wss:// connection
           "--add-data", "%s%stools" % (ROOT / "tools" / "convert_data.py", sep),
           "--add-data", "%s%stools" % (ROOT / "tools" / "lingo_data.py", sep),
           "--icon", icon]
    if HOST in ("windows", "macos"):
        cmd.append("--windowed")                                 # no console window behind the GUI
    if HOST == "macos":
        cmd += ["--osx-bundle-identifier", BUNDLE_ID]
    if (ROOT / "AP Menu").is_dir():                            # Archipelago menu art (+ optional you_found_me sound)
        cmd += ["--add-data", "%s%sAP Menu" % (ROOT / "AP Menu", sep)]
    if ffmpeg:
        cmd += ["--add-binary", "%s%sffmpeg" % (ffmpeg, sep)]
    if (ROOT / "ispy" / "icon.png").is_file():                  # window/taskbar icon (tools/extract_icon.py)
        cmd += ["--add-data", "%s%sispy" % (ROOT / "ispy" / "icon.png", sep)]
    for m in hidden_imports_for_tools():
        cmd += ["--hidden-import", m]
    cmd.append(PKG / "entry.py")
    shutil.rmtree(dist, ignore_errors=True)
    run(cmd)
    return dist


def selftest(exe, ffmpeg_bundled):
    home = WORK / "selftest-home"
    shutil.rmtree(home, ignore_errors=True)
    env = dict(os.environ, ISPY_PORT_HOME=str(home), ISPY_SELFTEST_FFMPEG="1" if ffmpeg_bundled else "0")
    print("\nSelf-test of the built app...")
    r = subprocess.run([str(exe), "--selftest"], env=env, capture_output=True, text=True, timeout=300)
    log = home / "logs" / "launcher.log"
    text = (r.stdout or "") + (r.stderr or "")
    if not text.strip() and log.exists():                        # windowed apps have no stdout: read the log
        text = log.read_text(encoding="utf-8", errors="replace")
    print(text.rstrip() or "(no output)")
    if r.returncode != 0:
        die("The built app failed its self-test (exit code %s). See the lines marked FAIL above." % r.returncode)


def out_name(suffix, version):
    tag = "-" + version if version else ""
    return OUT / ("%s%s-%s-%s%s" % (APP, tag, HOST, ARCH, suffix))


# ------------------------------------------------------------------------------------------------
# per-OS packaging
# ------------------------------------------------------------------------------------------------

def build_windows(py, icon, ffmpeg, version):
    dist = pyinstaller(py, True, icon, ffmpeg)
    exe = dist / (APP + ".exe")
    selftest(exe, bool(ffmpeg))
    OUT.mkdir(parents=True, exist_ok=True)
    final = out_name(".exe", version)
    shutil.copy2(exe, final)
    return [final]


def make_dmg(stage, dmg, attempts=5):
    """hdiutil fails now and then on CI runners with 'Resource busy' (Spotlight / a stale mount holds the folder).
    Nothing is wrong with the build, so wait and try again."""
    import time
    for n in range(1, attempts + 1):
        try:
            run(["hdiutil", "create", "-volname", DISPLAY_NAME, "-srcfolder", stage, "-ov", "-format", "UDZO", dmg])
            return
        except subprocess.CalledProcessError:
            if n == attempts:
                raise
            print("hdiutil failed (attempt %d of %d); retrying in %d s..." % (n, attempts, 10 * n), flush=True)
            subprocess.run(["hdiutil", "detach", "/Volumes/" + DISPLAY_NAME, "-force"], capture_output=True)
            Path(dmg).unlink(missing_ok=True)
            time.sleep(10 * n)


def build_macos(py, icon, ffmpeg, version):
    dist = pyinstaller(py, False, icon, ffmpeg)
    app = dist / (APP + ".app")
    if not app.is_dir():
        die("PyInstaller didn't produce %s" % app)
    selftest(app / "Contents" / "MacOS" / APP, bool(ffmpeg))
    OUT.mkdir(parents=True, exist_ok=True)
    final_app = out_name(".app", version)
    shutil.rmtree(final_app, ignore_errors=True)
    shutil.copytree(app, final_app, symlinks=True)

    stage = WORK / "dmg-stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    shutil.copytree(app, stage / (APP + ".app"), symlinks=True)
    (stage / "Applications").symlink_to("/Applications")
    dmg = out_name(".dmg", version)
    dmg.unlink(missing_ok=True)
    make_dmg(stage, dmg)

    zipped = out_name(".app.zip", version)                       # a plain zip keeps the exec bits (for CI artifacts)
    zipped.unlink(missing_ok=True)
    run(["ditto", "-c", "-k", "--keepParent", final_app, zipped])
    return [final_app, dmg, zipped]


APPIMAGETOOL_URL = "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-%s.AppImage"


def get_appimagetool(arch, override):
    if override:
        return Path(override)
    name = {"x86_64": "x86_64", "arm64": "aarch64"}.get(arch)
    if not name:
        die("No appimagetool for CPU '%s'." % arch)
    tool = CACHE / ("appimagetool-%s.AppImage" % name)
    if not tool.exists():
        tool.parent.mkdir(parents=True, exist_ok=True)
        print("Downloading appimagetool...")
        urllib.request.urlretrieve(APPIMAGETOOL_URL % name, tool)
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return tool


def build_linux(py, icon, ffmpeg, version, appimagetool):
    dist = pyinstaller(py, False, icon, ffmpeg)
    folder = dist / APP
    selftest(folder / APP, bool(ffmpeg))

    appdir = WORK / (APP + ".AppDir")
    shutil.rmtree(appdir, ignore_errors=True)
    (appdir / "usr" / "bin").mkdir(parents=True)
    shutil.copytree(folder, appdir / "usr" / "bin" / APP, symlinks=True)
    shutil.copy2(icon if icon.suffix == ".png" else WORK / "placeholder-icon.png", appdir / (APP + ".png"))
    (appdir / (APP + ".desktop")).write_text(
        "[Desktop Entry]\nType=Application\nName=%s\nComment=Setup and launcher for the I SPY Spooky Mansion port\n"
        "Exec=%s\nIcon=%s\nCategories=Game;\nTerminal=false\n" % (DISPLAY_NAME, APP, APP), encoding="utf-8")
    apprun = appdir / "AppRun"
    apprun.write_text('#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\nexec "$HERE/usr/bin/%s/%s" "$@"\n' % (APP, APP),
                      encoding="utf-8")
    apprun.chmod(0o755)

    OUT.mkdir(parents=True, exist_ok=True)
    final = out_name(".AppImage", version)
    final.unlink(missing_ok=True)
    tool = get_appimagetool(ARCH, appimagetool)
    env = dict(os.environ, ARCH={"x86_64": "x86_64", "arm64": "aarch64"}[ARCH], APPIMAGE_EXTRACT_AND_RUN="1")
    run([tool, appdir, final], env=env)
    final.chmod(0o755)
    return [final]


# ------------------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expect-arch", choices=["x86_64", "arm64"], help="fail if this Python isn't for that CPU")
    ap.add_argument("--version", default="", help="added to the output file names, e.g. v1.0")
    ap.add_argument("--no-venv", action="store_true", help="use the current Python and its installed packages")
    ap.add_argument("--fresh", action="store_true", help="recreate packaging/.venv from scratch")
    ap.add_argument("--no-ffmpeg", action="store_true", help="don't bundle ffmpeg (Bink videos fall back to stills)")
    ap.add_argument("--appimagetool", help="path to an appimagetool binary (Linux); default: download it")
    a = ap.parse_args()

    print("Host: %s %s, Python %s (%s)" % (HOST, ARCH, platform.python_version(), platform.machine()))
    if HOST not in ("windows", "macos", "linux"):
        die("Unsupported OS: %s" % sys.platform)
    if a.expect_arch and a.expect_arch != ARCH:
        die("This Python is %s but --expect-arch is %s. Install a native %s Python and run again."
            % (ARCH, a.expect_arch, a.expect_arch))
    if HOST == "linux" and ARCH not in ("x86_64", "arm64"):
        die("Unsupported CPU: %s" % ARCH)
    for needed in (ROOT / "ispy" / "main.py", ROOT / "launcher" / "__main__.py", ROOT / "dirtools" / "ripper.py",
                   ROOT / "tools" / "convert_data.py"):
        if not needed.is_file():
            die("Missing %s - run this from a full checkout of the port." % needed)

    py = Path(sys.executable) if a.no_venv else make_venv(a.fresh)
    check_tkinter(py)
    WORK.mkdir(parents=True, exist_ok=True)
    icon = get_icon()
    ffmpeg = get_ffmpeg(py, a.no_ffmpeg)

    if HOST == "windows":
        files = build_windows(py, icon, ffmpeg, a.version)
    elif HOST == "macos":
        files = build_macos(py, icon, ffmpeg, a.version)
    else:
        files = build_linux(py, icon, ffmpeg, a.version, a.appimagetool)

    print("\nDone. Built:")
    for f in files:
        print("  " + str(f))


if __name__ == "__main__":
    main()
