"""Datums — the coordinate systems a timber carries for its joinery.

A datum is a ``Part::LocalCoordinateSystem`` **owned by the timber**,
created before any joinery and surviving every joint swap. A joint is
applied *to* a datum; it never owns one. Placed **directly, never by
attachment** (attached-datum axis mapping produced three separate bugs
in this project), from one row of ``facetable.FACE_TABLE``: the user
picks a face and a station, the tool writes position, rotation and
accessors. Two separate failures came from a human setting the five
placement fields by hand, so nothing here is meant to be typed.

What a datum carries (group ``Datum``, all Tier-2 — visible and editable
without the workbench):

- ``Face``      which face or end it sits on (declared, never guessed)
- ``Station``   where along the host; ``Placement.z`` is bound to it, so
                it cannot go stale, and it may itself be an expression on
                a project VarSet (one ``GirtLine`` moving a whole line
                of joints at once)
- ``WidthU``, ``WidthV``, ``DepthW``  the host's extents along the
                datum's local X, Y and behind it along -Z, bound to the
                timber's own Dims per the face-table row
- ``MateDatum``, ``Joint``  the pairing, as internal-Name STRINGS. Link
                properties cannot cross a Body boundary (scope error on
                the next recompute), expressions can, and strings carry
                no dependency edge at all.

The cross-timber accessors (``HostWidthU`` … ``MateDepthW``) live on the
**joint VarSet**, which reads both datums. A datum never reads another
datum: FreeCAD's dependency graph is object-granular, and mutual
``Mate*`` accessors are a cycle the moment both sides carry them (the
rev-2 Step 0 probe hit exactly that). So a component reads its own
datum for host data and its joint VarSet for the mate's.

Seating: every datum's Z points out of its material, so two paired
datums seat **antiparallel** — coincident origins, Z opposed — with the
180° carried as a rotation about local Y (declared, not derived). The
mover's pose is fully computable (``seat_delta``), which is what lets
the assembly pre-position the timber before the solver sees the joint.
"""

from __future__ import annotations

import math

import FreeCAD as App

from . import facetable, naming
from .facetable import FACE_TABLE, PLACES
from .timber import TimberError, dim_input, dims_varset

DATUM_TYPE = "Part::LocalCoordinateSystem"

# The seat: 180° about the datum's local Y (facetable's rule fixes what
# the in-plane axes mean; this fixes how two of them mate).
FLIP = App.Rotation(App.Vector(0, 1, 0), 180)
FLIP_PLACEMENT = App.Placement(App.Vector(), FLIP)

TOOLTIPS = {
    naming.PROP_FACE:
        "Which face (+X, -X, +Y, -Y) or end (A, B) of its timber this "
        "datum sits on. Declared by the tool that placed it; the "
        "placement and accessors below follow from it.",
    naming.PROP_STATION:
        "Position along the timber's Z (from end A) where the datum "
        "sits. Drives Placement.z — bind it to a project variable to "
        "move a whole line of joints together.",
    "WidthU": "The host timber's extent across the datum's local X.",
    "WidthV": "The host timber's extent along the datum's local Y.",
    "DepthW": "The host timber's extent behind the datum, along -Z "
              "(into the material).",
    naming.PROP_MATE_DATUM:
        "Internal name of the datum this one is paired with (on the "
        "other timber of the joint); empty when unpaired.",
    naming.PROP_JOINT:
        "Internal name of the timber-joint VarSet this datum is paired "
        "under; empty when unpaired.",
}

ACCESSOR_TOOLTIPS = {
    "Host": "The host timber's extent {axis}, read through the host "
            "datum. Written by Apply Timber Joint; do not edit.",
    "Mate": "The entering timber's extent {axis}, read through the "
            "mate datum. Written by Apply Timber Joint; do not edit.",
}
_AXIS_TEXT = {"WidthU": "across the datum's local X",
              "WidthV": "along the datum's local Y",
              "DepthW": "behind the datum (along -Z)"}


class DatumError(ValueError):
    """A datum request that cannot be honored."""


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------

def is_datum(obj):
    """A BentWizard datum: an LCS declaring Face and Station. Structural,
    never label-matched."""
    return (obj.TypeId == DATUM_TYPE
            and hasattr(obj, naming.PROP_FACE)
            and hasattr(obj, naming.PROP_STATION))


