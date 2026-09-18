"""Assemble Timbers — the always-assembled two-level structure.

Bents are native Assembly::AssemblyObjects; the building is a parent
frame assembly of bent sub-assemblies (created automatically on the
first cross-bent timber joint). Every timber joint becomes one Fixed
assembly joint referencing the two paired datums by object reference
(never solid faces), with the seat — 180° about the datum's local Y,
the same for every joint now that every datum's Z points out of its
material — carried in the joint's Offset1 so its NOMINAL pose is the
correct seat.

Container rules (deterministic, applied by assimilate_joint every time
a timber joint is created):

- both timbers loose        -> a new bent sub-assembly; the host timber
                               (start at the Principal Post) is grounded
- one timber loose          -> it joins the other timber's assembly
- same assembly             -> the Fixed joint lives there
- different assemblies      -> the joint lives in their deepest common
                               parent; two top-level bents get a new
                               parent frame assembly, grounded by the
                               oldest bent (the principal bent)

No temporary anchors, ever: the only grounds are each sub-assembly's
internal principal timber and the principal bent in the parent.

**Pre-position before the solver sees the joint.** A Fixed joint has no
flip control and the solver converges to the solution nearest the
current pose; worse, if a recompute runs while the mover is parked far
away and rotated, MbD can rotate the GROUNDED part (rev-2 Step 0 probe:
~20° on the ±X faces). So the free side is moved to its exact seat —
computable from the two datums — and only then is the document
recomputed and solved. Nothing here recomputes between creating the
joint and seating it.

Tier 1 throughout: assemblies, assembly joints, and datum references
are stock FreeCAD; uninstalling the workbench changes nothing.
"""

from __future__ import annotations

import math
import sys
from collections import namedtuple

import FreeCAD as App

from . import datums, joint_handle
from .apply import JointError, bent_joints, joint_datums

# post-solve agreement thresholds: solver noise is ~1e-6; anything past
# these means two timber joints place a timber inconsistently
MISFIT_MM = 1e-3
MISFIT_DEG = 0.01

ASSEMBLY_TYPE = "Assembly::AssemblyObject"


def _joint_object():
    """The Assembly workbench's JointObject module (its GUI half is
    gated behind App.GuiUp, so this works headless too)."""
    try:
        import JointObject
    except ImportError:
        import os
        mod = os.path.join(App.getHomePath(), "Mod", "Assembly")
        if os.path.isdir(mod) and mod not in sys.path:
            sys.path.append(mod)
        import JointObject
    return JointObject


def _engagement_datums(varset):
    """((mover_body, mate_datum), (anchor_body, host_datum)) for a
    seatable timber joint, or None when it is not paired."""
    pair = joint_datums(varset)
    if len(pair) != 2:
        return None
    host = joint_handle.anchor_datum(varset)
    if host not in pair:
        host = pair[0]
    mate = pair[1] if host is pair[0] else pair[0]
    return (datums.owner(mate), mate), (datums.owner(host), host)


# --------------------------------------------------------------------------
# Containers
# --------------------------------------------------------------------------

def container_assembly(obj):
    """The nearest Assembly ancestor of `obj`, or None. Std Groups are
    transparent (they are not GeoFeatureGroups)."""
    parent = obj.getParentGeoFeatureGroup()
    while parent is not None and parent.TypeId != ASSEMBLY_TYPE:
        parent = parent.getParentGeoFeatureGroup()
    return parent


def root_assembly(asm):
    while True:
        parent = container_assembly(asm)
        if parent is None:
            return asm
        asm = parent


def assembly_chain(obj):
    """Assembly ancestors of `obj`, nearest first."""
    chain = []
    asm = container_assembly(obj)
    while asm is not None:
        chain.append(asm)
        asm = container_assembly(asm)
    return chain


