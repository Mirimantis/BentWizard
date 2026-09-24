"""The flat frame — every timber seated by expression, no Assembly object.

A frame is an ordinary Std Group holding bent and bay Std Groups. There
is no ``Assembly::AssemblyObject``, no Fixed joint and no solver: every
timber except the frame's anchor is placed by an EXPRESSION, so a
parameter edit is a plain recompute. Measured against the solver it
replaces: exact to ~1e-11 mm at 20 bents, where the solver returned a
wrong answer at 4 and failed outright at 5 (docs/spike-flat-frame-results).

Which joint places which timber is the PLACEMENT TREE. The timber joint
that first connects a timber is its *placing joint*; it carries a
``Seat_J-...`` VarSet whose ``SeatPlacement`` computes

    anchor.Placement * near.Placement * FLIP * minvert(far.Placement)

— the same seat ``datums.seat_delta`` computes, written where FreeCAD
recomputes it. ``near`` is the datum on the timber already placed,
``far`` the datum on the one being placed, and FLIP is 180 deg about the
datum's local Y (its own inverse). The placed timber's ``Placement``
reads that property.

The seat cannot live on the joint VarSet: FreeCAD's dependency graph is
per object, and the joint's component bodies already read that VarSet,
so having it read a timber's Placement is a cycle. It nests under the
joint's handle instead, beside the parameter VarSet — deleting a handle
must stay harmless to geometry, and a nested VarSet survives one.

Placing joints form a spanning tree rooted at the *anchor*, whose
Placement is bound to ``FrameOrigin`` on the project VarSet: an
expression-driven value cannot be dragged or typed over, and moving the
whole frame is one edit.

Two joints do not place anything. A joint whose timbers are already
placed **in the same component** closes a loop: it places nothing and the
misfit check verifies it still closes. A joint connecting **different
components** merges them — the seats between the joined timber and its
own root are reversed (a seat is symmetric: swap near and far, re-point
the Placement binding, and "J places X from Y" becomes "J places Y from
X"), then it is seated from the other side. Its whole component follows
rigidly, because its internal seats are all relative. That is what makes
"tie these two bents together" bring them together whatever order the
framer worked in.

**The placement tree is not the load path.** It follows build order. The
structural graph (Phase 4) derives from ALL timber joints plus roles,
bearing faces and supports; nothing structural may read this tree.

Tier 1 throughout: Std Groups, VarSets and expressions are stock
FreeCAD. Uninstall the workbench and the frame still opens, edits and
recomputes.
"""

from __future__ import annotations

from collections import namedtuple

import FreeCAD as App

from . import datums, joint_handle, naming
from .apply import JointError, bent_joints, joint_datums
from .timber import dims_varset

# Agreement thresholds. Expression seating is exact to ~1e-11 mm, so
# anything past these means two timber joints place a timber
# inconsistently — a loop that does not close.
MISFIT_MM = 1e-3
MISFIT_DEG = 0.01

GROUP_TYPE = "App::DocumentObjectGroup"
BODY_TYPE = "PartDesign::Body"
VARSET_TYPE = "App::VarSet"

FRAME_BASE = "Frame"
BENT_BASE = "Bent"
BAY_BASE = "Bay"

SEAT_PREFIX = "Seat_"
SEAT_PROP = "SeatPlacement"
SEAT_GROUP = "Seat"
# 180 deg about the datum's local Y, as an expression.
FLIP_EXPR = "placement(vector(0; 0; 0); rotation(vector(0; 1; 0); 180))"

PROJECT_VARSET_LABEL = "ProjectVars"
FRAME_ORIGIN_PROP = "FrameOrigin"
FRAME_ORIGIN_GROUP = "Frame"

PLACEMENT = "Placement"

SEAT_TOOLTIP = (
    "Where the timber this timber joint places sits — the seat, computed "
    "from the two datums. The timber's own Placement reads this; do not "
    "edit it.")
FRAME_ORIGIN_TOOLTIP = (
    "Where the frame's principal timber sits, and with it the whole "
    "frame: every other timber is seated from it through its joints. "
    "Move the frame by editing this.")


# --------------------------------------------------------------------------
# The joint's two sides
# --------------------------------------------------------------------------

def _host_mate(varset):
    """(host datum, mate datum) for a paired timber joint, or None."""
    pair = joint_datums(varset)
    if len(pair) != 2:
        return None
    host = joint_handle.anchor_datum(varset)
    if host not in pair:
        host = pair[0]
    mate = pair[1] if host is pair[0] else pair[0]
    return host, mate


