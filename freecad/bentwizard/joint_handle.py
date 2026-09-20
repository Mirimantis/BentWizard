"""Per-joint handle — the clickable representative of a timber joint.

A timber joint has no single object: it is a VarSet, two paired datums
on two timbers, component bodies and Booleans, and a Fixed joint inside
an assembly. The handle gives it one — an ordinary object linked to the
joint's VarSet and its host datum, marked in the 3D view by a
workbench-drawn marker so an intersection reads as joined at a glance.

Tier 2 by construction: an `App::FeaturePython` carrying a *group*
extension and NO App-level Proxy. Without the workbench it is a plain
container holding native data — nothing to import, nothing to fail, zero
geometric effect (the marker is view-only; the handle owns no Placement
and takes no part in the solve). The ViewProvider is attached only under
a GUI and lives in the Gui document.

Tree home: the handle holds its joint's VarSet and its seat, and files
in a `TimberJoints_<Frame>` Std Group inside the frame the joint's
timbers belong to. Joints whose timbers are in no frame yet fall back to
a bare `TimberJoints` group at the document root.
"""

from __future__ import annotations

import FreeCAD as App

from . import datums, naming

HANDLE_TYPE = "App::FeaturePython"
HANDLE_NAME = "TimberJointHandle"          # internal name; never semantic
HANDLE_PREFIX = "Handle_"                  # Handle_J-HousedMT-001

GROUP_TYPE = "App::DocumentObjectGroup"
GROUP_BASE = "TimberJoints"                # + _<AssemblyLabel> when nested

DATUM_PROP = "Datum"
JOINT_PROP = "Joint"
PROP_GROUP = "TimberJoint"

# Whole-joint operations offered on the marker's context menu, as
# (text, callable(varset)). commands.register() fills this at workbench
# start; the ViewProvider only reads it.
CONTEXT_ACTIONS = []


def handle_label(varset):
    return f"{HANDLE_PREFIX}{varset.Label}"


def is_handle(obj):
    """True for a timber-joint handle: our two link properties on an
    App::FeaturePython. The label is deliberately not part of the test."""
    return (obj.TypeId == HANDLE_TYPE
            and hasattr(obj, JOINT_PROP) and hasattr(obj, DATUM_PROP))


def handle_varset(handle):
    """The joint VarSet a handle stands for, or None — the `Joint` link,
    never the label; a VarSet still held as a group child is the fallback."""
    joint = getattr(handle, JOINT_PROP, None)
    if joint is not None:
        return joint
    for obj in getattr(handle, "Group", []):
        if obj.TypeId == "App::VarSet" and naming.is_joint_varset_label(obj.Label):
            return obj
    return None


def find_handle(varset):
    """The existing handle for a joint, or None (structural first)."""
    doc = varset.Document
    for obj in doc.Objects:
        if is_handle(obj) and handle_varset(obj) is varset:
            return obj
    for obj in doc.getObjectsByLabel(handle_label(varset)):
        if is_handle(obj):
            return obj
    return None


def joint_varsets(doc):
    """Every timber-joint VarSet in a document."""
    return [o for o in doc.Objects
            if o.TypeId == "App::VarSet" and naming.is_joint_varset_label(o.Label)]


def anchor_datum(varset):
    """The datum the marker sits on: the handle's own link, else the
    host datum the VarSet's accessors read, else any paired datum."""
    handle = find_handle(varset)
    d = getattr(handle, DATUM_PROP, None) if handle is not None else None
    if d is not None:
        return d
    d = datums.host_datum(varset)
    if d is not None:
        return d
    pair = datums.datums_of_joint(varset)
    return pair[0] if pair else None


def marker_position(handle, frame):
    """Where the marker draws: the host datum's origin in the handle's
    scene-graph frame. The marker's Coin nodes sit under the handle's
    container assembly (via its TimberJoints_ group), which already
    applies that assembly's placement — so the datum's global position is
    taken back into the container's frame, or an offset bent would draw
    its markers at twice its offset."""
    pos = frame.getGlobalPlacement().Base
    container = handle.getParentGeoFeatureGroup()
    if container is not None:
        pos = container.getGlobalPlacement().inverse().multVec(pos)
    return pos


