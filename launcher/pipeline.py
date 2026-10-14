"""The first-run pipeline: validate disc -> extract -> tools -> rip -> convert -> stamp."""
import shutil
import threading

from . import convert as convert_mod
from . import disc, ripper, state, tools
from .config import STAMP_VERSION
from .errors import LauncherError, NeedDisc

STAGES = [
    ("check", "Checking the disc", 2),
    ("extract", "Copying files from the disc", 30),
    ("tools", "Preparing tools", 1),
    ("rip", "Extracting game assets", 57),
    ("convert", "Converting game data", 8),
    ("finish", "Finishing up", 2),
]


class Reporter:
    """Turns per-stage progress into one overall fraction. emit(overall, stage_label, message)."""

    def __init__(self, emit):
        self.emit = emit
        self.total = float(sum(w for _, _, w in STAGES))
        self.base = 0.0
        self.cur = None

    def _info(self, key):
        for k, label, w in STAGES:
            if k == key:
                return label, w
        raise KeyError(key)

    def begin(self, key):
        self.cur = key
        label, _ = self._info(key)
        self.emit(self.base / self.total, label, "")

    def update(self, frac, msg=""):
        label, w = self._info(self.cur)
        self.emit((self.base + w * max(0.0, min(1.0, frac))) / self.total, label, msg)

    def done(self, key, msg=""):
        label, w = self._info(key)
        self.base += w
        self.emit(self.base / self.total, label, msg)


# --------------------------------------------------------------------------------------------
# state queries (no disc needed)
# --------------------------------------------------------------------------------------------

def _extract_sig(fingerprint):
    return state.sig_of(STAMP_VERSION, fingerprint)


def _rip_sig(paths, fingerprint):
    return state.sig_of(_extract_sig(fingerprint), tools.tools_signature(paths), ripper.cli_hash())


def _convert_sig(paths, fingerprint):
    return state.sig_of(_rip_sig(paths, fingerprint), state.file_hash(paths.convert_script, paths.lingo_script))


def _game_files_ok(paths):
    aiff = paths.game / "DATA" / "AIFF"
    return aiff.is_dir() and any(aiff.iterdir())


def rip_valid(paths, st, fingerprint):
    """The exported files are usable. Judged by what is actually on disk, NOT by version stamps or tool signatures:
    those change with every launcher update, and re-ripping would force the user to find their disc again.
    Only a different disc than the one recorded (when a disc is supplied) invalidates the export."""
    saved = st.get("fingerprint")
    if fingerprint and saved and fingerprint != saved:
        return False
    return not ripper.verify_exports(paths.exports) and _game_files_ok(paths)


def needs_disc(paths, st=None):
    st = st if st is not None else state.load(paths)
    return not rip_valid(paths, st, None)


def is_ready(paths):
    """True when a launch can skip all setup work."""
    st = state.load(paths)
    if not state.stamp_ok(st) or needs_disc(paths, st):
        return False
    fp = st.get("fingerprint")
    return (state.stage_sig(st, "convert") == _convert_sig(paths, fp)
            and all((paths.data / f).exists() for f in convert_mod.REQUIRED_OUTPUT))


# --------------------------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------------------------

def run_setup(paths, disc_path, rep, cancel=None, ripper_dir=None, log=print):
    """Do whatever setup is still needed. Raises LauncherError / NeedDisc / Cancelled."""
    cancel = cancel or threading.Event()
    paths.ensure()
    st = state.load(paths)
    if not state.stamp_ok(st):
        # New launcher version: drop the stage signatures (so convert re-runs) but keep what identifies the old export.
        st = {"stamp_version": STAMP_VERSION, "fingerprint": st.get("fingerprint")}

    rep.begin("check")
    source = report = None
    fingerprint = st.get("fingerprint")
    try:
        if disc_path:
            source = disc.open_source(disc_path)
            report = disc.collect(source)
            for w in report.warnings:
                log("warning: " + w)
            if not report.ok:
                raise LauncherError(
                    "This disc is missing files the port needs.",
                    detail="\n".join(report.errors),
                    hint="Make sure you chose the I SPY Spooky Mansion Deluxe disc (not another title, "
                         "and not an installer-only image).")
            log("Disc OK: " + report.summary())
            fingerprint = report.fingerprint
            _check_space(paths, report)
        elif needs_disc(paths, st):
            raise NeedDisc()
        rep.done("check", "Disc looks good" if report else "Using files from an earlier setup")

        # ---- extract / tools / rip: skipped entirely when already valid for this disc ----
        if rip_valid(paths, st, fingerprint):
            state.mark(st, "rip", _rip_sig(paths, fingerprint))
            for k in ("extract", "tools", "rip"):
                rep.begin(k)
                rep.done(k, "Already done")
        else:
            rep.begin("extract")
            disc.extract(source, report, paths.work, paths.game, rep.update, cancel)
            state.mark(st, "extract", _extract_sig(fingerprint))
            st["fingerprint"] = fingerprint
            state.save(paths, st)
            rep.done("extract")

            rep.begin("tools")
            tools.ensure_tools(paths, rep.update, cancel, local_ripper_dir=ripper_dir)
            rep.done("tools")

            rep.begin("rip")
            ripper.rip_all(paths, rep.update, cancel, log)
            state.mark(st, "rip", _rip_sig(paths, fingerprint))
            state.clear_from(st, ["convert"])
            state.save(paths, st)
            shutil.rmtree(paths.work, ignore_errors=True)      # raw disc files are no longer needed
            rep.done("rip")

        # ---- convert ----
        rep.begin("convert")
        csig = _convert_sig(paths, fingerprint)
        have_data = all((paths.data / f).exists() for f in convert_mod.REQUIRED_OUTPUT)
        if state.stage_sig(st, "convert") == csig and have_data:
            rep.done("convert", "Already done")
        else:
            rep.update(0.1, "Building handlers.json, script_ids.json, members_main.json")
            failures = convert_mod.convert(paths, log)
            for f in failures:
                log("warning: " + f)
            state.mark(st, "convert", csig)
            state.save(paths, st)
            rep.done("convert")

        # ---- finish ----
        rep.begin("finish")
        st["stamp_version"] = STAMP_VERSION
        st["fingerprint"] = fingerprint
        st["complete"] = True
        state.save(paths, st)
        rep.done("finish", "Ready to play")
    finally:
        if source is not None:
            source.close()


def _check_space(paths, report):
    paths.root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(paths.root).free
    need = report.total_bytes * 3 + 200 * 1024 * 1024          # rough: raw copy + exports + slack
    if free < need:
        raise LauncherError(
            "Not enough free disk space.",
            detail="Need roughly %d MB, have %d MB free on the drive holding %s." % (need >> 20, free >> 20, paths.root),
            hint="Free up some space and try again.")
