"""Drive a timber's Length from a layout distance (roadmap: Parametric
layout).

The inversion: instead of typing a stick length and letting the solver
put the far post wherever the joinery lands, the framer authors the
layout distance and the stick length derives from it.

Two bases, because framers use both:

    O.C.   Length = distance + sum(Stick_Allowance_OC)
           centerline to centerline; each allowance is
           tenon + housing - half the landing timber's thickness

    F.T.F. Length = distance + sum(Stick_Allowance_FTF)
           clear span, face to face; each allowance is just
           tenon + housing — the half-thickness terms cancel

Both allowances are measured along the entering timber's own axis, so
the sums are angle-blind and serve diagonals unchanged.

**The basis belongs to the distance, not to the tool.** A variable is
an on-center number or a clear-span number for good, so there is no
mode a user can set wrongly; and which allowance a driven Length sums
IS the basis, so it reads back structurally rather than from a name.

Only joints this timber ENTERS contribute: the entering half is the one
whose stick length the joinery consumes. A post carrying a tie's
mortise is unaffected by that joint.

No GUI imports — the dialog in commands.py is a thin wrapper.
"""

from __future__ import annotations

import re

from . import naming
from .apply_joint import dims_varset, layout_varset

# Where a hand-authored distance lands when the tool creates one.
# 'Project_' is an accepted VarSet kind, so the linter stays quiet.
DEFAULT_SPAN_VARSET = "Project_Main"
SPAN_GROUP = "Grid"
SPAN_TOOLTIP = {
    naming.BASIS_OC: (
        "On-Center (O.C.) distance — centerline of one timber to "
        "centerline of the next. Stick lengths derive from it; edit "
        "here to move the bay."),
    naming.BASIS_FTF: (
        "Clear span (Face-to-Face) — the open distance between the two "
        "timbers this one lands on. Stick lengths derive from it; edit "
        "here to move the bay."),
}


class SpanError(ValueError):
    """A layout-distance request that cannot be honored."""


def _basis_prop(basis):
    try:
        return naming.ALLOWANCE_FOR_BASIS[basis]
    except KeyError:
        raise SpanError(f"unknown layout basis {basis!r} — "
                        f"one of {', '.join(naming.BASES)}")


def allowance_ref(companion, basis):
    """The expression term naming a companion's allowance for `basis`."""
    return f"<<{companion.Label}>>.{_basis_prop(basis)}"


def entering_joints(body):
    """[(joint VarSet, companion)] for every timber joint this body
    ENTERS and that publishes allowances, in document order.

    The entering half is resolved structurally, from the engagement
    frames — the mate-frame carrier — never from labels or roles.
    """
    from .assemble import _engagement_frames
    from .joint_handle import joint_varsets
    out = []
    for varset in joint_varsets(body.Document):
        pair = _engagement_frames(varset)
        if pair is None:
            continue
        (mover, _mate), (_anchor, _landing) = pair
        if mover is not body:
            continue
        companion = layout_varset(varset)
        if companion is not None and any(
                hasattr(companion, p)
                for p in naming.ALLOWANCE_FOR_BASIS.values()):
            out.append((varset, companion))
    return out


def available_bases(body):
    """Bases this timber can actually be driven on.

    Clear span needs exactly two ends to be between: a timber entering
    one joint, or three, has no meaningful face-to-face distance, while
    on-center stays well defined however many ends there are.
    """
    joints = entering_joints(body)
    if not joints:
        return ()
    if len(joints) == 2:
        return (naming.BASIS_OC, naming.BASIS_FTF)
    return (naming.BASIS_OC,)


def span_expression(span_ref, companions, basis):
    """`<distance> + <allowance> + ...` — the driven-Length expression."""
    return " + ".join([span_ref]
                      + [allowance_ref(c, basis) for c in companions])


def driving_span(body):
    """(distance term, basis) of a timber's driven Length, or None.

    The basis comes from which allowance the expression sums — the
    structure, never a name.
    """
    dims = dims_varset(body)
    if dims is None:
        return None
    for path, expr in dims.ExpressionEngine:
        if path.lstrip(".") != "Length":
            continue
        for basis in naming.BASES:
            if naming.ALLOWANCE_FOR_BASIS[basis] in expr:
                return expr.split("+")[0].strip(), basis
    return None


def _sum(companions, prop):
    total = 0.0
    for c in companions:
        value = getattr(c, prop, None)
        total += value.Value if hasattr(value, "Value") else float(value or 0)
    return total