def datums_of(body):
    return [o for o in body.Group if is_datum(o)]


def all_datums(doc):
    return [o for o in doc.Objects if is_datum(o)]


def owner(datum):
    """The timber Body a datum belongs to."""
    return datum.getParentGeoFeatureGroup()


def face_of(datum):
    return getattr(datum, naming.PROP_FACE)


def parity(datum):
    return facetable.parity(face_of(datum))


def is_paired(datum):
    return bool(getattr(datum, naming.PROP_MATE_DATUM, ""))


def mate_of(datum):
    name = getattr(datum, naming.PROP_MATE_DATUM, "")
    return datum.Document.getObject(name) if name else None


def joint_of(datum):
    """The joint VarSet a datum is paired under, or None."""
    name = getattr(datum, naming.PROP_JOINT, "")
    return datum.Document.getObject(name) if name else None


def datums_of_joint(varset):
    """The datums paired under a joint VarSet, host first when the
    VarSet's accessors say which is which."""
    doc = varset.Document
    found = [d for d in all_datums(doc)
             if getattr(d, naming.PROP_JOINT, "") == varset.Name]
    host = host_datum(varset)
    if host in found:
        found.remove(host)
        found.insert(0, host)
    return found


def host_datum(varset):
    """The joint's host datum, or None.

    Read from the `HostDatum` record the pairing writes. The fallback
    infers it from the Host* accessor expression the way this used to,
    for a joint paired before that property existed — and it must look
    on the accessor VarSet, not the joint VarSet, for one paired after
    the split but before `HostDatum` was written."""
    name = getattr(varset, naming.PROP_HOST_DATUM, "")
    if name:
        found = varset.Document.getObject(name)
        if found is not None and is_datum(found):
            return found
    holder = accessors_varset(varset)
    for path, expr in holder.ExpressionEngine:
        if path.lstrip(".") == "Host" + facetable.ACCESSORS[0]:
            for d in all_datums(varset.Document):
                if f"<<{d.Label}>>" in expr:
                    return d
    return None


def describe(datum):
    """'+Y @ 48.000 in' — for pickers."""
    face = face_of(datum)
    st = getattr(datum, naming.PROP_STATION)
    return f"{facetable.display(face)} @ {st.UserString}"


# --------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------

def add_datum(body, face, station=None, label=None):
    """Place a datum on `body` at `face` (a facetable.PLACES value).

    `station` is a Quantity / quantity string, or '=<expression>' to
    bind it; required for a side face, defaulted for an end (0 for
    end A, the timber's LengthZ for end B). Returns the LCS. Caller
    owns the transaction.
    """
    if face not in PLACES:
        raise DatumError(f"unknown face {face!r}; one of {', '.join(PLACES)}")
    dims = dims_varset(body)
    if dims is None:
        raise DatumError(f"{body.Label!r} is not a timber (no Dims VarSet "
                         f"drives its base pad)")
    doc = body.Document
    row = FACE_TABLE[face]
    if station is None:
        if row.station is None:
            raise DatumError(f"a datum on face {facetable.display(face)} "
                             f"needs a station")
        station = "=" + row.station.format(dims=dims.Label)
        if row.station == "0":
            station = "0 mm"
    q, expr = dim_input(station)

    if label is None:
        if facetable.is_end(face):
            label = naming.datum_label(body.Label, face)
        else:
            base = f"D_{body.Label}_{face}"
            label = naming.next_serial([o.Label for o in doc.Objects],
                                       base, sep="_")
    if doc.getObjectsByLabel(label):
        raise DatumError(f"label {label!r} already exists")

    d = body.newObject(DATUM_TYPE, naming.object_name(label))
    d.Label = label
    d.MapMode = "Deactivated"
    G = naming.DATUM_GROUP
    d.addProperty("App::PropertyEnumeration", naming.PROP_FACE, G,
                  TOOLTIPS[naming.PROP_FACE])
    setattr(d, naming.PROP_FACE, list(PLACES))
    setattr(d, naming.PROP_FACE, face)
    d.addProperty("App::PropertyDistance", naming.PROP_STATION, G,
                  TOOLTIPS[naming.PROP_STATION])
    for acc in facetable.ACCESSORS:
        d.addProperty("App::PropertyLength", acc, G, TOOLTIPS[acc])
    d.addProperty("App::PropertyString", naming.PROP_MATE_DATUM, G,
                  TOOLTIPS[naming.PROP_MATE_DATUM])
    d.addProperty("App::PropertyString", naming.PROP_JOINT, G,
                  TOOLTIPS[naming.PROP_JOINT])
    try:
        if expr is None:
            setattr(d, naming.PROP_STATION, q)
        else:
            try:
                d.evalExpression(expr)
            except Exception as err:
                raise DatumError(f"Station: bad expression {expr!r} ({err})")
            d.setExpression(naming.PROP_STATION, expr)
        for acc, e in facetable.accessor_expressions(face, dims.Label).items():
            d.setExpression(acc, e)
        d.Placement = App.Placement(App.Vector(),
                                    App.Rotation(App.Vector(*row.axis), row.angle))
        for path, e in facetable.position_expressions(face, dims.Label).items():
            d.setExpression(path, e)
        d.setExpression(".Placement.Base.z", naming.PROP_STATION)
        doc.recompute()
        if "Invalid" in d.State or "Error" in d.State:
            raise DatumError(f"{label}: recompute failed ({d.State})")
        problems = verify_datum(d)
        if problems:
            raise DatumError(f"{label}: " + "; ".join(problems))
    except Exception:
        doc.removeObject(d.Name)
        raise
    return d