def joint_timbers(varset):
    """(host timber, mate timber) for a paired timber joint, or None."""
    pair = _host_mate(varset)
    if pair is None:
        return None
    host, mate = datums.owner(pair[0]), datums.owner(pair[1])
    if host is None or mate is None or host is mate:
        return None
    return host, mate


# --------------------------------------------------------------------------
# The frame container
# --------------------------------------------------------------------------

def member_bodies(group):
    """Every timber body inside a frame or grouping tree."""
    out, seen = [], set()

    def walk(g):
        for child in getattr(g, "Group", []):
            if child.Name in seen:
                continue
            seen.add(child.Name)
            if child.TypeId == GROUP_TYPE:
                walk(child)
            elif child.TypeId == BODY_TYPE and dims_varset(child) is not None:
                out.append(child)

    walk(group)
    return out


def is_frame_group(obj):
    """A frame: a root Std Group holding timbers. Structural — the joints
    group holds handles, a bent group has a parent."""
    return (obj.TypeId == GROUP_TYPE and obj.getParentGroup() is None
            and bool(member_bodies(obj)))


def frame_group(doc, label=""):
    """Find or create the frame Std Group. An existing frame is reused;
    a named one must match that label."""
    for obj in doc.Objects:
        if is_frame_group(obj) and (not label or obj.Label == label):
            return obj
    label = (label or "").strip() or naming.next_serial(
        [o.Label for o in doc.Objects], FRAME_BASE, sep="-")
    for obj in doc.getObjectsByLabel(label):
        if obj.TypeId == GROUP_TYPE:
            return obj
    group = doc.addObject(GROUP_TYPE, FRAME_BASE)
    group.Label = label
    return group


def subgroup(frame, label="", base=BENT_BASE):
    """Find or create a bent/bay Std Group inside a frame. Tree
    organisation only — a Std Group is not a GeoFeatureGroup, so
    membership has no geometric effect whatsoever."""
    doc = frame.Document
    label = (label or "").strip() or naming.next_serial(
        [o.Label for o in doc.Objects], base, sep="-")
    for obj in doc.getObjectsByLabel(label):
        if obj.TypeId == GROUP_TYPE:
            return obj
    group = doc.addObject(GROUP_TYPE, base)
    group.Label = label
    frame.addObject(group)
    return group


def containing_frame(obj):
    """The outermost Std Group an object sits in, or None."""
    group = obj.getParentGroup()
    if group is None:
        return None
    while True:
        parent = group.getParentGroup()
        if parent is None:
            return group
        group = parent


# --------------------------------------------------------------------------
# Placement state — read from the document, never tracked
# --------------------------------------------------------------------------

def placement_expression(body):
    """The expression driving a timber's whole Placement, or None."""
    for path, expr in body.ExpressionEngine:
        if path.lstrip(".") == PLACEMENT:
            return expr
    return None


def seat_label(varset):
    return f"{SEAT_PREFIX}{varset.Label}"


def is_seat(obj):
    """A seat VarSet: structural, on the SeatPlacement property."""
    return obj.TypeId == VARSET_TYPE and hasattr(obj, SEAT_PROP)


def seat_of_joint(varset):
    """The seat VarSet a timber joint carries, or None."""
    handle = joint_handle.find_handle(varset)
    for child in (getattr(handle, "Group", []) if handle is not None else []):
        if is_seat(child):
            return child
    for obj in varset.Document.getObjectsByLabel(seat_label(varset)):
        if is_seat(obj):
            return obj
    return None


def seat_driving(body):
    """The seat VarSet placing this timber, or None."""
    expr = placement_expression(body)
    if not expr or SEAT_PROP not in expr:
        return None
    named = naming.referenced_labels(expr)
    for obj in body.Document.Objects:
        if is_seat(obj) and obj.Label in named:
            return obj
    return None


def is_anchored(body):
    """True when the timber roots its placement component — Placement
    bound to a FrameOrigin rather than to a seat."""
    expr = placement_expression(body)
    return bool(expr) and FRAME_ORIGIN_PROP in expr


def is_placed(body):
    """True when a timber's position is driven: seated, or anchored."""
    return is_anchored(body) or seat_driving(body) is not None