def readout(body, distance_mm, basis):
    """{'OC', 'FTF', 'Length'} in mm for a proposed distance.

    What the dialog shows live: a framer types a clear span and sees
    the on-center it implies, or the reverse, plus the stick it will
    cut. Seeing all three is what stops the two bases being confused —
    a mismatch is visible instead of silent. 'FTF' is None when the
    timber has other than two ends to be between.
    """
    companions = [c for _v, c in entering_joints(body)]
    if not companions:
        raise SpanError(f"{body.Label!r} enters no timber joint that "
                        f"publishes a stick allowance")
    setback = _sum(companions, naming.GRID_SETBACK_PROP)
    two_ended = len(companions) == 2
    if basis == naming.BASIS_OC:
        oc = distance_mm
        ftf = distance_mm - setback if two_ended else None
    elif basis == naming.BASIS_FTF:
        if not two_ended:
            raise SpanError(
                f"{body.Label!r} lands on {len(companions)} timber(s) — "
                f"a clear span needs exactly two to be between")
        ftf = distance_mm
        oc = distance_mm + setback
    else:
        _basis_prop(basis)                      # raises with the valid list
    length = distance_mm + _sum(companions, _basis_prop(basis))
    return {"OC": oc, "FTF": ftf, "Length": length}


def ensure_span_property(doc, prop_name, value, basis=naming.BASIS_OC,
                         varset_label=None):
    """Find or create a layout distance to bind to, returning its
    `<<VarSet>>.Prop` reference.

    The inline 'new distance' path: a framer should not have to
    hand-author a VarSet before the tool is usable (CLAUDE.md audience
    note). An existing property of that name is reused, never
    overwritten — the point of a layout distance is that several bays
    share one.
    """
    label = varset_label or DEFAULT_SPAN_VARSET
    if not prop_name or not prop_name.isidentifier():
        raise SpanError(
            f"{prop_name!r} is not a usable property name — letters, "
            f"digits and underscores, not starting with a digit")
    _basis_prop(basis)
    holder = None
    for obj in doc.getObjectsByLabel(label):
        if obj.TypeId == "App::VarSet":
            holder = obj
            break
    if holder is None:
        holder = doc.addObject("App::VarSet", "ProjectVars")
        holder.Label = label
    if not hasattr(holder, prop_name):
        holder.addProperty("App::PropertyLength", prop_name, SPAN_GROUP,
                           SPAN_TOOLTIP[basis])
        setattr(holder, prop_name, value)
    return f"<<{holder.Label}>>.{prop_name}"


def suggested_name(base, basis):
    """'Bay' + O.C. -> 'Bay_Dist_OC'. The suffix advertises the basis so
    a name read on its own is not ambiguous."""
    return f"{base}{naming.BASIS_SUFFIX[basis]}"


def drive_length(body, span_ref, basis=naming.BASIS_OC):
    """Bind `body`'s Dims.Length to `span_ref` plus its joints'
    allowances for `basis`. Returns the resolved length (a Quantity).

    Refuses rather than leaving a broken document: a binding that will
    not evaluate, or that resolves to a non-positive length, is rolled
    back to whatever drove Length before. Caller owns the transaction.
    """
    _basis_prop(basis)          # before anything formats a message with it
    dims = dims_varset(body)
    if dims is None:
        raise SpanError(
            f"{body.Label!r} has no Dims VarSet driving its base pad — "
            f"is it a BentWizard timber?")
    joints = entering_joints(body)
    if not joints:
        raise SpanError(
            f"{body.Label!r} does not enter any timber joint that "
            f"publishes a stick allowance — apply its end joints first "
            f"(and use a template that declares a layout VarSet)")
    if basis not in available_bases(body):
        raise SpanError(
            f"{body.Label!r} lands on {len(joints)} timber(s) — "
            f"{naming.BASIS_LABEL[basis]} needs exactly two to be "
            f"between; use {naming.BASIS_LABEL[naming.BASIS_OC]}")
    companions = [c for _v, c in joints]
    expression = span_expression(span_ref, companions, basis)

    previous = None
    for path, expr in dims.ExpressionEngine:
        if path.lstrip(".") == "Length":
            previous = expr
    before = dims.Length

    def restore():
        dims.setExpression("Length", previous)
        if previous is None:
            dims.Length = before
        body.Document.recompute()

    try:
        dims.setExpression("Length", expression)
        body.Document.recompute()
    except Exception as exc:
        restore()
        raise SpanError(f"{body.Label}: {expression} — {exc}")
    if "Invalid" in dims.State or "Error" in dims.State:
        restore()
        raise SpanError(
            f"{body.Label}: the distance expression did not evaluate — "
            f"check that {span_ref} exists and is a length")
    if dims.Length.Value <= 0:
        resolved = dims.Length.UserString
        restore()
        raise SpanError(
            f"{body.Label}: that distance gives a stick length of "
            f"{resolved} — it is shorter than the joinery it has to "
            f"carry")
    return dims.Length