def add_end_datums(body):
    """Both end datums, created with the timber. Returns (A, B)."""
    return (add_datum(body, "EndA"), add_datum(body, "EndB"))


def end_datum(body, end):
    """The timber's datum on 'EndA' / 'EndB', or None."""
    for d in datums_of(body):
        if face_of(d) == end:
            return d
    return None


# --------------------------------------------------------------------------
# Pairing
# --------------------------------------------------------------------------

PLACEMENT_TOOLTIPS = {
    "Host": "The host datum's Placement. A component on the host binds its "
            "own Placement to this — never to the datum directly: a Body "
            "reading a datum makes FreeCAD file the datum's axes under "
            "that Body, and the datum then fails its scope check.",
    "Mate": "The mate datum's Placement. A component on the mate binds its "
            "own Placement to this — never to the datum directly (see "
            "HostPlacement).",
}

HOST_DATUM_TOOLTIP = (
    "Which of this joint's two datums is the host — the one that stays "
    "put while the other timber is seated onto it. Written by Apply; "
    "changing it by hand does not re-point anything.")

ACCESSORS_TOOLTIP = (
    "The VarSet holding this joint's accessors — the values it reads "
    "from its two datums, which the joinery is built from. Recorded by "
    "internal name so renaming either VarSet keeps them linked. Written "
    "by Apply; do not edit.")


def _carries_accessors(obj):
    return (obj is not None and obj.TypeId == "App::VarSet"
            and hasattr(obj, naming.placement_accessor("Host")))


def accessors_varset(varset):
    """Where joint `varset`'s accessors live: its own accessor VarSet
    when it has one, otherwise the joint VarSet itself.

    Both shapes are live — a template holds its accessors directly, an
    applied joint holds them on a VarSet of its own, and a document from
    before the split holds them directly too. Resolving it here is what
    lets every caller stay ignorant of which (see `naming`).

    Found by the internal Name the joint records in `Accessors`, which
    survives the framer renaming either VarSet. The `Accessors_<label>`
    lookup is only a fallback, for a joint split before that record
    existed — and it records the Name once found, so it heals."""
    doc = varset.Document
    name = getattr(varset, naming.PROP_ACCESSORS, "")
    if name:
        obj = doc.getObject(name)
        if obj is not varset and _carries_accessors(obj):
            return obj
    for obj in doc.getObjectsByLabel(naming.accessors_label(varset.Label)):
        if obj is not varset and _carries_accessors(obj):
            _record_accessors(varset, obj)
            return obj
    return varset


def _record_accessors(varset, target):
    if not hasattr(varset, naming.PROP_ACCESSORS):
        varset.addProperty("App::PropertyString", naming.PROP_ACCESSORS,
                           naming.ACCESSOR_GROUP, ACCESSORS_TOOLTIP)
    if getattr(varset, naming.PROP_ACCESSORS) != target.Name:
        setattr(varset, naming.PROP_ACCESSORS, target.Name)


