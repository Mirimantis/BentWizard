"""The joint template library: where templates live, and how a user's
own joint gets into it.

Two directories are searched — the user's template folder (one
configurable path, remembered in FreeCAD's parameters) and the shipped
``library/`` that comes with the workbench. The user's folder wins on a
stem collision, so a locally revised copy of a shipped joint shadows the
shipped one instead of appearing twice.

Saving is ``Document.saveCopy``: the authoring document keeps its own
file name and its unmodified state, so "save as joint template" does not
quietly become "save as" — the user goes on editing the document they
were editing. Relabeling the joint VarSet is FreeCAD's rename, not an
expression rewrite: relabeling rebinds every ``<<Label>>`` reference in
the document (verified headless, August 2026), which is exactly what
makes the offer safe.

FreeCAD is imported lazily, inside the functions that need it, so the
discovery half stays usable from the linter's pure-Python context.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import naming
from .fcstd import FcstdDocument

SHIPPED_DIR = Path(__file__).resolve().parents[2] / "library"
PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/BentWizard"
USER_DIR_KEY = "TemplateDir"

# The serial every template's own joint VarSet carries. An applied joint
# gets a real serial; the template's is a placeholder, and 000 keeps it
# visibly out of the range Apply allocates.
TEMPLATE_SERIAL = "000"

TEMPLATE_SUFFIX = ".FCStd"
# Library file stems read 'Joint_<Kind>'; naming.kind_token_from_source
# strips the prefix back off, so the two round-trip.
STEM_PREFIX = naming.LEGACY_JOINT_PREFIX          # 'Joint_'


class TemplateError(ValueError):
    """A template save/create request that cannot be honored."""


# --------------------------------------------------------------------------
# Where templates live
# --------------------------------------------------------------------------

def default_user_dir():
    """<FreeCAD user app data>/BentWizard/library — beside the user's
    other FreeCAD data, so it survives an addon update."""
    import FreeCAD as App
    return Path(App.getUserAppDataDir()) / "BentWizard" / "library"


def user_dir():
    """The configured user template folder (never created here)."""
    import FreeCAD as App
    configured = App.ParamGet(PARAM_PATH).GetString(USER_DIR_KEY, "")
    return Path(configured) if configured else default_user_dir()


def set_user_dir(path):
    import FreeCAD as App
    App.ParamGet(PARAM_PATH).SetString(USER_DIR_KEY, str(Path(path)))


def search_dirs():
    """User folder first, shipped library second — the shadowing order.
    Both are returned whether or not they exist; callers that list files
    skip the missing ones, and callers that report to the user want to
    name the folder that is missing."""
    dirs = [user_dir(), SHIPPED_DIR]
    seen, out = set(), []
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _as_dirs(dirs):
    """Accept a single directory or an iterable of them — call sites
    that predate the search path pass one."""
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
    """The path a template stem resolves to, or None."""
    for name, path in templates(dirs):
        if name == stem:
            return path
    return None


def is_starter(path):
    """A jointless skeleton: two timbers, their frames and VarSets, and
    no joinery geometry at all.

    Structural rather than a declared flag — the property that matters
    is that there is nothing to inherit, and a boolean someone sets
    wrongly would hand an author exactly the phantom features finding
    #12 warns about. The two base stick pads are the only solid features
    a starter may carry.
    """
    try:
        doc = FcstdDocument.from_file(path)
    except Exception:
        return False
    solids = [o for o in doc.objects.values()
              if o.type_id.startswith("PartDesign::")
              and not o.is_type("PartDesign::Body")]
    if not solids:
        return False
    return all(o.is_type("PartDesign::Pad") for o in solids)


def starters(dirs=None):
    """[(stem, Path)] for every template fit to author a new joint from."""
    return [(stem, path) for stem, path in templates(dirs)
            if is_starter(path)]


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

def stem_for(kind):
    """'BraceMT' -> 'Joint_BraceMT'. A kind already carrying the prefix
    is left alone, so re-saving a template does not stutter."""
    kind = (kind or "").strip()
    if not kind:
        raise TemplateError("a template needs a joint kind (e.g. 'BraceMT')")
    bad = naming.reserved_in_label(kind)
    if bad:
        raise TemplateError(
            f"joint kind {kind!r} contains reserved character(s) "
            f"{bad!r} — they break <<Label>> expressions")
    if naming.kind_token_from_source(kind) != kind:
        return kind
    return f"{STEM_PREFIX}{kind}"


def template_path(directory, kind):
    return Path(directory) / (stem_for(kind) + TEMPLATE_SUFFIX)


def _joint_varset(doc):
    """The document's single joint VarSet, by label. Save-as runs on an
    authoring document the user is looking at, so the loud failure is
    the useful one."""
    joints = [o for o in doc.Objects
              if o.TypeId == "App::VarSet"
              and naming.parse_joint_label(o.Label)]
    if len(joints) != 1:
        raise TemplateError(
            f"expected exactly one joint VarSet labelled J-<Kind>-<serial>, "
            f"found {[o.Label for o in joints]} — a template holds one joint")
    return joints[0]


def _companion(doc, joint):
    for obj in doc.Objects:
        if obj.TypeId != "App::VarSet" or obj is joint:
            continue
        if getattr(obj, naming.VARSET_ROLE_PROP, None) \
                == naming.VARSET_ROLE_LAYOUT:
            return obj
    return None


def rename_needed(doc, kind, abbrev):
    """(joint label, companion label, abbrev) the document would take —
    or None if it already carries them. Drives the dialog's checkbox:
    an offer to change nothing is noise."""
    joint = _joint_varset(doc)
    want_joint = naming.joint_label(naming.kind_token_from_source(stem_for(kind)),
                                    TEMPLATE_SERIAL)
    want_layout = naming.layout_label(want_joint)
    companion = _companion(doc, joint)
    have_abbrev = getattr(joint, naming.TEMPLATE_ABBREV, "") or ""
    if (joint.Label == want_joint
            and (companion is None or companion.Label == want_layout)
            and (not abbrev or have_abbrev == abbrev)):
        return None
    return want_joint, want_layout, (abbrev or have_abbrev)


def _set_abbrev(joint, abbrev):
    if not hasattr(joint, naming.TEMPLATE_ABBREV):
        joint.addProperty(
            "App::PropertyString", naming.TEMPLATE_ABBREV,
            naming.TEMPLATE_META_GROUP,
            "Short kind token this template's feature labels carry "
            "(e.g. 'HMT') — Apply-Joint rewrites exactly this suffix.")
    setattr(joint, naming.TEMPLATE_ABBREV, abbrev)


def _retag_features(joint, old_suffix, new_suffix):
    """Rewrite the joint-token suffix on every feature label.

    The suffix is built from the joint label AND the abbrev, so changing
    either moves it. A feature left on the old suffix is a strict lint
    finding for a reason: Apply-Joint rewrites exactly this string, so a
    stale one reaches every applied model unchanged and two applications
    collide on the label.
    """
    from .apply_joint import joint_members
    if not old_suffix or old_suffix == new_suffix:
        return []
    renamed = []
    for obj in joint_members(joint):
        if obj is joint or obj.TypeId == "App::VarSet":
            continue
        if obj.Label.endswith(old_suffix):
            obj.Label = obj.Label[:-len(old_suffix)] + new_suffix
            renamed.append(obj.Label)
    return renamed


def relabel(doc, kind, abbrev):
    """Relabel the joint VarSet, its companion and every joint feature
    to match `kind`/`abbrev`. Returns the new joint label.

    No expression rewriting: FreeCAD rebinds every ``<<Label>>``
    reference in the document when an object is relabeled."""
    joint = _joint_varset(doc)
    old_suffix = naming.joint_suffix_for(
        joint.Label, getattr(joint, naming.TEMPLATE_ABBREV, None) or None)
    companion = _companion(doc, joint)

    new_label = naming.joint_label(
        naming.kind_token_from_source(stem_for(kind)), TEMPLATE_SERIAL)
    joint.Label = new_label
    if companion is not None:
        companion.Label = naming.layout_label(new_label)
    if abbrev:
        _set_abbrev(joint, abbrev)
    new_suffix = naming.joint_suffix_for(
        new_label, getattr(joint, naming.TEMPLATE_ABBREV, None) or None)
    _retag_features(joint, old_suffix, new_suffix)
    return new_label


# --------------------------------------------------------------------------
# Saving and starting
# --------------------------------------------------------------------------

def save_as_template(doc, directory, kind, abbrev=None, rename=True,
                     overwrite=True):
    """Write `doc` into `directory` as a joint template; returns the path.

    `rename` relabels the joint VarSet (and its companion, and every
    joint feature's suffix) to match the file name first — the file stem
    is what applied joints take their kind from, so a mismatch is a
    surprise waiting in a cut list. Declining leaves the document alone
    and the report flags it.

    The document itself is not saved: `saveCopy` writes the file without
    touching FileName or the modified flag.
    """
    path = template_path(directory, kind)
    if path.exists() and not overwrite:
        raise TemplateError(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    if rename:
        relabel(doc, kind, abbrev)
    elif abbrev:
        _set_abbrev(_joint_varset(doc), abbrev)
    doc.recompute()
    doc.saveCopy(str(path))
    return path


def new_from_starter(starter_path, directory, kind, abbrev=None):
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
    doc = App.openDocument(str(path))
    try:
        relabel(doc, kind, abbrev)
        doc.recompute()
        doc.save()
    except Exception:
        App.closeDocument(doc.Name)
        path.unlink(missing_ok=True)
        raise
    return path, doc