def moving_part(body, assembly):
    """The direct member of `assembly` that carries `body` — the body
    itself, or the sub-assembly the body lives in."""
    obj = body
    current = container_assembly(obj)
    while current is not assembly:
        if current is None:
            raise JointError(f"{body.Label!r} is not inside {assembly.Label!r}")
        obj = current
        current = container_assembly(current)
    return obj


def _lcs_path(moving, lcs):
    """The reference sub-path from a moving part down to a datum,
    e.g. 'T-Post-001.D_T_Post_001_YPos_001.' (empty prefix when the
    moving part is the body itself)."""
    chain = [lcs]
    obj = lcs.getParentGeoFeatureGroup()
    while obj is not None and obj is not moving:
        chain.append(obj)
        obj = obj.getParentGeoFeatureGroup()
    return ".".join(o.Name for o in reversed(chain)) + "."


def assembly_joint_group(asm):
    for child in asm.Group:
        if child.TypeId == "Assembly::JointGroup":
            return child
    return asm.newObject("Assembly::JointGroup", "Joints")


def grounded_joint(asm):
    for child in assembly_joint_group(asm).Group:
        if hasattr(child, "ObjectToGround"):
            return child
    return None


def ground(asm, obj):
    """Ground `obj` (a direct member) in `asm`, replacing any existing
    ground — one principal per assembly."""
    JointObject = _joint_object()
    existing = grounded_joint(asm)
    if existing is not None:
        asm.Document.removeObject(existing.Name)
    g = assembly_joint_group(asm).newObject("App::FeaturePython", "GroundedJoint")
    JointObject.GroundedJoint(g, obj)
    if App.GuiUp:
        JointObject.ViewProviderGroundedJoint(g.ViewObject)
    return g


def new_assembly(doc, label="", base="Bent"):
    from . import naming
    label = (label or "").strip() or naming.next_serial(
        [o.Label for o in doc.Objects], base)
    if doc.getObjectsByLabel(label):
        raise JointError(f"label {label!r} already exists")
    asm = doc.addObject(ASSEMBLY_TYPE, base)
    asm.Type = "Assembly"
    asm.Label = label
    assembly_joint_group(asm)
    return asm


def pick_grounded(bodies, joints):
    """The timber to ground: the first (selection order) that hosts a
    joint without ever being the entering half. Falls back to the
    first body."""
    movers, anchors = set(), set()
    for varset in joints:
        pair = _engagement_datums(varset)
        if pair is None:
            continue
        movers.add(pair[0][0])
        anchors.add(pair[1][0])
    for body in bodies:
        if body in anchors and body not in movers:
            return body
    return bodies[0]


# --------------------------------------------------------------------------
# Assimilation — one timber joint -> one Fixed assembly joint, seated
# --------------------------------------------------------------------------

def _fixed_label(varset):
    return f"Fixed_{varset.Label}"


def _referenced_datums(joint):
    """Internal names of the LCS datums an assembly joint's references
    point at — the last segment of each dotted reference path."""
    names = set()
    for attr in ("Reference1", "Reference2"):
        ref = getattr(joint, attr, None)
        subs = ref[1] if ref and len(ref) == 2 else []
        for sub in subs:
            if sub:
                names.add(sub.rstrip(".").split(".")[-1])
                break
    return names


def find_fixed_joints(doc, varset):
    """EVERY assembly joint seating this timber joint (normally one),
    matched structurally on the datums its references point at."""
    pair = joint_datums(varset)
    if len(pair) != 2:
        return [obj for obj in doc.getObjectsByLabel(_fixed_label(varset))
                if getattr(obj, "JointType", None) is not None]
    want = {pair[0].Name, pair[1].Name}
    return [obj for obj in doc.Objects
            if getattr(obj, "JointType", None) is not None
            and _referenced_datums(obj) == want]


def find_fixed_joint(doc, varset):
    found = find_fixed_joints(doc, varset)
    return found[0] if found else None