def joint_of_seat(seat_vs):
    """The timber joint a seat belongs to, or None."""
    doc = seat_vs.Document
    handle = seat_vs.getParentGroup()
    if handle is not None and joint_handle.is_handle(handle):
        return joint_handle.handle_varset(handle)
    if seat_vs.Label.startswith(SEAT_PREFIX):
        for obj in doc.getObjectsByLabel(seat_vs.Label[len(SEAT_PREFIX):]):
            if obj.TypeId == VARSET_TYPE:
                return obj
    return None


def places(varset):
    """The timber this joint's seat places, or None when it places
    nothing — a loop closer, or unseated."""
    seat_vs = seat_of_joint(varset)
    if seat_vs is None:
        return None
    for body in joint_timbers(varset) or ():
        if seat_driving(body) is seat_vs:
            return body
    return None


def anchor_timber(body):
    """The timber `body` is seated FROM, or None when it is a root."""
    seat_vs = seat_driving(body)
    if seat_vs is None:
        return None
    varset = joint_of_seat(seat_vs)
    pair = joint_timbers(varset) if varset is not None else None
    if pair is None:
        return None
    host, mate = pair
    return host if mate is body else mate


def seat_path(body):
    """[(seat, timber it places)] from `body` up to its component's root,
    nearest first. Empty when `body` is itself a root."""
    path, seen = [], set()
    while True:
        seat_vs = seat_driving(body)
        if seat_vs is None or seat_vs.Name in seen:
            return path
        seen.add(seat_vs.Name)
        path.append((seat_vs, body))
        nxt = anchor_timber(body)
        if nxt is None or nxt.Name in {b.Name for _s, b in path}:
            return path
        body = nxt


def root_of(body):
    """The root of `body`'s placement component (itself when it is one)."""
    path = seat_path(body)
    return anchor_timber(path[-1][1]) or path[-1][1] if path else body


# --------------------------------------------------------------------------
# The anchor
# --------------------------------------------------------------------------

def project_varset(doc, create=True):
    """The project variables VarSet, created on demand."""
    for obj in doc.Objects:
        if obj.TypeId == VARSET_TYPE and obj.Label == PROJECT_VARSET_LABEL:
            return obj
    if not create:
        return None
    pv = doc.addObject(VARSET_TYPE, "ProjectVars")
    pv.Label = PROJECT_VARSET_LABEL
    return pv


def anchored_timber(doc):
    """The timber bound to FrameOrigin, or None. Exactly one timber in a
    document is anchored: every other placement root is *provisional* —
    a literal placement, waiting for a joint to seat it."""
    for obj in doc.Objects:
        if obj.TypeId == BODY_TYPE and is_anchored(obj):
            return obj
    return None


def anchor(doc, body):
    """Anchor a timber: bind its Placement to the project FrameOrigin,
    seeded with where it already stands, so nothing moves."""
    pv = project_varset(doc)
    if not hasattr(pv, FRAME_ORIGIN_PROP):
        pv.addProperty("App::PropertyPlacement", FRAME_ORIGIN_PROP,
                       FRAME_ORIGIN_GROUP, FRAME_ORIGIN_TOOLTIP)
        setattr(pv, FRAME_ORIGIN_PROP, App.Placement(body.Placement))
    body.setExpression(PLACEMENT, f"<<{pv.Label}>>.{FRAME_ORIGIN_PROP}")
    return pv


def _freeze(body):
    """Drop whatever drives a timber's Placement, leaving it exactly
    where it stands."""
    if placement_expression(body) is None:
        return False
    current = App.Placement(body.Placement)
    body.setExpression(PLACEMENT, None)
    body.Placement = current
    return True


# --------------------------------------------------------------------------
# Seats
# --------------------------------------------------------------------------