def _split_ref(span_ref):
    """'<<Project_Main>>.Bay_Dist_OC' -> ('Project_Main', 'Bay_Dist_OC'),
    or None when the term is not a plain VarSet reference."""
    match = re.fullmatch(r"\s*<<([^<>]+)>>\.([A-Za-z_][A-Za-z0-9_]*)\s*",
                         span_ref or "")
    return match.groups() if match else None


def references_to(doc, span_ref):
    """[(object, property path)] still consuming a layout distance.

    Two forms have to be caught, not one: other objects name it
    `<<Label>>.Prop`, but the holder's OWN expressions reference a
    sibling property bare — `Bay_Dist_OC * 2` — so a qualified-only
    scan would call a distance unused while its own VarSet still
    derives from it.
    """
    parts = _split_ref(span_ref)
    if parts is None:
        return []
    label, prop = parts
    qualified = f"<<{label}>>.{prop}"
    bare = re.compile(rf"(?<![\w.]){re.escape(prop)}(?![\w])")
    holders = {o.Name for o in doc.getObjectsByLabel(label)}
    out = []
    for obj in doc.Objects:
        for path, expr in (getattr(obj, "ExpressionEngine", None) or []):
            if qualified in expr or (obj.Name in holders
                                     and path.lstrip(".") != prop
                                     and bare.search(expr)):
                out.append((obj, path.lstrip(".")))
    return out


def remove_distance(doc, span_ref):
    """Delete an unused layout distance. Returns True when removed.

    Refuses while anything still consumes it — a distance is shared on
    purpose, so a bay elsewhere may be living on it. Caller owns the
    transaction.
    """
    parts = _split_ref(span_ref)
    if parts is None:
        raise SpanError(f"{span_ref!r} is not a plain VarSet reference")
    label, prop = parts
    still = references_to(doc, span_ref)
    if still:
        raise SpanError(
            f"{prop} is still used by "
            f"{', '.join(sorted({o.Label for o, _p in still}))}")
    for obj in doc.getObjectsByLabel(label):
        if obj.TypeId == "App::VarSet" and hasattr(obj, prop):
            obj.removeProperty(prop)
            return True
    return False


def freeze_length(body):
    """Stop driving a timber's Length, keeping its current value.

    Returns True when a driven Length was frozen.
    """
    dims = dims_varset(body)
    if dims is None or driving_span(body) is None:
        return False
    resolved = dims.Length
    dims.setExpression("Length", None)
    dims.Length = resolved
    return True


def freeze_allowance_term(companion):
    """Replace every reference to `companion`'s allowances with their
    resolved values, wherever they are consumed.

    Called when a joint is removed. Dropping the term outright would
    shrink the stick by the tenon it just lost and shove the far post
    along with it, mid-delete; freezing that ONE term leaves the
    geometry exactly where it is while the distance keeps driving the
    rest (roadmap: 'reverting the term to the resolved literal').
    Returns the objects whose expressions were rewritten.
    """
    doc = companion.Document
    touched = []
    for prop in naming.ALLOWANCE_FOR_BASIS.values():
        if not hasattr(companion, prop):
            continue
        ref = f"<<{companion.Label}>>.{prop}"
        value = getattr(companion, prop)
        # Raw internal value with an explicit unit, never UserString:
        # that renders under the user's DISPLAY schema, and under
        # Building US a zero allowance comes out as a bare '0' with no
        # unit at all — adding a unitless number to a length is a unit
        # error, so the timber's Length went Invalid the moment a
        # zero-allowance joint was removed. Parenthesised so a negative
        # allowance cannot turn 'distance + -3 mm' into a parse error.
        mm = value.Value if hasattr(value, "Value") else float(value or 0)
        literal = f"({mm} mm)"
        for obj in doc.Objects:
            if obj is companion:
                continue
            for path, expr in (getattr(obj, "ExpressionEngine", None) or []):
                if ref not in expr:
                    continue
                try:
                    obj.setExpression(path.lstrip("."),
                                      expr.replace(ref, literal))
                    touched.append(obj)
                except Exception:
                    # never block a removal on a rewrite we cannot make;
                    # the caller's own recompute surfaces the breakage
                    pass
    return touched
