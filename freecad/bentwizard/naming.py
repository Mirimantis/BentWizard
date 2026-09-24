"""Naming: permanent serial labels, Tier-2 property names, feature labels.

Every object has two kinds of name:

- **Permanent identity — the Label.** Chosen at creation, descriptive of
  what the piece IS, never of where it stands. Labels are **permissive**:
  any characters except the reserved set below, ending in a separator +
  digit serial so the copy tools can bump it. ``T-<Role>[-<Qualifier>...]
  -<serial>`` (``T-Post-Level1-003``) is the recommended style; dotted or
  spaced forms (``T-Post.Balcony.001``) are equally valid. Joint
  instances (tool-generated): ``J-<Kind>-<serial>`` (``J-HousedMT-001``);
  a template's own joint VarSet is ``J-<Kind>-000``.
- **Position — Tier-2 data.** The ``PositionTag`` property on the Dims
  and joint VarSets carries bent/bay/level info for drawings and lists.
  Nothing binds to it.

**Property names are UpperCamelCase**, FreeCAD's own convention, with no
separators (``MortiseThickness``, ``HousingDepth``, ``WidthX``). The
Property View inserts display spaces itself. Labels are exempt.

**Datum labels** read ``D_<timber>_A`` / ``D_<timber>_B`` for the end
datums and ``D_<timber>_<Face>_<serial>`` for a face datum
(``D_T-Post-001_YPos_001``). The word is *datum*, never *frame* — to a
framer a frame is a structure made of wood.

**Component labels** — the cutter and adder Bodies a joint template
carries — read ``<Descriptive>.<Kind>.<serial>`` (``Mortise.HousedMT.001``),
the joint's own serial trailing so two applications of one template
never collide. The Boolean that applies one is ``Cut.<component>`` /
``Fuse.<component>``, a mirrored copy's mirroring ``Mirror.<component>``.

The serial is the label's trailing run of digits when preceded by a
separator (``-``, ``.``, ``_``, or space). Suggestion helpers only ever
touch that segment, preserving the separator — digits glued to letters
in a descriptive part (``Level1``) are never rewritten.

Pure Python, no FreeCAD imports: shared by the cores, the GUI, and the
tests, and unit-testable under any interpreter.
"""

from __future__ import annotations

import re

TIMBER_PREFIX = "T-"
JOINT_PREFIX = "J-"
SERIAL_WIDTH = 3
TEMPLATE_SERIAL = "000"      # a template's own joint serial

# A timber's Dims VarSet label: '<prefix><timber label>'. The prefix is
# only a hint: tools resolve a body's Dims STRUCTURALLY, from the base
# pad's LengthZ expression (timber.dims_varset).
DIMS_PREFIX = "TDim_"

# Serial separator characters; SEPARATORS and _SEP_CLASS must stay in
# sync.
SEPARATORS = "-._ "
_SEP_CLASS = r"[-._ ]"
DEFAULT_SEP = "."
_SERIAL = re.compile(r"^(?P<base>.+?)(?P<sep>" + _SEP_CLASS + r")(?P<serial>\d+)$")

# Characters that break the tooling when they appear in a Label
# (verified against FreeCAD 1.1.1 and 26.3, everything else survives the
# <<Label>>.Prop expression round trip — including '.', ' ', quotes,
# '<', '<<' and unicode):
#   >        terminates <<Label>> quoting in expressions
#   \        the expression lexer's escape character
#   ;        a record separator in Tier-2 strings
#   newline  breaks the expression parser
RESERVED_LABEL_CHARS = ">\\;\n\r"

# --------------------------------------------------------------------------
# <<Label>> references as FreeCAD stores them
# --------------------------------------------------------------------------
# FreeCAD evaluates `<<T-Post'1'>>.Len` as typed, but STORES it the way
# its own App::quote writes a label: a backslash before a quote, '\',
# '>', and tab/newline/CR as \t \n \r. So `<<T-Post\'1\'>>.Len` is what
# ExpressionEngine and Document.xml hold (sweep finding 18). Anything that
# looks for a reference in stored text goes through these three — never
# `f"<<{label}>>" in expr`. Building an expression may use the plain
# label: the parser takes both forms and stores the escaped one.