def joint_container(varset):
    """The frame group a timber joint belongs to, or None — the common
    frame of the two timbers it connects."""
    from .frame import containing_frame
    homes = {containing_frame(owner)
             for owner in (datums.owner(d)
                           for d in datums.datums_of_joint(varset))
             if owner is not None}
    homes.discard(None)
    return homes.pop() if len(homes) == 1 else None


def group_label(container):
    if container is None:
        return GROUP_BASE
    return f"{GROUP_BASE}_{container.Label}"


def handle_group(doc, container=None):
    """Find or create the joints Std Group for a container. Matched by
    label AND TypeId: every FreeCAD Assembly carries its own 'Joints'
    (an Assembly::JointGroup) and must never be hijacked."""
    label = group_label(container)
    for obj in doc.getObjectsByLabel(label):
        if obj.TypeId == GROUP_TYPE:
            return obj
    group = doc.addObject(GROUP_TYPE, GROUP_BASE)
    group.Label = label
    if container is not None:
        container.addObject(group)
    return group


def ensure_handle(varset, host_datum=None):
    """Create this joint's handle, or bring an existing one up to date
    (datum, label, and the group it files in). Idempotent. Returns the
    handle. Caller owns the transaction."""
    doc = varset.Document
    handle = find_handle(varset)
    created = handle is None
    if created:
        handle = doc.addObject(HANDLE_TYPE, HANDLE_NAME)
        # holds the joint's VarSet. A group extension rather than a
        # ViewProvider's claimChildren, so the nesting is native — but the
        # tree only DRAWS it when the view provider carries the matching
        # Gui::ViewProviderGroupExtension (see view_joint_handle).
        handle.addExtension("App::GroupExtensionPython")
        handle.addProperty("App::PropertyLinkGlobal", DATUM_PROP, PROP_GROUP,
                           "The timber joint's host datum — where this joint "
                           "sits. The marker draws here.")
        handle.Label = handle_label(varset)
    if not hasattr(handle, JOINT_PROP):
        handle.addProperty("App::PropertyLink", JOINT_PROP, PROP_GROUP,
                           "The timber joint this handle stands for — its "
                           "VarSet, holding the joint's parameters.")
    if getattr(handle, JOINT_PROP, None) is not varset:
        setattr(handle, JOINT_PROP, varset)
    if host_datum is None:
        host_datum = anchor_datum(varset)
    if getattr(handle, DATUM_PROP, None) is not host_datum:
        setattr(handle, DATUM_PROP, host_datum)
    group = handle_group(doc, joint_container(varset))
    if handle not in group.Group:
        group.addObject(handle)
    # The joint's parameters nest under its handle. A user who drags the
    # VarSet out to sit beside the handle keeps that arrangement — only
    # one that has drifted out of the joints folder altogether is re-filed.
    home = varset.getParentGroup()
    if home is not handle and home is not group:
        handle.addObject(varset)
    prune_root_group(doc)
    if created and App.GuiUp:
        attach_view(handle)
    return handle


def attach_view(handle):
    """Give a handle its marker ViewProvider. GUI-only."""
    if not App.GuiUp or handle.ViewObject is None:
        return
    from .view_joint_handle import ViewProviderTimberJointHandle
    ViewProviderTimberJointHandle(handle.ViewObject)


def remove_handle(varset):
    """Delete a joint's handle, moving a VarSet it still holds out of the
    way first. Returns True when one was removed."""
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
    number created. Safe to re-run."""
    created = 0
    for varset in joint_varsets(doc):
        if find_handle(varset) is None:
            created += 1
        ensure_handle(varset)
    return created


def prune_root_group(doc):
    """Remove the root joints group once it has emptied."""
    for obj in list(doc.Objects):
        if obj.TypeId == GROUP_TYPE and not obj.Group \
                and obj.getParentGeoFeatureGroup() is None \
                and obj.Label == GROUP_BASE:
            doc.removeObject(obj.Name)
