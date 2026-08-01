"""Naming: permanent serial labels, separated from positional tags.

The adopted scheme gives every object two kinds of name:

- **Permanent identity — the Label.** Chosen at creation, descriptive of
  what the piece IS, never of where it stands. Labels are **permissive**
  (loosened July 2026 — since labels no longer carry position, the only
  constraints left are what the tooling needs): any characters except
  the reserved set below, ending in a separator + digit serial so the
  copy tools can bump it. ``T-<Role>[-<Qualifier>...]-<serial>``
  (``T-Post-Level1-003``) is the recommended style, dotted or spaced
  forms (``T-Post.Balcony.001``) equally valid. Joint instances (tool-
  generated): ``J-<Kind>-<serial>`` (``J-HousedMT-001``). Everything
  structural — VarSet ownership, feature labels, expressions, placement
  records — keys off the label, which is why it must never encode
  layout.
- **Position — Tier-2 data.** The ``Position_Tag`` property on the Dims
  and joint VarSets carries bent/bay/level info for layout drawings and
  lists. Nothing binds to it; reassign it freely as the layout evolves.

**Feature labels are descriptive-first** (reworked July 2026). A feature
inside a body reads ``<Descriptive>[.<TypeTag>].<Abbrev>.<serial>`` —
``TailSlope.Skt.WHD.001`` — putting the part you scan for at the front.
The earlier ``<TimberLabel>_<Feature>_<JointLabel>`` form buried it
between two long tokens and was never load-bearing: joint membership is
structural (the expression graph, see ``apply_joint.joint_members``) and
no expression ever targets a feature label. Only two things are needed:
the trailing joint token, so two applications of one template do not
collide, and — within a template — labels unique across both halves,
since the timber name no longer separates them. The ``<Abbrev>`` comes
from the template's ``Template_Abbrev`` property; frame ROLE is Tier-2
data in ``Frame_Role``, never a label substring.

The serial is the label's trailing run of digits when preceded by a
separator (``-``, ``.``, ``_``, or space). Suggestion helpers only ever
touch that segment, preserving the separator — digits glued to letters
in a descriptive part (``Level1``) are never rewritten (the retired
bent-number swap changed the FIRST number it found, which mangled
descriptive names).

Pure Python, no FreeCAD imports: shared by the cores, the GUI, and the
tests, and unit-testable under any interpreter.
"""

from __future__ import annotations

import re

TIMBER_PREFIX = "T-"
JOINT_PREFIX = "J-"
LEGACY_JOINT_PREFIX = "Joint_"
SERIAL_WIDTH = 3

# A timber's Dims VarSet label: '<prefix><timber label>'. Shortened from
# 'TimberDims_' (July 2026) — it is the longest thing in a body's tree
# row and the prefix is only a hint: both apply_joint.dims_varset and the
# linter resolve a body's Dims STRUCTURALLY, from the base pad's Length
# expression, so legacy-prefixed VarSets keep working untouched.
DIMS_PREFIX = "TDim_"
LEGACY_DIMS_PREFIX = "TimberDims_"
DIMS_PREFIXES = (DIMS_PREFIX, LEGACY_DIMS_PREFIX)

# Serial separator characters; SEPARATORS and _SEP_CLASS must stay in
# sync.
SEPARATORS = "-._ "
_SEP_CLASS = r"[-._ ]"
DEFAULT_SEP = "."
_SERIAL = re.compile(r"^(?P<base>.+?)(?P<sep>" + _SEP_CLASS + r")(?P<serial>\d+)$")

# Characters that break the tooling when they appear in a Label
# (verified against FreeCAD 1.1.1, everything else survives the
# <<Label>>.Prop expression round trip — including '.', ' ', quotes,
# '<', '<<' and unicode):
#   >        terminates <<Label>> quoting in expressions
#   \        the expression lexer's escape character
#   ;        the Placement_Record segment separator
#   newline  breaks the expression parser (and one-line records)
RESERVED_LABEL_CHARS = ">\\;\n\r"