def _placement_for(varset):
    """(joint_asm, created, principal): the assembly the timber joint's
    Fixed joint belongs in, per the container rules."""
    doc = varset.Document
    (mover, _mate), (anchor, _host) = _engagement_datums(varset)
    a_asm = container_assembly(anchor)
    m_asm = container_assembly(mover)
    if a_asm is None and m_asm is None:
        asm = new_assembly(doc)
        asm.addObject(anchor)
        asm.addObject(mover)
        ground(asm, anchor)                 # the Principal timber
        return asm, asm, anchor
    if a_asm is None:
        m_asm.addObject(anchor)
        return m_asm, None, None
    if m_asm is None:
        a_asm.addObject(mover)
        return a_asm, None, None
    a_chain = assembly_chain(anchor)        # nearest first
    m_set = set(assembly_chain(mover))
    for asm in a_chain:
        if asm in m_set:
            return asm, None, None          # deepest common parent
    root_a, root_m = a_chain[-1], root_assembly(m_asm)

    def is_parent(asm):
        return any(c.TypeId == ASSEMBLY_TYPE for c in asm.Group)

    if is_parent(root_a) and not is_parent(root_m):
        root_a.addObject(root_m)
        return root_a, None, None
    if is_parent(root_m) and not is_parent(root_a):
        root_m.addObject(root_a)
        return root_m, None, None
    frame = new_assembly(doc, base="Frame")
    frame.addObject(root_a)
    frame.addObject(root_m)
    # the principal bent grounds the frame: the OLDEST of the two
    order = {o.Name: i for i, o in enumerate(doc.Objects)}
    principal = min((root_a, root_m), key=lambda o: order[o.Name])
    ground(frame, principal)
    return frame, frame, principal


Assimilation = namedtuple("Assimilation", "joint new_assembly principal")


def refresh_joint_display(asm):
    """Touch every assembly joint inside `asm`'s tree so viewproviders
    redraw after a container moved."""
    doc = asm.Document
    for obj in doc.Objects:
        if getattr(obj, "JointType", None) is None \
                and not hasattr(obj, "ObjectToGround"):
            continue
        parent = obj.getParentGeoFeatureGroup()
        if parent is not None and (parent is asm or asm in assembly_chain(parent)):
            obj.touch()
    doc.recompute()


def _is_connected(assembly, part, suppress_joint=None):
    """Whether `part` traces to the assembly's grounded member through
    its joints, ignoring `suppress_joint` (the one being created)."""
    if suppress_joint is not None:
        suppress_joint.Suppressed = True
    try:
        return assembly.isPartConnected(part)
    finally:
        if suppress_joint is not None:
            suppress_joint.Suppressed = False