_QUOTE_ESCAPES = {"\\": "\\\\", "'": "\\'", '"': '\\"', ">": "\\>",
                  "\t": "\\t", "\n": "\\n", "\r": "\\r"}
_UNQUOTE = {"t": "\t", "n": "\n", "r": "\r"}

# One stored reference: '<<', then escaped characters or anything but
# '\' and '>', then '>>'. Group 1 is the label as stored (escaped).
LABEL_REF = re.compile(r"<<((?:\\.|[^\\>])+)>>")


def quote_label(label):
    """A label escaped as FreeCAD stores it between '<<' and '>>' — for
    templates that already carry the brackets (facetable's rows)."""
    return "".join(_QUOTE_ESCAPES.get(c, c) for c in label)


def label_ref(label):
    """'<<Label>>' exactly as FreeCAD stores it in an expression."""
    return "<<" + quote_label(label) + ">>"


def unquote_label(stored):
    """The label behind LABEL_REF's group 1 (the inverse of label_ref)."""
    return re.sub(r"\\(.)", lambda m: _UNQUOTE.get(m.group(1), m.group(1)),
                  stored, flags=re.DOTALL)


def referenced_labels(expr):
    """Every label an expression names in the <<Label>> form."""
    return {unquote_label(m) for m in LABEL_REF.findall(expr or "")}

# --------------------------------------------------------------------------
# Tier-2 property names (UpperCamelCase, FreeCAD convention)
# --------------------------------------------------------------------------

# Dims VarSet
DIMS = ("WidthX", "WidthY", "LengthZ")
PROP_POSITION_TAG = "PositionTag"

# Datum (an LCS owned by a timber)
DATUM_GROUP = "Datum"
PROP_FACE = "Face"               # XPos / XNeg / YPos / YNeg / EndA / EndB
PROP_STATION = "Station"         # along the host, drives Placement.z
PROP_MATE_DATUM = "MateDatum"    # internal Name of the paired datum
PROP_JOINT = "Joint"             # internal Name of the joint VarSet
ACCESSORS = ("WidthU", "WidthV", "DepthW")
# The joint VarSet's placement accessors (HostPlacement / MatePlacement):
# a component Body binds its Placement to one of these, never to a
# datum's Placement directly. FreeCAD resolves a datum's child axes and
# planes to the FIRST GeoFeatureGroup in the datum's in-list, without
# checking membership; a component Body reading the datum can come
# before the owning timber and the datum then fails its scope check on
# recompute ("Link(s) ... go out of the allowed scope").
PLACEMENT_ACCESSOR = "Placement"
ALL_ACCESSORS = ACCESSORS + (PLACEMENT_ACCESSOR,)

# The accessors live on a VarSet of their own, one per joint, labelled
# `Accessors_<joint label>` and filed under the joint's handle — the same
# shape as `Seat_<joint label>`. The joint VarSet then holds only what a
# framer edits. They exist for the scope rule above, not for tidiness: a
# VarSet reads the datums and components read the VarSet.
#
# A TEMPLATE keeps them on its own joint VarSet (one object, and every
# template already saved on disk stays valid); Apply expands them onto a
# separate VarSet as it copies. Both shapes are therefore live, and
# `datums.accessors_varset` resolves whichever a joint has rather than
# anything being configured.
ACCESSORS_PREFIX = "Accessors_"
ACCESSOR_GROUP = "Accessors"
SIDES = ("Host", "Mate")
# Which datum is the host, recorded rather than inferred. The old
# inference read it back out of the HostWidthU expression, which stops
# working the moment that expression lives on another object.
PROP_HOST_DATUM = "HostDatum"    # internal Name of the host datum
# The accessor VarSet, by internal Name — the same reason datums carry
# `Joint` and `MateDatum` as Names: a label is the framer's to change,
# a Name never changes. Finding it by `Accessors_<joint label>` alone
# broke the moment a joint VarSet was renamed in the tree: false strict
# lint findings on a sound joint, and Remove left the accessors behind.
PROP_ACCESSORS = "Accessors"     # internal Name of the accessor VarSet


