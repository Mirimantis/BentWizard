"""Assemble Timbers — the always-assembled two-level structure.

Bents are native Assembly::AssemblyObjects; the building is a parent
assembly of bent sub-assemblies (created automatically on the first
cross-bent timber joint). Every timber joint becomes one Fixed assembly
joint referencing the landing / mate LCS datums by object reference
(the frames a joint's Frame_Role property names, never solid faces),
with the face-parity correction carried
in the joint's Offset1 so its NOMINAL pose is the correct seat.

Container rules (deterministic, applied by assimilate_joint every time
a timber joint is created):

- both timbers loose        -> a new bent sub-assembly; the anchor
                               timber (the mortise carrier — start at
                               the Principal Post) is grounded in it
- one timber loose          -> it joins the other timber's assembly
- same assembly             -> the Fixed joint lives there
- different assemblies      -> the joint lives in their deepest common
                               parent; two top-level bents get a new
                               parent frame assembly, grounded by the
                               anchor-side bent (the principal bent)

No temporary anchors, ever: the only grounds are each sub-assembly's
internal principal timber and the principal bent in the parent. An
unconnected bent's parent-level placement stays free (user-movable)
until a cross-assembly joint constrains it — verified: the parent
solver leaves unconstrained sub-assemblies untouched, and a plain
document recompute re-solves the chain, so tie-beam Length edits move
whole bays parametrically.

Tier 1 throughout: assemblies, assembly joints, and datum references
are stock FreeCAD; uninstalling the workbench changes nothing.
"""

from __future__ import annotations

import math
import sys
from collections import namedtuple

import FreeCAD as App

from . import naming
from .apply_joint import (JointError, bent_joints, joint_role_frames,
                          mate_parity)

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


def _engagement_frames(varset):
    """((mover_body, mate_lcs), (anchor_body, landing_lcs)) for a
    seatable timber joint, or None when a frame is missing (legacy
    joints applied before mate frames existed)."""
    frames = joint_role_frames(varset)
    mover = next(((b, f["mate"]) for b, f in frames.items() if f["mate"]),
                 None)
    anchor = next(((b, f["landing"]) for b, f in frames.items()
                   if f["landing"] and not f["mate"]), None)
    if mover is None or anchor is None:
        return None
    return mover, anchor


# --------------------------------------------------------------------------
# Containers
# --------------------------------------------------------------------------

def container_assembly(obj):
    """The nearest Assembly ancestor of `obj`, or None. Std Groups are
    transparent (they are not GeoFeatureGroups), so a body organized in
    a group inside a bent still reports the bent."""
    parent = obj.getParentGeoFeatureGroup()
    while parent is not None and parent.TypeId != ASSEMBLY_TYPE:
        parent = parent.getParentGeoFeatureGroup()
    return parent


def root_assembly(asm):
    """The top of an assembly's container chain."""
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
    itself, or the sub-assembly the body lives in: the unit the
    assembly's solver moves."""
    obj = body
    current = container_assembly(obj)
    while current is not assembly:
        if current is None:
            raise JointError(
                f"{body.Label!r} is not inside {assembly.Label!r}")
        obj = current
        current = container_assembly(current)
    return obj


def _lcs_path(moving, lcs):
    """The reference sub-path from a moving part down to an LCS datum,
    e.g. 'T-Post-001.LocalCoordinateSystem002.' (empty prefix when the
    moving part is the body itself)."""
    chain = [lcs]
    obj = lcs.getParentGeoFeatureGroup()
    while obj is not None and obj is not moving:
        chain.append(obj)
        obj = obj.getParentGeoFeatureGroup()
    return ".".join(o.Name for o in reversed(chain)) + "."


def assembly_joint_group(asm):
    """The assembly's own Assembly::JointGroup (FreeCAD's native
    'Joints' — the reason our Std Group is named TimberJointVars)."""
    for child in asm.Group:
        if child.TypeId == "Assembly::JointGroup":
            return child
    return asm.newObject("Assembly::JointGroup", "Joints")


