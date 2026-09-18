"""Shared plumbing for the instancing spikes: result recording, document
housekeeping and console capture.

Used by ``spike_variant_link.py`` (round 1, App::Link copy-on-change) and
``spike_copyobject.py`` (round 2, doc.copyObject).  Nothing here imports a
production module -- the spikes are evaluations only.
"""

import os
import sys
import tempfile
import traceback

import FreeCAD as App

TOL = 1e-6          # relative volume tolerance


class Result(object):
    def __init__(self, ident, title):
        self.id = ident
        self.title = title
        self.status = "FAIL"
        self.notes = []          # (label, value) pairs, in order
        self.exceptions = []     # (where, text)

    def note(self, label, value):
        self.notes.append((label, str(value)))
        print("    %-40s %s" % (label + ":", value))

    def check(self, label, ok, detail=""):
        self.note("%s %s" % ("PASS" if ok else "FAIL", label),
                  detail if detail != "" else ok)
        return bool(ok)

    def error(self, where, exc):
        text = "%s: %s" % (type(exc).__name__, exc)
        self.exceptions.append((where, text))
        print("    !! %s -- %s" % (where, text))
        print(traceback.format_exc())


class Recorder(object):
    def __init__(self):
        self.results = []

    def start(self, ident, title):
        r = Result(ident, title)
        self.results.append(r)
        print("\n=== %s  %s" % (ident, title))
        return r

    def get(self, ident):
        for r in self.results:
            if r.id == ident:
                return r
        return None


def close_all():
    for name in list(App.listDocuments()):
        try:
            App.closeDocument(name)
        except Exception:
            pass


def near(a, b, tol=TOL):
    if a is None or b is None:
        return False
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) / scale < tol


def save(doc, workdir, stem):
    path = os.path.join(workdir, stem + ".FCStd")
    doc.saveAs(path)
    return path


def force_recompute(doc):
    doc.recompute(None, True, True)


def _flush_all():
    """Flush Python's buffers *and* the C runtime's.

    FreeCAD writes from C++, so anything still sitting in the CRT's stdout
    buffer would otherwise be carried across the ``dup2`` and land in the
    capture file -- appearing as duplicated output.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        import ctypes
        ctypes.CDLL("msvcrt").fflush(None)
    except Exception:
        pass


def capture_console(fn):
    """Run ``fn()`` with the process's stdout/stderr redirected to a file,
    and return ``(result, text)``.

    FreeCAD's warnings come from C++ and never pass through ``sys.stdout``,
    so a file-descriptor level redirect is the only way to see them -- which
    is what the ``hasher mismatch`` and ``does not exist!`` comparisons need.
    """
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
    handle.close()
    _flush_all()
    saved_out, saved_err = os.dup(1), os.dup(2)
    fd = os.open(handle.name, os.O_WRONLY)
    try:
        os.dup2(fd, 1)
        os.dup2(fd, 2)
        result = fn()
    finally:
        _flush_all()
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        for descriptor in (fd, saved_out, saved_err):
            os.close(descriptor)
    with open(handle.name, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    try:
        os.remove(handle.name)
    except OSError:
        pass
    return result, text


def render_results(rec, headlines):
    """The results table plus one observation table per test."""
    lines = []
    w = lines.append
    w("## Results")
    w("")
    w("| Test | Status | Headline |")
    w("|---|---|---|")
    for r in rec.results:
        w("| **%s** %s | **%s** | %s |"
          % (r.id, r.title, r.status, headlines.get(r.id, "")))
    w("")
    for r in rec.results:
        w("### %s — %s (%s)" % (r.id, r.title, r.status))
        w("")
        if r.notes:
            w("| Observation | Value |")
            w("|---|---|")
            for label, value in r.notes:
                w("| %s | `%s` |" % (label.replace("|", "\\|"),
                                     value.replace("|", "\\|")))
            w("")
        if r.exceptions:
            w("Exceptions:")
            w("")
            for where, text in r.exceptions:
                w("- **%s** — `%s`" % (where, text))
            w("")
    return lines


# --------------------------------------------------------------------------
# the round-2b assertion: a correct volume is not a passing test
# --------------------------------------------------------------------------

#: ``getStatusString()`` values that mean "nothing wrong here".
HEALTHY_STATUS = ("", "Valid", "Up-to-date")

#: Substrings that make a console line a fault rather than chatter.
CONSOLE_FAULTS = ("error", "warning", "failed", "cannot", "invalid",
                  "shape is null", "out of the allowed scope",
                  "hasher mismatch", "does not exist")


def unhealthy(doc):
    """``[(name, State, statusString)]`` for objects not fully Up-to-date.

    Round 2 asserted only that a volume reached its expected value after a
    parameter change, which a stale-but-plausible model passes.  This is
    the missing half.
    """
    bad = []
    for obj in doc.Objects:
        state = list(obj.State)
        try:
            status = obj.getStatusString()
        except Exception:
            status = "<unreadable>"
        if state != ["Up-to-date"] or status not in HEALTHY_STATUS:
            bad.append((obj.Name, state, status))
    return bad


def console_faults(text):
    """Distinct console lines that look like a fault, in order."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        low = line.lower()
        if line and any(f in low for f in CONSOLE_FAULTS) and line not in out:
            out.append(line)
    return out


def changed_cleanly(r, doc, label, mutate, measure, expected):
    """Apply ``mutate()``, recompute, and assert all three of round 2b's
    conditions: the measured value reached ``expected``, no object is left
    in an error or touched state, and the console stayed quiet.

    Returns ``(ok, forced)``.
    """
    def run():
        mutate()
        doc.recompute()

    _, console = capture_console(run)
    value = measure()
    forced = False
    if not near(value, expected):
        _, extra = capture_console(lambda: force_recompute(doc))
        console += extra
        value = measure()
        forced = True

    bad = unhealthy(doc)
    faults = console_faults(console)
    ok_value = near(value, expected)

    r.note("%s: value" % label,
           "%.3f (expected %.3f)" % (value, expected))
    r.note("%s: forced recompute needed" % label, "YES" if forced else "no")
    r.note("%s: objects not Up-to-date" % label, bad or "none")
    r.note("%s: console faults during recompute" % label,
           faults or "none")
    ok = ok_value and not bad and not faults
    r.check("%s -- value, object state and console all clean" % label, ok,
            "value=%s state=%s console=%s"
            % ("ok" if ok_value else "WRONG",
               "clean" if not bad else "%d bad" % len(bad),
               "quiet" if not faults else "%d faults" % len(faults)))
    return ok, forced