def accessors_label(joint_label):
    """'J-HousedMT-001' -> 'Accessors_J-HousedMT-001'."""
    return f"{ACCESSORS_PREFIX}{joint_label}"
JOINT_GROUP = "Joint"            # the template author's parameters

# Component Body (a cutter or adder in a joint template)
COMPONENT_GROUP = "Component"
PROP_COMPONENT_ROLE = "ComponentRole"
COMPONENT_CUTTER = "Cutter"
COMPONENT_ADDER = "Adder"
COMPONENT_ROLES = (COMPONENT_CUTTER, COMPONENT_ADDER)
PROP_COMPONENT_ORDER = "ComponentOrder"
BOOLEAN_OP = {COMPONENT_CUTTER: "Cut", COMPONENT_ADDER: "Fuse"}

# Template metadata on a joint VarSet
TEMPLATE_META_PREFIX = "Template"
TEMPLATE_META_GROUP = "Template"
PROP_TEMPLATE_SOURCE = "TemplateSource"
RANGES_GROUP = "Ranges"
RANGE_MIN_SUFFIX = "Min"
RANGE_MAX_SUFFIX = "Max"
PROP_SWEEP_FINDINGS = "SweepFindings"
# Bool in the Template group. False: the joint looks the same from either
# side, so Apply never mirrors it. True, or absent (a template predating
# the flag): Apply mirrors a component on a datum of the other parity.
PROP_TEMPLATE_HANDED = "Handed"

_CAMEL = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def is_camel_case(name):
    """True for an UpperCamelCase property name with no separators."""
    return bool(_CAMEL.match(name))


# UpperCamelCase names FreeCAD's expression lexer reads as a unit or a
# constant, so a property with one of these names can never be
# referenced: `<<J-Kind-001>>.W` is a parse error, because W is the watt.
# They are the lexer's own tokens (src/App/Expression.l): 34 unit
# symbols, M and AS (arcminute and arcsecond), and True/False/None.
# Each one was confirmed to fail as a VarSet property reference on
# 1.1.3 and 26.3 (sweep finding 17). 'Nmm' is in the lexer too, but it
# resolves as a property, so it is not listed. test_naming pins this
# list against the engine.
EXPRESSION_WORDS = frozenset(
    "A AS C CV F False G GHz GPa H Hz J K M MA MHz MN MOhm MPa MS MeV Mpsi "
    "N Nm None Ohm Pa S T THz Torr True V VA VAs W Wb Ws".split())


def is_expression_word(name):
    """True when `name` is one FreeCAD reads as a unit or a constant, so
    a property with that name cannot be referenced in an expression."""
    return name in EXPRESSION_WORDS


def reserved_in_label(label):
    """The reserved characters present in `label`, as a sorted string
    (empty when the label is clean)."""
    return "".join(sorted({c for c in label if c in RESERVED_LABEL_CHARS}))


# --------------------------------------------------------------------------
# Timber labels
# --------------------------------------------------------------------------

def dims_label(timber_label):
    """The Dims VarSet label for a timber: 'TDim_T.Joist.001'."""
    return f"{DIMS_PREFIX}{timber_label}"


def is_dims_label(label):
    """True for a Dims VarSet label. A hint only — callers with a live
    document resolve Dims from the base pad."""
    return label.startswith(DIMS_PREFIX)


def dims_owner(label):
    """The timber label a Dims VarSet label names, or None."""
    if label.startswith(DIMS_PREFIX):
        return label[len(DIMS_PREFIX):]
    return None


def split_serial(label):
    """(base, serial) — serial is the trailing digit run when preceded
    by a separator (-, ., _, space), else None. 'T-Post-Level1-003' ->
    ('T-Post-Level1', '003'); 'T-Post-Level1' -> ('T-Post-Level1', None):
    the digit glued to 'Level' is part of the description."""
    m = _SERIAL.match(label)
    if m is None:
        return (label, None)
    return (m.group("base"), m.group("serial"))


