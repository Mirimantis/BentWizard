"""Naming: permanent serial labels, separated from positional tags.

The adopted scheme gives every object two kinds of name:

- **Permanent identity — the Label.** Chosen at creation, descriptive of
  what the piece IS, never of where it stands. Timbers:
  ``T-<Role>[-<Qualifier>...]-<serial>`` (``T-Post-Level1-003``,
  ``T-TieBeam_decorative-007``). Joint instances: ``J-<Kind>-<serial>``
  (``J-HousedMT-001``). Everything structural — VarSet ownership,
  feature labels, expressions, placement records — keys off the label,
  which is why it must never encode layout.
- **Position — Tier-2 data.** The ``Position_Tag`` property on the Dims
  and joint VarSets carries bent/bay/level info for layout drawings and
  lists. Nothing binds to it; reassign it freely as the layout evolves.

The serial is the label's final ``-``-separated segment when that
segment is all digits. Suggestion helpers only ever touch that segment —
digits inside a descriptive part (``Level1``) are never rewritten (the
retired bent-number swap changed the FIRST number it found, which
mangled descriptive names).

Pure Python, no FreeCAD imports: shared by the cores, the GUI, and the
tests, and unit-testable under any interpreter.
"""

from __future__ import annotations

import re

TIMBER_PREFIX = "T-"
JOINT_PREFIX = "J-"
LEGACY_JOINT_PREFIX = "Joint_"
SERIAL_WIDTH = 3

_SERIAL = re.compile(r"^(?P<base>.+)-(?P<serial>\d+)$")


def split_serial(label):
    """(base, serial) — serial is the final '-'-separated segment when it
    is all digits, else None. 'T-Post-Level1-003' -> ('T-Post-Level1',
    '003'); 'T-Post-Level1' -> ('T-Post-Level1', None): the digit inside
    'Level1' is part of the description, not a serial."""
    m = _SERIAL.match(label)
    if m is None:
        return (label, None)
    return (m.group("base"), m.group("serial"))


def next_serial(labels, base, width=SERIAL_WIDTH, taken=()):
    """The next free '<base>-NNN' label given existing `labels` (and
    `taken`, serials already promised in the same batch)."""
    used = set()
    pat = re.compile(re.escape(base) + r"-(\d+)$")
    for label in list(labels) + list(taken):
        m = pat.match(label)
        if m:
            used.add(int(m.group(1)))
    n = (max(used) + 1) if used else 1
    return f"{base}-{n:0{max(width, len(str(n)))}d}"


def successor_label(labels, label, taken=()):
    """A copy-name for `label`: same base, next free serial. A label
    without a serial gets one appended ('T-Post-Level1' ->
    'T-Post-Level1-001')."""
    base, serial = split_serial(label)
    if serial is None:
        return next_serial(labels, label, taken=taken)
    return next_serial(labels, base, width=len(serial), taken=taken)


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