def reserved_in_label(label):
    """The reserved characters present in `label`, as a sorted string
    (empty when the label is clean)."""
    return "".join(sorted({c for c in label if c in RESERVED_LABEL_CHARS}))


def dims_label(timber_label):
    """The Dims VarSet label for a timber: 'TDim_T.Joist.001'."""
    return f"{DIMS_PREFIX}{timber_label}"


def is_dims_label(label):
    """True for a Dims VarSet label under either prefix. A hint only —
    callers with a live document resolve Dims from the base pad."""
    return label.startswith(DIMS_PREFIXES)


def dims_owner(label):
    """The timber label a Dims VarSet label names, or None when the label
    carries neither prefix."""
    for prefix in DIMS_PREFIXES:
        if label.startswith(prefix):
            return label[len(prefix):]
    return None


def split_serial(label):
    """(base, serial) — serial is the trailing digit run when preceded
    by a separator (-, ., _, space), else None. 'T-Post-Level1-003' ->
    ('T-Post-Level1', '003'); 'T-Post.Balcony.001' -> ('T-Post.Balcony',
    '001'); 'T-Post-Level1' -> ('T-Post-Level1', None): the digit glued
    to 'Level' is part of the description, not a serial."""
    m = _SERIAL.match(label)
    if m is None:
        return (label, None)
    return (m.group("base"), m.group("serial"))


def next_serial(labels, base, width=SERIAL_WIDTH, taken=(), sep=None):
    """The next free '<base><sep>NNN' label given existing `labels` (and
    `taken`, serials already promised in the same batch).

    A trailing separator on `base` is taken as the separator, never
    doubled: 'T.Post.solarium.' means "append my next serial with a
    dot". When `sep` is not settled by the caller or a trailing
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
    serial. A label without a serial gets one appended ('T-Post-Level1'
    -> 'T-Post-Level1-001')."""
    m = _SERIAL.match(label)
    if m is None:
        return next_serial(labels, label, taken=taken)
    return next_serial(labels, m.group("base"), width=len(m.group("serial")),
                       taken=taken, sep=m.group("sep"))


def is_joint_varset_label(label):
    """True for a joint-instance VarSet label, either scheme
    ('J-HousedMT-001' or legacy 'Joint_MT_B2a')."""
    return label.startswith((JOINT_PREFIX, LEGACY_JOINT_PREFIX))


def parse_joint_label(label):
    """(kind, joint_id) from a joint VarSet label of either scheme, or
    None when the label carries no parsable kind/id."""
    if label.startswith(JOINT_PREFIX):
        rest = label[len(JOINT_PREFIX):]
        if "-" in rest:
            kind, jid = rest.rsplit("-", 1)
            if kind and jid:
                return (kind, jid)
        return None
    if label.startswith(LEGACY_JOINT_PREFIX):
        parts = label.split("_")
        if len(parts) >= 3 and all(parts[1:]):
            return ("_".join(parts[1:-1]), parts[-1])
    return None


def joint_label(kind_token, joint_id):
    """The label for a new joint instance: 'J-<Kind>-<ID>'."""
    return f"{JOINT_PREFIX}{kind_token}-{joint_id}"


def member_suffix(joint_label):
    """The suffix a joint's feature labels carry inside timber bodies.

    '_J-HousedMT-001' under the current scheme; '_MT_0a' for a legacy
    'Joint_MT_0a' VarSet. Apply-Joint rewrites exactly this string when
    it clones a template, so a template feature whose label lacks the
    suffix keeps its template name in every document it is applied to.
    None when the joint label carries no parsable kind/id.
    """
    if joint_label.startswith(JOINT_PREFIX):
        return f"_{joint_label}"
    parsed = parse_joint_label(joint_label)
    if parsed is None:
        return None
    return f"_{parsed[0]}_{parsed[1]}"


# --------------------------------------------------------------------------
# Feature labels inside bodies
# --------------------------------------------------------------------------

