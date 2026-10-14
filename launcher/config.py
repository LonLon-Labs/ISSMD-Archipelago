import os
import sys
from pathlib import Path

APP_NAME = "ISpySpookyMansionArchipelago"

# Bump when the pipeline itself changes in a way that invalidates previously generated files.
STAMP_VERSION = 2


def default_root():
    """Per-user app data folder. Must match ispy.movie._saved_games_dir so saves land under the same root.
    ISPY_PORT_HOME overrides it (testing, or moving everything to another drive)."""
    env = os.environ.get("ISPY_PORT_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / APP_NAME


def code_root():
    """Folder holding the `ispy` and `tools` packages: the repo's ispy_port folder, or PyInstaller's bundle folder."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


class Paths:
    """Everything the launcher reads or writes. Override the base with ISPY_PORT_HOME for testing."""

    def __init__(self, root=None):
        self.root = Path(root) if root is not None else default_root()
        self.repo_root = code_root()                              # ispy_port/ (or the frozen bundle)

    @property
    def tools(self):          return self.root / "tools"
    @property
    def ripper_dir(self):     return self.tools / "DirectorCastRipper"
    @property
    def ripper_exe(self):     return self.ripper_dir / "DirectorCastRipper.exe"
    @property
    def game(self):           return self.root / "game"            # game_root: DATA\AIFF, DATA\BINK
    @property
    def work(self):           return self.root / "work"            # raw disc files, deleted after ripping
    @property
    def exports(self):        return self.root / "exports"         # exports_root
    @property
    def exports_partial(self):return self.root / "exports.partial"
    @property
    def data(self):           return self.root / "data"            # handlers.json etc.
    @property
    def data_partial(self):   return self.root / "data.partial"
    @property
    def state_file(self):     return self.root / "state.json"
    @property
    def logs(self):           return self.root / "logs"
    @property
    def convert_script(self): return self.repo_root / "tools" / "convert_data.py"
    @property
    def lingo_script(self):   return self.repo_root / "tools" / "lingo_data.py"

    def ensure(self):
        for p in (self.root, self.tools, self.logs):
            p.mkdir(parents=True, exist_ok=True)
