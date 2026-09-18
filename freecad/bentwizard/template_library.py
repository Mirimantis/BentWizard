"""The joint template library: where templates live, and how a user's
own joint gets into it.

Two directories are searched — the user's template folder (one
configurable path, remembered in FreeCAD's parameters) and the shipped
``library/`` that comes with the workbench. The user's folder wins on a
stem collision, so a locally revised copy of a shipped joint shadows the
shipped one instead of appearing twice.

Saving is ``Document.saveCopy``: the authoring document keeps its own
file name and its unmodified state. Relabeling the joint VarSet is
FreeCAD's rename, not an expression rewrite: relabeling rebinds every
``<<Label>>`` reference in the document, which is what makes the offer
safe.

FreeCAD is imported lazily, inside the functions that need it, so the
discovery half stays usable from a pure-Python context.
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

from . import naming
from .fcstd import FcstdDocument

SHIPPED_DIR = Path(__file__).resolve().parents[2] / "library"
PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/BentWizard"
USER_DIR_KEY = "TemplateDir"
TEMPLATE_SUFFIX = ".FCStd"


class TemplateError(ValueError):
    """A template save/create request that cannot be honored."""


# --------------------------------------------------------------------------
# Opening a template behind the user's document
# --------------------------------------------------------------------------

def restore_active(doc):
    """Make `doc` the active document again (App and, when the GUI is
    up, Gui) if it is still open. No-op for None or a closed document."""
    import FreeCAD as App
    if doc is None:
        return
    try:
        name = doc.Name
    except Exception:                  # a closed document's proxy
        return
    if name not in App.listDocuments():
        return
    App.setActiveDocument(name)
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.setActiveDocument(name)


@contextlib.contextmanager
def open_hidden(path):
    """Open a template read-only behind the user's document and close it
    again afterwards, restoring the active document.

    In the GUI, ``openDocument(hidden=True)`` makes the hidden file the
    active document (App and Gui), and closing it leaves *no* active
    document at all: every command that needs one greys out and the
    report view fills with access violations (Adam's first GUI round of
    rev 2). Every hidden open goes through here.
    """
    import FreeCAD as App
    active = App.ActiveDocument
    doc = App.openDocument(str(path), hidden=True)
    try:
        yield doc
    finally:
        App.closeDocument(doc.Name)
        restore_active(active)


# --------------------------------------------------------------------------
# Where templates live
# --------------------------------------------------------------------------

def default_user_dir():
    import FreeCAD as App
    return Path(App.getUserAppDataDir()) / "BentWizard" / "library"


def user_dir():
    import FreeCAD as App
    configured = App.ParamGet(PARAM_PATH).GetString(USER_DIR_KEY, "")
    return Path(configured) if configured else default_user_dir()


def set_user_dir(path):
    import FreeCAD as App
    App.ParamGet(PARAM_PATH).SetString(USER_DIR_KEY, str(Path(path)))


def search_dirs():
    """User folder first, shipped library second — the shadowing order."""
    dirs = [user_dir(), SHIPPED_DIR]
    seen, out = set(), []
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _as_dirs(dirs):
    if dirs is None:
        return search_dirs()
    if isinstance(dirs, (str, Path)):
        return [Path(dirs)]
    return [Path(d) for d in dirs]


def templates(dirs=None):
    """[(stem, Path)] sorted by stem, first directory winning a tie."""
    found = {}
    for directory in _as_dirs(dirs):
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*" + TEMPLATE_SUFFIX)):
            found.setdefault(path.stem, path)
    return sorted(found.items())


def find(stem, dirs=None):
    for name, path in templates(dirs):
        if name == stem:
            return path
    return None


def is_starter(path):
    """A jointless skeleton: two timbers with a paired datum each and no
    Boolean anywhere. Structural rather than a declared flag — a starter
    has nothing to inherit, which is what an author wants to begin from
    (finding #12)."""
    try:
        doc = FcstdDocument.from_file(path)
    except Exception:
        return False
    if doc.of_type("PartDesign::Boolean"):
        return False
    return len(doc.of_type("PartDesign::Body")) >= 2


def starters(dirs=None):
    return [(stem, path) for stem, path in templates(dirs) if is_starter(path)]


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

def stem_for(kind):
    """'BraceMT' -> 'Joint_BraceMT'."""
    kind = (kind or "").strip()
    if not kind:
        raise TemplateError("a template needs a joint kind (e.g. 'BraceMT')")
    bad = naming.reserved_in_label(kind)
    if bad:
        raise TemplateError(f"joint kind {kind!r} contains reserved "
                            f"character(s) {bad!r}")
    return naming.template_stem(kind)


def template_path(directory, kind):
    return Path(directory) / (stem_for(kind) + TEMPLATE_SUFFIX)


def _joint_varset(doc):
    joints = [o for o in doc.Objects
              if o.TypeId == "App::VarSet" and naming.parse_joint_label(o.Label)]
    if len(joints) != 1:
        raise TemplateError(
            f"expected exactly one joint VarSet labelled J-<Kind>-<serial>, "
            f"found {[o.Label for o in joints]} — a template holds one joint")
    return joints[0]


def wanted_label(kind):
    return naming.joint_label(naming.template_kind_from_stem(stem_for(kind)),
                              naming.TEMPLATE_SERIAL)


def rename_needed(doc, kind):
    """The joint label the document would take for `kind`, or None when
    it already carries it."""
    joint = _joint_varset(doc)
    want = wanted_label(kind)
    return None if joint.Label == want else want


def relabel(doc, kind):
    """Relabel the joint VarSet to J-<kind>-000 and retag every
    component, Boolean and mirroring label to the kind. No expression
    rewriting: FreeCAD rebinds <<Label>> references on relabel."""
    from .apply import joint_members
    joint = _joint_varset(doc)
    new_label = wanted_label(kind)
    new_kind = naming.template_kind_from_stem(stem_for(kind))
    joint.Label = new_label
    for obj in joint_members(joint):
        if obj.TypeId == "PartDesign::Body" and hasattr(obj, naming.PROP_COMPONENT_ROLE):
            obj.Label = naming.retag_component_label(obj.Label, new_kind,
                                                     naming.TEMPLATE_SERIAL)
    for obj in joint_members(joint):
        if obj.TypeId == "PartDesign::Boolean" and obj.Group:
            operand = obj.Group[0]
            src = operand if operand.TypeId == "PartDesign::Body" \
                else getattr(operand, "Source", None)
            if src is not None and hasattr(src, naming.PROP_COMPONENT_ROLE):
                obj.Label = naming.boolean_label(
                    getattr(src, naming.PROP_COMPONENT_ROLE), src.Label)
        elif obj.TypeId == "Part::Mirroring" and obj.Source is not None:
            obj.Label = naming.mirror_label(obj.Source.Label)
    return new_label


# --------------------------------------------------------------------------
# Saving and starting
# --------------------------------------------------------------------------

def save_as_template(doc, directory, kind, rename=True, overwrite=True):
    """Write `doc` into `directory` as a joint template; returns the
    path. `rename` relabels the joint VarSet and components to match
    the file name first. The document itself is not saved."""
    path = template_path(directory, kind)
    if path.exists() and not overwrite:
        raise TemplateError(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    if rename:
        relabel(doc, kind)
    doc.recompute()
    doc.saveCopy(str(path))
    return path


def new_from_starter(starter_path, directory, kind):
    """Copy a starter skeleton to a new template file, relabel it for
    `kind`, save it, and return (path, document) with the document open
    and ready to author in."""
    import FreeCAD as App
    starter_path = Path(starter_path)
    if not starter_path.is_file():
        raise TemplateError(f"starter template not found: {starter_path}")
    path = template_path(directory, kind)
    if path.exists():
        raise TemplateError(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(starter_path, path)
    active = App.ActiveDocument
    doc = App.openDocument(str(path))      # visible: it is opened to author in
    try:
        relabel(doc, kind)
        doc.recompute()
        doc.save()
    except Exception:
        App.closeDocument(doc.Name)
        restore_active(active)
        path.unlink(missing_ok=True)
        raise
    return path, doc