def seat(varset, anchor_body, mover_body):
    """Seat `mover_body` from `anchor_body` through timber joint
    `varset`: create or rewrite the joint's seat VarSet, point the
    mover's Placement at it, and file it under the joint's handle.
    Caller owns the transaction."""
    pair = _host_mate(varset)
    if pair is None:
        raise JointError(f"{varset.Label}: not paired — nothing to seat")
    host_d, mate_d = pair
    if anchor_body is datums.owner(host_d):
        near, far = host_d, mate_d
    elif anchor_body is datums.owner(mate_d):
        near, far = mate_d, host_d
    else:
        raise JointError(f"{anchor_body.Label!r} is not a timber of "
                         f"{varset.Label}")
    if mover_body is not datums.owner(far):
        raise JointError(f"{mover_body.Label!r} is not the other timber of "
                         f"{varset.Label}")
    doc = varset.Document
    seat_vs = seat_of_joint(varset)
    if seat_vs is None:
        seat_vs = doc.addObject(VARSET_TYPE, "Seat")
        seat_vs.Label = seat_label(varset)
    if not hasattr(seat_vs, SEAT_PROP):
        seat_vs.addProperty("App::PropertyPlacement", SEAT_PROP, SEAT_GROUP,
                            SEAT_TOOLTIP)
    seat_vs.setExpression(
        SEAT_PROP,
        f"<<{anchor_body.Label}>>.Placement * <<{near.Label}>>.Placement"
        f" * {FLIP_EXPR} * minvert(<<{far.Label}>>.Placement)")
    mover_body.setExpression(PLACEMENT, f"<<{seat_vs.Label}>>.{SEAT_PROP}")
    handle = joint_handle.find_handle(varset)
    if handle is not None and seat_vs.getParentGroup() is not handle:
        handle.addObject(seat_vs)
    return seat_vs


def unseat(varset):
    """Remove a joint's seat, freezing the timber it placed where it
    stands — Remove Timber Joint must move nothing."""
    seat_vs = seat_of_joint(varset)
    if seat_vs is None:
        return False
    doc = varset.Document
    for body in doc.Objects:
        if body.TypeId == BODY_TYPE and seat_driving(body) is seat_vs:
            _freeze(body)
    doc.removeObject(seat_vs.Name)
    return True


def reverse_seat(seat_vs, placed=None):
    """Turn "this joint places X from Y" into "it places Y from X".

    Rebinds Y's Placement to the seat; X's binding is left for the caller
    to replace — the next reversal up the path, or the joint doing the
    merge."""
    varset = joint_of_seat(seat_vs)
    pair = joint_timbers(varset) if varset is not None else None
    if pair is None:
        return None
    host_b, mate_b = pair
    if placed is None:
        placed = next((b for b in (host_b, mate_b)
                       if seat_driving(b) is seat_vs), None)
    if placed is None:
        return None
    other = host_b if placed is mate_b else mate_b
    return seat(varset, placed, other)


def re_root(body):
    """Make `body` the root of its placement component: reverse every
    seat between it and the current root. `body` is left frozen where it
    stands — the caller normally seats it straight afterwards."""
    path = seat_path(body)
    _freeze(body)
    for seat_vs, placed in path:
        reverse_seat(seat_vs, placed)
    return [s for s, _b in path]


Seating = namedtuple("Seating", "seat mover anchored closing merged")


def place_on_apply(doc, varset):
    """Place what this timber joint places, when it is applied.

    Anchors the host when neither timber is placed yet and the frame
    has no anchor; seats whichever side is loose; merges two placement
    components by re-rooting the one without the frame's anchor; or
    reports a loop closure when both sides already belong to the same
    component. Returns a Seating, or None when the joint is not
    paired. Caller owns the transaction.

    **Recomputes before returning**, so the timber it placed really is
    at its seat when the call comes back: a seat is an expression, and
    an expression is worth nothing until the document evaluates it. The
    Fixed-joint path this replaced recomputed for the same reason."""
    seating = _place_on_apply(doc, varset)
    if seating is not None:
        doc.recompute()
    return seating


def _place_on_apply(doc, varset):
    """The placement decision itself; `place_on_apply` recomputes."""
    pair = joint_timbers(varset)
    if pair is None:
        return None
    host_b, mate_b = pair
    homes = [containing_frame(b) for b in (host_b, mate_b)]
    if None in homes:                       # never create a stray frame
        group = next((h for h in homes if h is not None), None) \
            or frame_group(doc)
        for body, home in zip((host_b, mate_b), homes):
            if home is None:
                group.addObject(body)
    joint_handle.ensure_handle(varset)      # re-files it under the frame
    anchored = None
    if not is_placed(host_b) and not is_placed(mate_b) \
            and anchored_timber(doc) is None:
        anchor(doc, host_b)              # the frame's principal timber
        anchored = host_b
    if not is_placed(mate_b):
        return Seating(seat(varset, host_b, mate_b), mate_b, anchored,
                       False, False)
    if not is_placed(host_b):
        return Seating(seat(varset, mate_b, host_b), host_b, anchored,
                       False, False)
    root_h, root_m = root_of(host_b), root_of(mate_b)
    if root_h is root_m:
        return Seating(None, None, None, True, False)        # loop closure
    # Merge two components. The one holding the frame's anchor stays put;
    # the other is re-rooted onto this joint and swings in behind it.
    if is_anchored(root_m) and not is_anchored(root_h):
        re_root(host_b)
        return Seating(seat(varset, mate_b, host_b), host_b, None, False, True)
    re_root(mate_b)
    return Seating(seat(varset, host_b, mate_b), mate_b, None, False, True)