def next_serial(labels, base, width=SERIAL_WIDTH, taken=(), sep=None):
    """The next free '<base><sep>NNN' label given existing `labels` (and
    `taken`, serials already promised in the same batch).

    A trailing separator on `base` is taken as the separator, never
    doubled. When `sep` is not settled by the caller or a trailing
    separator, it is inferred: the family's own separator (from its
    highest-serial member), else the last separator character in the
    base ('T-Post' stays hyphenated), else DEFAULT_SEP ('.'). The scan
    counts the family across any separator so mixed-separator siblings
    never collide on a serial."""
    if base and base[-1] in SEPARATORS:
        if sep is None:
            sep = base[-1]
        base = base[:-1]
    used, seps_seen = set(), {}
    pat = re.compile(re.escape(base) + "(" + _SEP_CLASS + r")(\d+)$")
    for label in list(labels) + list(taken):
        m = pat.match(label)
        if m:
            n = int(m.group(2))
            used.add(n)
            seps_seen[n] = m.group(1)
    if sep is None:
        if used:
            sep = seps_seen[max(used)]
        else:
            sep = next((c for c in reversed(base) if c in SEPARATORS),
                       DEFAULT_SEP)
    n = (max(used) + 1) if used else 1
    return f"{base}{sep}{n:0{max(width, len(str(n)))}d}"


def successor_label(labels, label, taken=()):
    """A copy-name for `label`: same base, same separator, next free
    serial. A label without a serial gets one appended."""
    m = _SERIAL.match(label)
    if m is None:
        return next_serial(labels, label, taken=taken)
    return next_serial(labels, m.group("base"), width=len(m.group("serial")),
                       taken=taken, sep=m.group("sep"))


# --------------------------------------------------------------------------
# Joint labels
# --------------------------------------------------------------------------

def is_joint_varset_label(label):
    """True for a joint VarSet label ('J-HousedMT-001')."""
    return label.startswith(JOINT_PREFIX) and parse_joint_label(label) is not None


def parse_joint_label(label):
    """(kind, serial) from 'J-<Kind>-<serial>', or None."""
    if not label.startswith(JOINT_PREFIX):
        return None
    rest = label[len(JOINT_PREFIX):]
    if "-" not in rest:
        return None
    kind, serial = rest.rsplit("-", 1)
    if kind and serial:
        return (kind, serial)
    return None


def joint_label(kind, serial):
    """The label for a joint VarSet: 'J-<Kind>-<serial>'."""
    return f"{JOINT_PREFIX}{kind}-{serial}"


def template_kind_from_stem(stem):
    """The joint kind a template's file stem names: 'Joint_HousedMT' ->
    'HousedMT'. The stem IS the kind; the joint VarSet's label follows it."""
    for prefix in ("Joint_", JOINT_PREFIX):
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


def template_stem(kind):
    """The file stem for a joint kind: 'HousedMT' -> 'Joint_HousedMT'."""
    return kind if kind.startswith("Joint_") else f"Joint_{kind}"


def is_template_metadata(name, group=None):
    """True for a joint VarSet property describing the TEMPLATE rather
    than the joint instance (TemplateSource, ...). Name-keyed on the
    'Template' prefix; the 'Template' group is honored too."""
    return (name.startswith(TEMPLATE_META_PREFIX)
            or (group or "") == TEMPLATE_META_GROUP)


def is_accessor_property(name):
    """True for a cross-timber accessor (HostWidthU ...) or the pairing
    record beside it — tool-written, never user-edited, and never a
    joint parameter."""
    return (name in (PROP_HOST_DATUM, PROP_ACCESSORS)
            or any(name == side + acc
                   for side in SIDES for acc in ALL_ACCESSORS))


def is_accessors_label(label):
    """True for an accessor VarSet's label."""
    return str(label).startswith(ACCESSORS_PREFIX)


def placement_accessor(side):
    """'HostPlacement' / 'MatePlacement'."""
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, got {side!r}")
    return side + PLACEMENT_ACCESSOR


