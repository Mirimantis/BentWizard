"""Per-joint handle — the clickable representative of a timber joint.

A timber joint has no single object: it is a VarSet, two landing frames,
a mate frame, sketches and cuts across two Bodies, and a Fixed joint
inside an assembly. The handle gives it one — an ordinary object linked
to the joint's VarSet and its landing frame, marked in the 3D view by a
workbench-drawn marker so an intersection reads as joined at a glance.

Tier 2 by construction: an `App::FeaturePython` carrying a *group*
extension and NO App-level Proxy. Without the workbench it is a plain
container holding native data — nothing to import, nothing to fail, zero
geometric effect (the marker is view-only; the handle owns no Placement
and takes no part in the solve). The ViewProvider is attached only under
a GUI and lives in the Gui document.

Tree home: the handle holds its joint's VarSet, and files in a
`TimberJoints_<Assembly>` Std Group inside the assembly the joint
belongs to, so each bent carries a folder of its own joints — one node
per joint. "Belongs to" is not a second concept — it is exactly where
assimilate_joint put the joint's Fixed assembly joint (its bent, or the
frame for a joint spanning two bents). Joints with no assembly yet fall
back to a bare `TimberJoints` group at the document root.
"""

from __future__ import annotations

import FreeCAD as App

from . import naming

HANDLE_TYPE = "App::FeaturePython"
HANDLE_NAME = "TimberJointHandle"          # internal name; never semantic
HANDLE_PREFIX = "Handle_"                  # Handle_J-HousedMT-001

GROUP_TYPE = "App::DocumentObjectGroup"
GROUP_BASE = "TimberJoints"                # + _<AssemblyLabel> when nested
LEGACY_GROUP_LABELS = ("TimberJointVars", "Joints")

FRAME_PROP = "Frame"
JOINT_PROP = "Joint"
PROP_GROUP = "TimberJoint"

# Whole-joint operations offered on the marker's context menu, as
# (text, callable(varset)). commands.register() fills this at workbench
# start; the ViewProvider only reads it. A joint spans many objects
# across several bodies, so this — not any one of them — is where a
# future joint-wide tool belongs: append an entry, touch no GUI code.
CONTEXT_ACTIONS = []


def handle_label(varset):
    """The handle label for a joint VarSet: 'Handle_J-HousedMT-001'."""
    return f"{HANDLE_PREFIX}{varset.Label}"


def is_handle(obj):
    """True for a timber-joint handle object.

    Structural — our own two link properties on an App::FeaturePython.
    The label is deliberately NOT part of the test: a user may rename a
    handle, and it must still resolve, which is the whole reason the
    joint is bound by link rather than by name. Handles from before the
    Joint link carry Frame and the label instead.
    """
    if obj.TypeId != HANDLE_TYPE:
        return False
    if hasattr(obj, JOINT_PROP) and hasattr(obj, FRAME_PROP):
        return True
    return hasattr(obj, FRAME_PROP) and obj.Label.startswith(HANDLE_PREFIX)


def handle_varset(handle):
    """The joint VarSet a handle stands for, or None.

    The `Joint` link, never the label: this project has twice been bitten
    by name-matched bindings (the JointFrame/MateFrame substring match,
    the drifted Fixed-joint label). Handles from before the VarSet moved
    out into the joints folder still hold it as a group child.
    """
    joint = getattr(handle, JOINT_PROP, None)
    if joint is not None:
        return joint
    for obj in getattr(handle, "Group", []):
        if obj.TypeId == "App::VarSet" \
                and naming.is_joint_varset_label(obj.Label):
            return obj
    return None


def find_handle(varset):
    """The existing handle for a joint, or None.

    Structural first — whichever handle points at (or still holds) this
    VarSet — so a renamed handle is found anyway; the label is only the
    fallback for a handle that lost its link.
    """
    doc = varset.Document
    for obj in doc.Objects:
        if is_handle(obj) and handle_varset(obj) is varset:
            return obj
    for obj in doc.getObjectsByLabel(handle_label(varset)):
        if is_handle(obj):
            return obj
    return None


def joint_varsets(doc):
    """Every timber-joint instance VarSet in a document."""
    return [o for o in doc.Objects
            if o.TypeId == "App::VarSet"
            and naming.is_joint_varset_label(o.Label)]


def anchor_frame(varset):
    """The landing frame the marker sits on: the anchor role's (the half
    that receives, never enters — the same rule engagement_placement
    uses). Falls back to any landing frame, then None."""
    from .apply_joint import joint_role_frames
    frames = joint_role_frames(varset)
    for _body, slot in frames.items():
        if slot["landing"] and not slot["mate"]:
            return slot["landing"]
    for _body, slot in frames.items():
        if slot["landing"]:
            return slot["landing"]
    return None


def joint_container(varset):
    """The assembly a timber joint belongs to, or None.

    Its Fixed assembly joint's container — the container rules resolved
    once, by assimilate_joint, rather than re-derived here. Before
    assimilation (or for a legacy joint with no engagement frames), the
    common assembly of the joint's role bodies.
    """
    from .apply_joint import joint_role_frames
    from .assemble import container_assembly, find_fixed_joints
    doc = varset.Document
    for fixed in find_fixed_joints(doc, varset):
        asm = container_assembly(fixed)
        if asm is not None:
            return asm
    homes = {container_assembly(b) for b in joint_role_frames(varset)}
    homes.discard(None)
    return homes.pop() if len(homes) == 1 else None