# --------------------------------------------------------------------------
# Misfit — the loop-closure check
# --------------------------------------------------------------------------

def joint_misfit(varset):
    """(mm, degrees) between a joint's seated pose and its actual one —
    (0, 0) when seated. On a loop closer this is the check that the loop
    still closes."""
    pair = _host_mate(varset)
    if pair is None:
        return (0.0, 0.0)
    return datums.misfit(*pair)


def is_misfit(varset):
    mm, deg = joint_misfit(varset)
    return mm > MISFIT_MM or deg > MISFIT_DEG


# --------------------------------------------------------------------------
# The repair / bulk path
# --------------------------------------------------------------------------

def pick_principal(bodies, joints):
    """The timber to anchor: the first (selection order) that hosts a
    joint without ever being the entering half. Falls back to the first."""
    movers, anchors = set(), set()
    for varset in joints:
        pair = joint_timbers(varset)
        if pair is None:
            continue
        anchors.add(pair[0].Name)
        movers.add(pair[1].Name)
    for body in bodies:
        if body.Name in anchors and body.Name not in movers:
            return body
    return bodies[0]


Rebuild = namedtuple("Rebuild",
                     "frame seated closures misfits skipped adopted")


def rebuild_seats(doc, bodies, label="", principal=None,
                  anchor_principal=True):
    """Seat Timbers — the bulk and repair path.

    Files loose timbers in the frame group, gives every timber joint a
    handle, anchors the principal timber, and seats every timber
    reachable from it through its joints. Existing seats are kept; only
    the missing ones are built. With `anchor_principal` False the
    principal keeps the placement it already has and roots the component
    provisionally, without a FrameOrigin binding — what a freshly
    duplicated set of timbers wants until a joint ties it to the frame. Returns a Rebuild: the frame group, the
    joints that seated a timber, the loop closers, the joints whose two
    sides disagree, the timbers no joint reaches, and how many handles
    were adopted. Caller owns the transaction."""
    if not bodies:
        raise JointError("select the timbers to seat first")
    adopted = joint_handle.adopt_handles(doc)
    frame = frame_group(doc, label)
    for body in bodies:
        if containing_frame(body) is None:
            frame.addObject(body)
    doc.recompute()

    members = member_bodies(frame) or list(bodies)
    inside, _outside = bent_joints(doc, members)
    seatable = [v for v in inside if joint_timbers(v) is not None]
    skipped = [v.Label for v in inside if joint_timbers(v) is None]

    placed = {b.Name for b in members if is_placed(b)}
    if principal is None:
        principal = next((b for b in members if is_anchored(b)), None)
    if principal is None:
        principal = pick_principal(
            [b for b in bodies if b in members] or members, seatable)
    if anchor_principal:
        held = anchored_timber(doc)
        if held is not None and held is not principal:
            _freeze(held)                # one anchored timber per document
            held = None
        if held is None:
            anchor(doc, principal)
    placed.add(principal.Name)

    seated, remaining, progress = [], list(seatable), True
    while remaining and progress:
        progress, still = False, []
        for varset in remaining:
            host_b, mate_b = joint_timbers(varset)
            in_host, in_mate = host_b.Name in placed, mate_b.Name in placed
            if in_host and in_mate:
                still.append(varset)
            elif in_host:
                seat(varset, host_b, mate_b)
                placed.add(mate_b.Name)
                seated.append(varset)
                progress = True
            elif in_mate:
                seat(varset, mate_b, host_b)
                placed.add(host_b.Name)
                seated.append(varset)
                progress = True
            else:
                still.append(varset)
        remaining = still

    closures = []
    for varset in remaining:
        host_b, mate_b = joint_timbers(varset)
        if host_b.Name in placed and mate_b.Name in placed:
            if places(varset) is None:
                closures.append(varset.Label)
        else:
            skipped.append(varset.Label)
    doc.recompute()
    misfits = [v.Label for v in seatable if is_misfit(v)]
    return Rebuild(frame, seated, closures, misfits, skipped, adopted)