def grounded_joint(asm):
    """The assembly's GroundedJoint object, or None."""
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
    g = assembly_joint_group(asm).newObject("App::FeaturePython",
                                            "GroundedJoint")
    JointObject.GroundedJoint(g, obj)
    if App.GuiUp:
        JointObject.ViewProviderGroundedJoint(g.ViewObject)
    return g


def new_assembly(doc, label="", base="Bent"):
    """A fresh assembly labeled `label` (or the next free
    '<base>-NNN'), with its native joint group."""
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
    """The timber to ground: the first (selection order) that anchors a
    joint without ever being the entering half — the load-bearing
    primary by the mate-frame heuristic. Falls back to the first body."""
    movers, anchors = set(), set()
    for varset in joints:
        pair = _engagement_frames(varset)
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


def find_fixed_joint(doc, varset):
    for obj in doc.getObjectsByLabel(_fixed_label(varset)):
        if getattr(obj, "JointType", None) is not None:
            return obj
    return None


def _placement_for(varset):
    """(joint_asm, created, principal): the assembly the timber joint's
    Fixed joint belongs in, applying the container rules (may create a
    bent or the parent frame — `created` is the new assembly or None,
    `principal` what got grounded in it)."""
    doc = varset.Document
    (mover, _mate), (anchor, _landing) = _engagement_frames(varset)
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
    # disjoint top-level assemblies: join them under the frame
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
    # the principal bent grounds the frame: the OLDEST of the two —
    # the first bent built holds the Principal Post the framers
    # measured everything from (the anchor side may well be the NEW
    # bent, e.g. a tie beam reaching a duplicated bent's post)
    order = {o.Name: i for i, o in enumerate(doc.Objects)}
    principal = min((root_a, root_m), key=lambda o: order[o.Name])
    ground(frame, principal)
    return frame, frame, principal


Assimilation = namedtuple("Assimilation",
                          "joint new_assembly principal")


