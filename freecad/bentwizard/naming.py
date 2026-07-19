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


def kind_token_from_source(source_name):
    """The descriptive kind token from a template's file stem:
    'Joint_HousedMT' -> 'HousedMT' (a 'J-' prefix is stripped too, for
    templates saved under the new scheme)."""
    for prefix in (LEGACY_JOINT_PREFIX, JOINT_PREFIX):
        if source_name.startswith(prefix):
            return source_name[len(prefix):]
    return source_name