def group_label(container):
    """The label of the joints group for an assembly (or the document
    root when None). Suffixed with the assembly's label: FreeCAD labels
    are document-global, so every bent's group needs its own."""
    if container is None:
        return GROUP_BASE
    return f"{GROUP_BASE}_{container.Label}"


def handle_group(doc, container=None):
    """Find or create the joints Std Group for a container.

    Matched by label AND TypeId, never label alone: every FreeCAD
    Assembly carries its own 'Joints' (an Assembly::JointGroup) and must
    never be hijacked — the reason this group was named apart in the
    first place. A root-level legacy group (TimberJointVars, or the
    pre-1.1 'Joints' Std Group) is renamed in place rather than
    duplicated.
    """
    label = group_label(container)
    for obj in doc.getObjectsByLabel(label):
        if obj.TypeId == GROUP_TYPE:
            return obj
    if container is None:
        for legacy in LEGACY_GROUP_LABELS:
            for obj in doc.getObjectsByLabel(legacy):
                if obj.TypeId == GROUP_TYPE \
                        and obj.getParentGeoFeatureGroup() is None:
                    obj.Label = label
                    return obj
        group = doc.addObject(GROUP_TYPE, GROUP_BASE)
    else:
        group = container.newObject(GROUP_TYPE, GROUP_BASE)
    group.Label = label
    return group


def ensure_handle(varset):
    """Create this joint's handle, or bring an existing one up to date
    (frame, label, and the group it files in). Idempotent — the joint's
    container changes as bents and frames get created around it, and
    every call re-files the handle where the joint now lives. Returns
    the handle. Caller owns the transaction.
    """
    doc = varset.Document
    handle = find_handle(varset)
    created = handle is None
    if created:
        handle = doc.addObject(HANDLE_TYPE, HANDLE_NAME)
        # holds the joint's VarSet (and, later, the companion Layout_
        # VarSet and any created parts). A group extension rather than a
        # ViewProvider's claimChildren, so the nesting is native and
        # survives with the workbench uninstalled — but note the tree
        # only DRAWS it when the view provider carries the matching
        # Gui::ViewProviderGroupExtension (see view_joint_handle).
        handle.addExtension("App::GroupExtensionPython")
        handle.addProperty("App::PropertyLinkGlobal", FRAME_PROP, PROP_GROUP,
                           "The timber joint's landing frame on the anchor "
                           "timber — where this joint sits. The marker "
                           "draws here.")
        handle.Label = handle_label(varset)
    if not hasattr(handle, JOINT_PROP):
        handle.addProperty("App::PropertyLink", JOINT_PROP, PROP_GROUP,
                           "The timber joint this handle stands for — its "
                           "VarSet, holding the joint's parameters.")
    if getattr(handle, JOINT_PROP, None) is not varset:
        setattr(handle, JOINT_PROP, varset)
    frame = anchor_frame(varset)
    if getattr(handle, FRAME_PROP, None) is not frame:
        setattr(handle, FRAME_PROP, frame)
    group = handle_group(doc, joint_container(varset))
    if handle not in group.Group:
        group.addObject(handle)
    # The joint's parameters nest under its handle, so the handle in the
    # tree IS the joint and the VarSet travels with it between bents.
    # addObject moves a member out of whatever group held it (verified).
    # A user who drags the VarSet out to sit beside the handle keeps that
    # arrangement — only one that has drifted out of the joints folder
    # altogether is re-filed.
    home = varset.getParentGroup()
    if home is not handle and home is not group:
        handle.addObject(varset)
    prune_root_group(doc)
    if created and App.GuiUp:
        attach_view(handle)
    return handle


def attach_view(handle):
    """Give a handle its marker ViewProvider. GUI-only, and imported
    here so the App side never reaches for Gui."""
    if not App.GuiUp or handle.ViewObject is None:
        return
    from .view_joint_handle import ViewProviderTimberJointHandle
    ViewProviderTimberJointHandle(handle.ViewObject)


def remove_handle(varset):
    """Delete a joint's handle. The VarSet is left where it is — beside
    the handle in the joints folder — except for an older handle that
    still holds it as a child, which would take it along. Returns True
    when one was removed. Caller owns the transaction."""
    handle = find_handle(varset)
    if handle is None:
        return False
    doc = varset.Document
    if varset in getattr(handle, "Group", []):
        handle_group(doc, joint_container(varset)).addObject(varset)
    doc.removeObject(handle.Name)
    return True


def adopt_handles(doc):
    """Give every timber joint in the document a handle, and re-file the
    ones whose joint has since moved between assemblies. Returns the
    number created. The migration path for documents built before
    handles existed; safe to re-run. Caller owns the transaction."""
    created = 0
    for varset in joint_varsets(doc):
        if find_handle(varset) is None:
            created += 1
        ensure_handle(varset)
    return created


def prune_root_group(doc):
    """Remove the root joints group once it has emptied — its handles
    now live in their bents. Only when empty: a user may have parked
    something there."""
    for obj in list(doc.Objects):
        if obj.TypeId == GROUP_TYPE and not obj.Group \
                and obj.getParentGeoFeatureGroup() is None \
                and obj.Label in (GROUP_BASE,) + LEGACY_GROUP_LABELS:
            doc.removeObject(obj.Name)