# Type tag appended to a feature's descriptive name. The CUT is bare —
# 'Housing', 'TailSlope' — because it is the thing the carpenter names;
# the sketch and datums that produce it are tagged so they can share the
# descriptive word without colliding. Longest TypeId prefix wins.
TYPE_TAGS = {
    "Sketcher::SketchObject": "Skt",
    "Part::LocalCoordinateSystem": "Lcs",
    "Part::DatumPlane": "Dtm",
    "Part::DatumLine": "Dln",
    "Part::DatumPoint": "Dpt",
}

# Tier-2 marker naming a joint frame's role. Read by Preview, Assemble,
# Duplicate and the end-B seat flip — behavior NEVER keys off the label
# (the retired 'JointFrame'/'MateFrame' substring match failed silently
# when a template author renamed a frame).
FRAME_ROLE_PROP = "Frame_Role"
FRAME_ROLE_LANDING = "Landing"
FRAME_ROLE_MATE = "Mate"
FRAME_ROLES = (FRAME_ROLE_LANDING, FRAME_ROLE_MATE)

# Legacy frame-role detection, for documents built before Frame_Role.
LEGACY_FRAME_TOKENS = {"MateFrame": FRAME_ROLE_MATE,
                       "JointFrame": FRAME_ROLE_LANDING}

# Tier-2 marker naming a VarSet's role within a joint template. Same
# discipline as Frame_Role: a template declares the companion, tools
# read the property, and nothing keys off the label — a renamed
# companion must still resolve.
VARSET_ROLE_PROP = "VarSet_Role"
VARSET_ROLE_LAYOUT = "Layout"

# The companion layout VarSet a joint template may declare (roadmap:
# Parametric layout). It holds the length-consuming parameters
# authoritatively plus the derived Stick_Allowance, and is a PURE
# SOURCE: the joint VarSet consumes from it, never the reverse, which
# is what keeps a grid-driven Dims.Length out of a dependency cycle.
LAYOUT_PREFIX = "Layout_"

# What a companion publishes, one per layout basis. Both are measured
# along the ENTERING timber's own axis, which is what keeps the
# arithmetic angle-blind:
#   O.C.  — past the landing timber's CENTERLINE (tenon + housing - ddim/2)
#   F.T.F.— past the landing timber's FACE      (tenon + housing)
# The half-thickness between them is published too, because it is the
# conversion term: OC = FTF + sum(Grid_Setback).
STICK_ALLOWANCE_OC = "Stick_Allowance_OC"
STICK_ALLOWANCE_FTF = "Stick_Allowance_FTF"
GRID_SETBACK_PROP = "Grid_Setback"

# Layout bases. The basis belongs to the DISTANCE, not to the tool: a
# variable is an on-center number or a clear-span number for good, so
# there is no mode for a user to set wrongly. Which allowance a
# driven Length sums IS the basis, so it reads back structurally.
BASIS_OC = "OC"
BASIS_FTF = "FTF"
BASES = (BASIS_OC, BASIS_FTF)
ALLOWANCE_FOR_BASIS = {BASIS_OC: STICK_ALLOWANCE_OC,
                       BASIS_FTF: STICK_ALLOWANCE_FTF}
BASIS_SUFFIX = {BASIS_OC: "_Dist_OC", BASIS_FTF: "_Dist_FTF"}
BASIS_LABEL = {BASIS_OC: "O.C. (On-Center)",
               BASIS_FTF: "Clear span (Face-to-Face)"}


def basis_from_name(prop_name):
    """The layout basis a distance variable's name advertises, or None.

    Advisory only — a nudge for the dialog's default. What a driven
    Length actually uses is read from its expression, never from a name.
    """
    for basis, suffix in BASIS_SUFFIX.items():
        if prop_name.endswith(suffix):
            return basis
    return None


def layout_label(joint_label_):
    """The companion layout VarSet's label for a joint: kind_owner, the
    owner being the joint itself ('Layout_J-HousedMT-001')."""
    return f"{LAYOUT_PREFIX}{joint_label_}"


def is_layout_varset_label(label):
    """True for a companion layout VarSet label. Advisory only — every
    tool resolves the companion through VarSet_Role, never this."""
    return label.startswith(LAYOUT_PREFIX)


