"""Make ``freecad.bentwizard`` resolve to THIS repo's code.

Under the bundled interpreter, FreeCAD ships its own regular ``freecad``
package, and FreeCAD's Mod scan grafts the dev-installed copy (the
%APPDATA% junction -> the MAIN repo) onto its ``__path__`` ahead of the
checkout the tests sit in. A worktree's suite would then silently
exercise the main repo's code. Front-loading this repo's package path
makes the code under test always the checkout containing the tests.

Import this before any ``freecad.bentwizard`` import; FreeCAD-dependent
test modules call :func:`graft` again right after ``import FreeCAD``
(whose init may extend the path) — it is idempotent.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def graft():
    """Front-load this repo's ``freecad`` package dir on the package's
    search path, so ``freecad.bentwizard`` imports from this checkout."""
    try:
        import freecad
    except ImportError:
        return          # plain Python: the sys.path entry is enough
    pkg = str(REPO_ROOT / "freecad")
    try:
        paths = freecad.__path__
        if pkg in paths:
            paths.remove(pkg)
        paths.insert(0, pkg)
    except (AttributeError, ValueError, TypeError):
        pass            # namespace-path object: repo path already wins
    # freecadcmd pre-imports freecad.bentwizard from the Mod junction at
    # startup; drop any copy imported from elsewhere so the next import
    # resolves from this checkout
    for name, mod in list(sys.modules.items()):
        if name == "freecad.bentwizard" \
                or name.startswith("freecad.bentwizard."):
            file = getattr(mod, "__file__", "") or ""
            if not file.startswith(str(REPO_ROOT)):
                del sys.modules[name]


graft()