def refresh_joint_display(asm):
    """Touch every assembly joint inside `asm`'s tree so viewproviders
    redraw. A joint's icon is drawn from its references' global
    placements, but nothing marks the joint when only its CONTAINER
    moved (a bent seating in the frame) — the icons stay floating at
    the old spot until touched."""
    doc = asm.Document
    for obj in doc.Objects:
        if getattr(obj, "JointType", None) is None \
                and not hasattr(obj, "ObjectToGround"):
            continue
        parent = obj.getParentGeoFeatureGroup()
        if parent is not None and (parent is asm
                                   or asm in assembly_chain(parent)):
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
    create) the right container per the container rules, create its
    Fixed assembly joint (parity in Offset1), pre-seat the free side at
    the engaged pose, and solve. Returns an Assimilation (joint,
    new_assembly, principal — the latter two set when a bent or frame
    was created), or None when the joint has no engagement frames
    (legacy — skipped). Caller owns the transaction."""
    pair = _engagement_frames(varset)
    if pair is None:
        return None
    joint_asm, new_asm, principal = _placement_for(varset)
    doc.recompute()

    (mover, mate), (anchor, landing) = pair
    mp_anchor = moving_part(anchor, joint_asm)
    mp_mover = moving_part(mover, joint_asm)
    if mp_anchor is mp_mover:
        raise JointError(
            f"{varset.Label}: both halves resolve to the same moving "
            f"part in {joint_asm.Label!r}")
    parity = mate_parity(varset, anchor)

    old = find_fixed_joint(doc, varset)
    if old is not None:
        doc.removeObject(old.Name)
    JointObject = _joint_object()
    joint = assembly_joint_group(joint_asm).newObject(
        "App::FeaturePython", "FixedJoint")
    JointObject.Joint(joint, 0)                     # 0 = Fixed
    joint.Label = _fixed_label(varset)
    joint.Offset1 = parity      # nominal pose = the correct seat
    joint.Reference1 = (mp_anchor, [_lcs_path(mp_anchor, landing), ""])
    joint.Reference2 = (mp_mover, [_lcs_path(mp_mover, mate), ""])
    joint.Placement1 = joint.Proxy.findPlacement(joint, joint.Reference1, 0)
    joint.Placement2 = joint.Proxy.findPlacement(joint, joint.Reference2, 1)
    if App.GuiUp:
        JointObject.ViewProviderJoint(joint.ViewObject)

    # Pre-seat the free side at the engaged pose so the solver locks
    # the correct one of the Fixed joint's two orientations. The free
    # side is the one NOT yet connected to the assembly's ground — a
    # tie beam already seated on bent 1 must stay put while the new
    # bent comes to IT, never the reverse.
    landing_g = landing.getGlobalPlacement()
    mate_g = mate.getGlobalPlacement()
    move = None
    if not _is_connected(joint_asm, mp_mover, joint):
        move, delta = mp_mover, (
            landing_g.multiply(parity).multiply(mate_g.inverse()))
    elif not _is_connected(joint_asm, mp_anchor, joint):
        move, delta = mp_anchor, (
            mate_g.multiply(parity.inverse())
            .multiply(landing_g.inverse()))
    if move is not None:
        new_global = delta.multiply(move.getGlobalPlacement())
        parent_g = move.getGlobalPlacement().multiply(
            move.Placement.inverse())
        move.Placement = parent_g.inverse().multiply(new_global)
        doc.recompute()

    for asm in {joint_asm, root_assembly(joint_asm)}:
        asm.solve()
    doc.recompute()
    if move is not None and move.TypeId == ASSEMBLY_TYPE:
        refresh_joint_display(move)
    return Assimilation(joint, new_asm, principal)


def joint_misfit(varset):
    """(mm, degrees) between the joint's seated pose and its actual
    pose — (0, 0) when seated. A parity or station disagreement shows
    up here after a solve."""
    pair = _engagement_frames(varset)
    if pair is None:
        return (0.0, 0.0)
    (_, mate), (anchor, landing) = pair
    target = landing.getGlobalPlacement().multiply(
        mate_parity(varset, anchor))
    delta = target.inverse().multiply(mate.getGlobalPlacement())
    return (delta.Base.Length, math.degrees(delta.Rotation.Angle))


def is_misfit(varset):
    mm, deg = joint_misfit(varset)
    return mm > MISFIT_MM or deg > MISFIT_DEG


# --------------------------------------------------------------------------
# Bulk form — Assemble Timbers
# --------------------------------------------------------------------------

def member_bodies(assembly):
    """Every timber body inside an assembly tree (groups and nested
    assemblies included)."""
    doc = assembly.Document
    return [o for o in doc.Objects
            if o.TypeId == "PartDesign::Body"
            and assembly in assembly_chain(o)]


def assemble_timbers(doc, bodies, assembly=None, label="", grounded=None):
    """Bulk assimilation: put loose `bodies` into `assembly` (created
    with `label` when None), ground the principal timber (`grounded`,
    or the pick_grounded heuristic), and assimilate every timber joint
    among the members. The path for pre-pivot documents, repair, and
    regrounding. Returns (assembly, skipped, misfits): timber-joint
    labels skipped (no engagement frames) and those still disagreeing
    after the solve (kept visible for inspection). Caller owns the
    transaction."""
    if not bodies:
        raise JointError("select the timbers to assemble first")
    if assembly is None:
        assembly = new_assembly(doc, label)
    for body in bodies:
        if container_assembly(body) is None:
            assembly.addObject(body)
    doc.recompute()

    members = member_bodies(root_assembly(assembly))
    inside, _outside = bent_joints(doc, members)
    seatable = [v for v in inside if _engagement_frames(v)]

    if grounded is not None:
        ground(assembly, moving_part(grounded, assembly))
    elif grounded_joint(assembly) is None:
        principal = pick_grounded(
            [b for b in bodies if b in members] or members, seatable)
        ground(assembly, moving_part(principal, assembly))

    skipped = [v.Label for v in inside if v not in seatable]
    for varset in seatable:
        assimilate_joint(doc, varset)
    doc.recompute()
    misfits = [v.Label for v in seatable if is_misfit(v)]
    return assembly, skipped, misfits