def is_range_property(name, group=None):
    """True for a declared range bound ('TenonLengthMin') — the 'Ranges'
    group, or the Min/Max suffix."""
    return ((group or "") == RANGES_GROUP
            or name.endswith((RANGE_MIN_SUFFIX, RANGE_MAX_SUFFIX)))


def range_base(name):
    """'TenonLengthMin' -> ('TenonLength', 'Min'); None when not a bound."""
    for suffix in (RANGE_MIN_SUFFIX, RANGE_MAX_SUFFIX):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)], suffix
    return None


# --------------------------------------------------------------------------
# Datum labels
# --------------------------------------------------------------------------

END_SUFFIX = {"EndA": "A", "EndB": "B"}


def datum_label(timber_label, face, serial=None):
    """'D_<timber>_A' / 'D_<timber>_B' for an end datum, else
    'D_<timber>_<Face>_<serial>' ('D_T-Post-001_YPos_001')."""
    if face in END_SUFFIX:
        return f"D_{timber_label}_{END_SUFFIX[face]}"
    return f"D_{timber_label}_{face}_{serial or '001'}"


def object_name(label):
    """A readable internal Name for `label`: FreeCAD accepts letters,
    digits and underscores, so everything else becomes '_'."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", label)
    if not name or name[0].isdigit():
        name = "_" + name
    return name


# --------------------------------------------------------------------------
# Feature and component labels inside bodies
# --------------------------------------------------------------------------

# Type tag appended to a timber base feature's descriptive name.
TYPE_TAGS = {
    "Sketcher::SketchObject": "Skt",
    "Part::LocalCoordinateSystem": "Lcs",
    "Part::DatumPlane": "Dtm",
    "Part::DatumLine": "Dln",
    "Part::DatumPoint": "Dpt",
}

_COMPONENT = re.compile(r"^(?P<desc>.+)\.(?P<kind>[^.]+)\.(?P<serial>\d+)$")


def type_tag(type_id):
    """The feature label's type tag for `type_id`, or None when the type
    is a solid feature (pad, pocket, boolean) and carries no tag."""
    for prefix, tag in TYPE_TAGS.items():
        if type_id.startswith(prefix):
            return tag
    return None


def feature_label(descriptive, type_id, suffix):
    """'Section' + a sketch + '.T-Post-001' -> 'Section.Skt.T-Post-001'."""
    tag = type_tag(type_id)
    return f"{descriptive}{'.' + tag if tag else ''}{suffix}"


def base_feature_label(descriptive, type_id, timber_label):
    """A timber's own base feature, qualified by its timber:
    'Section.Skt.T.Joist.003', 'Stick.T.Joist.003'. FreeCAD forces unique
    labels, so an unqualified 'Stick' on every timber would collect an
    auto-counter whose digits read like a serial but are FreeCAD's own."""
    return feature_label(descriptive, type_id, f".{timber_label}")


def section_sketch_label(timber_label):
    return base_feature_label("Section", "Sketcher::SketchObject", timber_label)


def stick_label(timber_label):
    return base_feature_label("Stick", "PartDesign::Pad", timber_label)


def component_label(descriptive, kind, serial):
    """'Mortise' + 'HousedMT' + '001' -> 'Mortise.HousedMT.001'."""
    return f"{descriptive}.{kind}.{serial}"


def parse_component_label(label):
    """('Mortise', 'HousedMT', '001') from 'Mortise.HousedMT.001', or None."""
    m = _COMPONENT.match(label)
    if m is None:
        return None
    return (m.group("desc"), m.group("kind"), m.group("serial"))


def retag_component_label(label, kind, serial):
    """Rewrite the kind and serial of a component label, keeping the
    descriptive part; a label without the pattern gets them appended."""
    parsed = parse_component_label(label)
    desc = parsed[0] if parsed else label
    return component_label(desc, kind, serial)


def boolean_label(component_role, comp_label):
    """'Cut.Mortise.HousedMT.001' / 'Fuse.Tenon.HousedMT.001'."""
    return f"{BOOLEAN_OP[component_role]}.{comp_label}"


def mirror_label(comp_label):
    return f"Mirror.{comp_label}"