def _add_accessor_props(target):
    for side in naming.SIDES:
        for acc in facetable.ACCESSORS:
            name = side + acc
            if not hasattr(target, name):
                target.addProperty(
                    "App::PropertyLength", name, naming.ACCESSOR_GROUP,
                    ACCESSOR_TOOLTIPS[side].format(axis=_AXIS_TEXT[acc]))
        name = naming.placement_accessor(side)
        if not hasattr(target, name):
            target.addProperty("App::PropertyPlacement", name,
                               naming.ACCESSOR_GROUP, PLACEMENT_TOOLTIPS[side])


def ensure_accessors(varset, separate=True):
    """Give joint `varset` its Host*/Mate* accessors and return the object
    that carries them (idempotent).

    `separate` puts them on an `Accessors_<joint>` VarSet filed under the
    joint's handle, which is what an applied joint gets. Template
    authoring passes False to keep the template a single object: every
    template already saved on disk stays valid, and Apply expands the
    accessors as it copies.

    An existing separate VarSet wins regardless, so calling this on an
    already-expanded joint never splits it a second time or silently
    moves the accessors back."""
    existing = accessors_varset(varset)
    if existing is not varset:
        _add_accessor_props(existing)
        return existing
    if not separate:
        _add_accessor_props(varset)
        return varset
    doc = varset.Document
    target = doc.addObject("App::VarSet", "Accessors")
    target.Label = naming.accessors_label(varset.Label)
    _add_accessor_props(target)
    _record_accessors(varset, target)
    _file_accessors(varset, target)
    return target


def _file_accessors(varset, target):
    """Under the joint's handle, beside its seat. Imported here rather
    than at module scope: joint_handle imports this module."""
    try:
        from . import joint_handle
        handle = joint_handle.find_handle(varset)
    except Exception:
        return
    if handle is not None and target.getParentGroup() is not handle:
        handle.addObject(target)


def side_of(varset, datum):
    """'Host' or 'Mate': which side of joint `varset` `datum` is, by the
    VarSet's accessors; None when the datum is not paired under it."""
    pair_ = datums_of_joint(varset)
    if not pair_ or datum not in pair_:
        return None
    return "Host" if pair_[0] is datum else "Mate"


def placement_binding(varset, datum):
    """The expression a component on `datum` binds its Placement to —
    '<<Accessors_J-...>>.HostPlacement' on an applied joint,
    '<<J-...>>.HostPlacement' on a template."""
    side = side_of(varset, datum)
    if side is None:
        raise DatumError(f"{datum.Label!r} is not paired under {varset.Label!r}")
    holder = accessors_varset(varset)
    return f"<<{holder.Label}>>.{naming.placement_accessor(side)}"


def pair(host, mate, varset, separate=True):
    """Pair two datums under a joint VarSet: record the pairing on both
    (strings), record which is the host on the VarSet, and bind the
    Host*/Mate* accessors through them. Refuses a datum that is already
    paired, or two datums on one timber.

    `separate` is passed through to `ensure_accessors` — see there."""
    for d in (host, mate):
        if not is_datum(d):
            raise DatumError(f"{d.Label!r} is not a datum")
        if is_paired(d):
            raise DatumError(f"{d.Label!r} is already paired (joint "
                             f"{getattr(d, naming.PROP_JOINT, '')!r}); "
                             f"remove that timber joint first")
    if owner(host) is owner(mate):
        raise DatumError("both datums belong to the same timber")
    holder = ensure_accessors(varset, separate=separate)
    for acc in naming.ALL_ACCESSORS:
        holder.setExpression("Host" + acc, f"<<{host.Label}>>.{acc}")
        holder.setExpression("Mate" + acc, f"<<{mate.Label}>>.{acc}")
    # which datum is the host, stated rather than inferred from an
    # expression that no longer lives on this object
    if not hasattr(varset, naming.PROP_HOST_DATUM):
        varset.addProperty("App::PropertyString", naming.PROP_HOST_DATUM,
                           naming.ACCESSOR_GROUP, HOST_DATUM_TOOLTIP)
    setattr(varset, naming.PROP_HOST_DATUM, host.Name)
    setattr(host, naming.PROP_MATE_DATUM, mate.Name)
    setattr(mate, naming.PROP_MATE_DATUM, host.Name)
    setattr(host, naming.PROP_JOINT, varset.Name)
    setattr(mate, naming.PROP_JOINT, varset.Name)