def assimilate_joint(doc, varset):
    """Absorb a timber joint into the structure assembly: choose (or
    create) the right container, create its Fixed assembly joint (the
    seat flip in Offset1), pre-seat the free side at the engaged pose,
    and only then recompute and solve. Returns an Assimilation, or None
    when the joint is not paired. Caller owns the transaction."""
    pair = _engagement_datums(varset)
    if pair is None:
        return None
    joint_asm, new_asm, principal = _placement_for(varset)
    doc.recompute()

    (mover, mate), (anchor, host) = pair
    mp_anchor = moving_part(anchor, joint_asm)
    mp_mover = moving_part(mover, joint_asm)
    if mp_anchor is mp_mover:
        raise JointError(f"{varset.Label}: both halves resolve to the same "
                         f"moving part in {joint_asm.Label!r}")

    for old in find_fixed_joints(doc, varset):
        doc.removeObject(old.Name)
    JointObject = _joint_object()
    joint = assembly_joint_group(joint_asm).newObject("App::FeaturePython", "FixedJoint")
    JointObject.Joint(joint, 0)                     # 0 = Fixed
    joint.Label = _fixed_label(varset)
    joint.Offset1 = datums.FLIP_PLACEMENT           # nominal pose = the seat
    joint.Reference1 = (mp_anchor, [_lcs_path(mp_anchor, host), ""])
    joint.Reference2 = (mp_mover, [_lcs_path(mp_mover, mate), ""])
    joint.Placement1 = joint.Proxy.findPlacement(joint, joint.Reference1, 0)
    joint.Placement2 = joint.Proxy.findPlacement(joint, joint.Reference2, 1)
    if App.GuiUp:
        JointObject.ViewProviderJoint(joint.ViewObject)

    # Pre-seat the free side — the one NOT yet connected to the
    # assembly's ground — at the exact engaged pose. No recompute has
    # run since the joint was created (see the module docstring).
    move = None
    if not _is_connected(joint_asm, mp_mover, joint):
        move, delta = mp_mover, datums.seat_delta(host, mate)
    elif not _is_connected(joint_asm, mp_anchor, joint):
        move, delta = mp_anchor, datums.seat_delta(mate, host)
    if move is not None:
        new_global = delta.multiply(move.getGlobalPlacement())
        parent_g = move.getGlobalPlacement().multiply(move.Placement.inverse())
        move.Placement = parent_g.inverse().multiply(new_global)
    doc.recompute()
    for asm in {joint_asm, root_assembly(joint_asm)}:
        asm.solve()
    doc.recompute()
    if move is not None and move.TypeId == ASSEMBLY_TYPE:
        refresh_joint_display(move)
    joint_handle.ensure_handle(varset)
    return Assimilation(joint, new_asm, principal)


def joint_misfit(varset):
    """(mm, degrees) between the joint's seated pose and its actual
    pose — (0, 0) when seated."""
    pair = _engagement_datums(varset)
    if pair is None:
        return (0.0, 0.0)
    (_, mate), (_, host) = pair
    return datums.misfit(host, mate)


def is_misfit(varset):
    mm, deg = joint_misfit(varset)
    return mm > MISFIT_MM or deg > MISFIT_DEG


# --------------------------------------------------------------------------
# Bulk form — Assemble Timbers
# --------------------------------------------------------------------------

def member_bodies(assembly):
    """Every timber body inside an assembly tree."""
    doc = assembly.Document
    return [o for o in doc.Objects
            if o.TypeId == "PartDesign::Body" and assembly in assembly_chain(o)]


def assemble_timbers(doc, bodies, assembly=None, label="", grounded=None):
    """Bulk assimilation: put loose `bodies` into `assembly` (created
    with `label` when None), ground the principal timber (`grounded`,
    or the pick_grounded heuristic), and assimilate every timber joint
    among the members. Returns (assembly, skipped, misfits, adopted).
    Caller owns the transaction."""
    if not bodies:
        raise JointError("select the timbers to assemble first")
    adopted = joint_handle.adopt_handles(doc)
    if assembly is None:
        homes = [container_assembly(b) for b in bodies]
        if len(set(homes)) == 1 and homes[0] is not None:
            assembly = homes[0]
        else:
            assembly = new_assembly(doc, label)
    for body in bodies:
        if container_assembly(body) is None:
            assembly.addObject(body)
    doc.recompute()

    members = member_bodies(root_assembly(assembly))
    if not members:
        raise JointError(
            f"{assembly.Label} has no timber bodies to assemble — the "
            f"selected timbers already belong to another assembly")
    inside, _outside = bent_joints(doc, members)
    seatable = [v for v in inside if _engagement_datums(v)]

    if grounded is not None:
        ground(assembly, moving_part(grounded, assembly))
    elif grounded_joint(assembly) is None:
        principal = pick_grounded([b for b in bodies if b in members] or members,
                                  seatable)
        ground(assembly, moving_part(principal, assembly))

    skipped = [v.Label for v in inside if v not in seatable]
    for varset in seatable:
        assimilate_joint(doc, varset)
    doc.recompute()
    misfits = [v.Label for v in seatable if is_misfit(v)]
    return assembly, skipped, misfits, adopted