def layout_owner(label):
    """The joint label a companion layout VarSet belongs to, or None."""
    if not is_layout_varset_label(label):
        return None
    owner = label[len(LAYOUT_PREFIX):]
    return owner or None


def base_feature_label(descriptive, type_id, timber_label):
    """A timber's own base feature, qualified by its timber:
    'Section.Skt.T.Joist.003', 'Stick.T.Joist.003'.

    Same shape as a joint feature — descriptive name, type tag,
    qualifier — with the owning timber standing in for the joint token.
    The timber IS needed here, unlike on joint features: FreeCAD forces
    unique labels (DuplicateLabels defaults false), so an unqualified
    'Stick' on every timber collects an auto-counter ('Stick001',
    'Stick002') whose digits read like a serial but are FreeCAD's own.
    """
    return feature_label(descriptive, type_id, f".{timber_label}")


def section_sketch_label(timber_label):
    """The label for a timber's section sketch."""
    return base_feature_label("Section", "Sketcher::SketchObject",
                              timber_label)


def stick_label(timber_label):
    """The label for a timber's full-length pad."""
    return base_feature_label("Stick", "PartDesign::Pad", timber_label)


def type_tag(type_id):
    """The feature label's type tag for `type_id`, or None when the type
    is a cut (pocket, pad, hole, groove) and carries no tag."""
    for prefix, tag in TYPE_TAGS.items():
        if type_id.startswith(prefix):
            return tag
    return None


def legacy_frame_role(label):
    """The frame role a pre-Frame_Role label implies, or None. 'MateFrame'
    is tested first: it is the more specific token."""
    for token, role in LEGACY_FRAME_TOKENS.items():
        if token in label:
            return role
    return None


def joint_suffix(abbrev, serial):
    """The trailing joint token a feature label carries: '.WHD.001'."""
    return f".{abbrev}.{serial}"


def joint_suffix_for(label, abbrev):
    """The feature-label suffix for the joint instance `label`, whose
    template declared `abbrev` (its Template_Abbrev).

    'J-WedgedHalfDovetail-001' + 'WHD' -> '.WHD.001'. Apply-Joint rewrites
    exactly this string when it clones a template, so a template feature
    whose label lacks the suffix keeps its TEMPLATE name in every document
    it is applied to. Without an abbrev — a template predating
    Template_Abbrev — falls back to the long `member_suffix` form, which
    still round-trips correctly, just verbosely.
    """
    parsed = parse_joint_label(label)
    if abbrev and parsed is not None:
        return joint_suffix(abbrev, parsed[1])
    return member_suffix(label)


def feature_label(descriptive, type_id, suffix):
    """A feature's full label: descriptive name, type tag, joint token.
    'TailSlope' + a sketch + '.WHD.001' -> 'TailSlope.Skt.WHD.001'."""
    tag = type_tag(type_id)
    return f"{descriptive}{'.' + tag if tag else ''}{suffix}"


TEMPLATE_META_PREFIX = "Template_"
TEMPLATE_META_GROUP = "Template"
TEMPLATE_ABBREV = "Template_Abbrev"


def is_template_metadata(name, group=None):
    """True for a joint VarSet property that describes the TEMPLATE
    rather than the joint instance (the Handed flag, the declared angle
    range). Name-keyed on the 'Template_' prefix — property groups are
    author-controlled and drift, so the name is the contract; the
    'Template' group is honored too, and the roadmap's bare 'Handed'
    stays recognized."""
    return (name.startswith(TEMPLATE_META_PREFIX)
            or name == "Handed"
            or (group or "") == TEMPLATE_META_GROUP)


def kind_token_from_source(source_name):
    """The descriptive kind token from a template's file stem:
    'Joint_HousedMT' -> 'HousedMT' (a 'J-' prefix is stripped too, for
    templates saved under the new scheme)."""
    for prefix in (LEGACY_JOINT_PREFIX, JOINT_PREFIX):
        if source_name.startswith(prefix):
            return source_name[len(prefix):]
    return source_name