def unpair(datum):
    """Clear a pairing on both datums. The joint VarSet's accessors are
    unbound when it still exists (it normally does not — Remove Joint
    deletes it)."""
    mate = mate_of(datum)
    varset = joint_of(datum)
    for d in (datum, mate):
        if d is not None:
            setattr(d, naming.PROP_MATE_DATUM, "")
            setattr(d, naming.PROP_JOINT, "")
    if varset is not None:
        if hasattr(varset, naming.PROP_HOST_DATUM):
            setattr(varset, naming.PROP_HOST_DATUM, "")
        holder = accessors_varset(varset)
        for side in naming.SIDES:
            for acc in facetable.ACCESSORS:
                name = side + acc
                if hasattr(holder, name):
                    holder.setExpression(name, None)
                    setattr(holder, name, 0)
            name = naming.placement_accessor(side)
            if hasattr(holder, name):
                holder.setExpression(name, None)
                setattr(holder, name, App.Placement())


# --------------------------------------------------------------------------
# Seating
# --------------------------------------------------------------------------

def seat_target(host, mate):
    """The global placement the MATE datum must have when seated: the
    host datum's, flipped 180° about local Y."""
    return host.getGlobalPlacement().multiply(FLIP_PLACEMENT)


def seat_delta(host, mate):
    """The global transform that carries the mate's side onto its seat
    (apply to the mover's global placement)."""
    return seat_target(host, mate).multiply(mate.getGlobalPlacement().inverse())


def misfit(host, mate):
    """(mm, degrees) between the seated pose and the actual one."""
    delta = seat_target(host, mate).inverse().multiply(mate.getGlobalPlacement())
    return (delta.Base.Length, math.degrees(delta.Rotation.Angle))


# --------------------------------------------------------------------------
# Verification (finding #10: resolve the placement, never trust a field)
# --------------------------------------------------------------------------

def verify_datum(datum):
    """Problems with a datum against its face-table row, as strings —
    empty when it is exactly what the tool would have written."""
    problems = []
    if not is_datum(datum):
        return [f"{datum.Label!r} is not a datum"]
    face = face_of(datum)
    row = FACE_TABLE[face]
    if datum.MapMode != "Deactivated":
        problems.append(f"MapMode is {datum.MapMode!r}, not Deactivated "
                        f"(datums are placed directly)")
    body = owner(datum)
    dims = dims_varset(body) if body is not None else None
    if dims is None:
        return problems + ["no owning timber"]
    exprs = {p.lstrip("."): e for p, e in datum.ExpressionEngine}
    if exprs.get("Placement.Base.z") != naming.PROP_STATION:
        problems.append("Placement.z is not bound to Station")
    for path, want in facetable.position_expressions(face, dims.Label).items():
        got = exprs.get(path.lstrip("."))
        if got != want:
            problems.append(f"{path} is {got!r}, expected {want!r}")
    for acc, want in facetable.accessor_expressions(face, dims.Label).items():
        got = exprs.get(acc)
        if got != want:
            problems.append(f"{acc} is {got!r}, expected {want!r}")
    q = datum.Placement.Rotation.Q
    if not facetable.same_rotation(q, row.quaternion):
        problems.append(f"rotation {tuple(round(v, 4) for v in q)} is not "
                        f"the {facetable.display(face)} row's "
                        f"{row.quaternion}")
    # resolved position: x/y from the row, z = Station
    want = App.Vector(0, 0, float(getattr(datum, naming.PROP_STATION)))
    ox, oy, _oz = row.outward
    if ox:
        want.x = ox * float(dims.WidthX) / 2
    if oy:
        want.y = oy * float(dims.WidthY) / 2
    if (datum.Placement.Base - want).Length > 1e-6:
        problems.append(f"position {datum.Placement.Base} resolved, "
                        f"expected {want}")
    return problems
