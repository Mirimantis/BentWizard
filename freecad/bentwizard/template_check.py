"""The template bar: what makes a joint file a template.

The linter's rules fire on what a document *contains*; a half-built
template — two timbers and nothing else — lints completely silent. The
rules here assert the **skeleton** a template must carry: two timbers,
one joint VarSet, a pairing under it, and components that are declared,
placed on the paired datums and applied by a matching Boolean. Same
``linter.Finding``, same strict/advisory split; ``check(path)`` is the
whole pure-Python bar, ``check_geometry(path)`` the FreeCAD half —
one solid per timber, growth direction, and the parameter sweep that
finds the silent two-solid holes round 3 found (finding #14 relocated
to authoring time). Everything **reports, never blocks**.
"""

from __future__ import annotations

from pathlib import Path

from . import naming, template_library
from .fcstd import FcstdDocument
from .linter import ADVISORY, STRICT, Finding, Model, lint_document

SWEEP_STEPS = 12
SWEEP_DEFAULT_RANGE = (0.25, 1.5)      # x default, when no range is declared


# --------------------------------------------------------------------------
# Skeleton rules (pure)
# --------------------------------------------------------------------------

def rule_two_timbers(model):
    timbers = model.timbers()
    if len(timbers) == 2:
        return []
    return [Finding("template-timbers", STRICT, "", "template",
                    f"a joint template holds exactly two timbers (host and "
                    f"mate), found {len(timbers)}: "
                    f"{', '.join(b.label for b in timbers) or 'none'}")]


def rule_joint_varset(model):
    joints = model.joint_varsets()
    if len(joints) != 1:
        return [Finding("template-joint-varset", STRICT, "", "template",
                        f"a template holds exactly one joint VarSet "
                        f"(J-<Kind>-000), found {len(joints)}: "
                        f"{', '.join(v.label for v in joints) or 'none'}")]
    vs = joints[0]
    out = []
    parsed = naming.parse_joint_label(vs.label)
    if parsed is None:
        out.append(Finding("template-joint-varset", ADVISORY, vs.name, vs.label,
                           "joint VarSet label should read 'J-<Kind>-000'"))
    elif parsed[1] != naming.TEMPLATE_SERIAL:
        out.append(Finding("template-joint-varset", ADVISORY, vs.name, vs.label,
                           f"a template's own joint serial is "
                           f"{naming.TEMPLATE_SERIAL!r}; Apply allocates real "
                           f"serials from 001"))
    return out


def rule_pairing(model):
    joints = model.joint_varsets()
    if len(joints) != 1:
        return []
    vs = joints[0]
    host = model.accessor_datum(vs, "Host")
    mate = model.accessor_datum(vs, "Mate")
    if host is None or mate is None:
        return [Finding("template-pairing", STRICT, vs.name, vs.label,
                        "the joint VarSet's Host*/Mate* accessors do not name "
                        "two datums — pair a datum on each timber under it")]
    owners = {model.datum_owner(d).name if model.datum_owner(d) else None
              for d in (host, mate)}
    timbers = {b.name for b in model.timbers()}
    if len(owners) != 2 or not owners <= timbers:
        return [Finding("template-pairing", STRICT, vs.name, vs.label,
                        f"the paired datums {host.label!r} and {mate.label!r} "
                        f"must sit one on each template timber")]
    out = []
    for d in (host, mate):
        j = model.datum_joint(d)
        if j is not vs:
            out.append(Finding("template-pairing", STRICT, d.name, d.label,
                               f"datum is not paired under {vs.label!r}"))
    return out


def rule_components(model):
    joints = model.joint_varsets()
    if len(joints) != 1:
        return []
    vs = joints[0]
    paired = {d.name for d in (model.accessor_datum(vs, "Host"),
                               model.accessor_datum(vs, "Mate")) if d is not None}
    out = []
    booleans = model.doc.of_type("PartDesign::Boolean")
    for comp in model.components:
        datum = model.component_datum(comp)
        if datum is None:
            continue                # the linter's component-declaration says so
        if datum.name not in paired:
            out.append(Finding("template-components", STRICT, comp.name, comp.label,
                               f"placed on {datum.label!r}, which is not one of "
                               f"the joint's paired datums"))
            continue
        timber = model.datum_owner(datum)
        holder = model.component_placement_holder(comp)
        holders = {comp.name, holder.name if holder else comp.name}
        applying = [b for b in booleans
                    if any(l.obj in holders for l in (b.prop("Group").links
                                                      if b.prop("Group") else []))]
        role = comp.prop(naming.PROP_COMPONENT_ROLE).value
        want = naming.BOOLEAN_OP.get(role)
        if not applying:
            out.append(Finding("template-components", STRICT, comp.name, comp.label,
                               f"no Boolean applies this {role.lower() if role else 'component'} "
                               f"to {timber.label!r} — add a PartDesign "
                               f"{want or 'Boolean'} with the component as its "
                               f"operand"))
            continue
        for b in applying:
            if model.owner.get(b.name) is not timber:
                out.append(Finding("template-components", STRICT, b.name, b.label,
                                   f"applies {comp.label!r} inside "
                                   f"'{model.owner.get(b.name).label if model.owner.get(b.name) else '?'}', "
                                   f"but the component's datum is on {timber.label!r}"))
            t = b.prop("Type")
            op = t.value if t else None
            if isinstance(op, int):
                op = ["Fuse", "Cut", "Common"][op] if 0 <= op < 3 else op
            if want and op != want:
                out.append(Finding("template-components", STRICT, b.name, b.label,
                                   f"is a {op}, but a {role} is applied with {want}"))
    return out


def rule_ranges(model):
    out = []
    for vs in model.joint_varsets():
        for p in vs.properties.values():
            if p.group is None:
                continue
            base = naming.range_base(p.name)
            if base is None or not naming.is_range_property(p.name, p.group):
                continue
            name, bound = base
            param = vs.prop(name)
            if param is None or param.group is None:
                out.append(Finding("template-ranges", ADVISORY, vs.name, vs.label,
                                   f"{p.name} declares a range for {name!r}, "
                                   f"which is not a parameter"))
                continue
            if isinstance(p.value, (int, float)) and isinstance(param.value, (int, float)):
                if bound == "Min" and param.value < p.value:
                    out.append(Finding("template-ranges", ADVISORY, vs.name, vs.label,
                                       f"{name}'s default is below {p.name}"))
                if bound == "Max" and param.value > p.value:
                    out.append(Finding("template-ranges", ADVISORY, vs.name, vs.label,
                                       f"{name}'s default is above {p.name}"))
    return out


def rule_handed(model):
    """A template declares whether it is handed. Undeclared keeps the
    mirror rule, so it is safe — but it pays for a mirroring (and an
    out-of-scope link warning on every GUI recompute) that a symmetric
    joint never needs."""
    out = []
    for vs in model.joint_varsets():
        p = vs.prop(naming.PROP_TEMPLATE_HANDED)
        if p is None or not isinstance(p.value, bool):
            out.append(Finding("template-handed", ADVISORY, vs.name, vs.label,
                               f"declare '{naming.PROP_TEMPLATE_HANDED}' (a Bool in "
                               f"group '{naming.TEMPLATE_META_GROUP}'): False when "
                               f"the joint looks the same from either side, so "
                               f"Apply never mirrors it; True when it has a hand"))
    return out


SKELETON_RULES = [rule_two_timbers, rule_joint_varset, rule_pairing,
                  rule_components, rule_ranges, rule_handed]


def skeleton_findings(doc):
    model = Model(doc)
    out = []
    for rule in SKELETON_RULES:
        out.extend(rule(model))
    return out


def stem_findings(path, doc):
    """The file stem is the joint's kind; a VarSet saying otherwise is
    reported (Apply takes the kind from the FILE)."""
    stem_kind = naming.template_kind_from_stem(Path(path).stem)
    out = []
    for vs in Model(doc).joint_varsets():
        parsed = naming.parse_joint_label(vs.label)
        if parsed and parsed[0] != stem_kind:
            out.append(Finding("template-stem", ADVISORY, vs.name, vs.label,
                               f"file stem names the kind {stem_kind!r} but the "
                               f"joint VarSet says {parsed[0]!r} — Save as Joint "
                               f"Template offers to relabel"))
    return out


def load_findings(path):
    """The real acceptance test: does TemplateSpec load it?"""
    from .template import JointError, TemplateSpec
    try:
        TemplateSpec(path)
    except JointError as err:
        return [Finding("template-load", STRICT, "", Path(path).stem, str(err))]
    return []


def check(path):
    """Every pure finding for a template file: lint + skeleton + stem +
    load. No FreeCAD needed."""
    doc = FcstdDocument.from_file(path)
    return (lint_document(doc) + skeleton_findings(doc)
            + stem_findings(path, doc) + load_findings(path))


# --------------------------------------------------------------------------
# Geometry (FreeCAD)
# --------------------------------------------------------------------------

def _sweep_domain(spec, name):
    p = spec.parameter(name)
    if p is None or not p["numeric"] or p["type"] == "App::PropertyInteger":
        return None
    default = p["default"]
    if not isinstance(default, (int, float)) or p["expression"]:
        return None
    lo = p["min"] if p["min"] is not None else default * SWEEP_DEFAULT_RANGE[0]
    hi = p["max"] if p["max"] is not None else default * SWEEP_DEFAULT_RANGE[1]
    if hi <= lo:
        return None
    return lo, hi


SYMMETRY_TOLERANCE = 1e-6          # relative volume mismatch


def is_mirror_symmetric(shape):
    """Whether a component, in its own (datum) frame, is its own mirror
    image across local X — the mirror Apply would otherwise apply."""
    import FreeCAD as App
    volume = shape.Volume
    if volume <= 0:
        return True
    mirrored = shape.mirror(App.Vector(0, 0, 0), App.Vector(1, 0, 0))
    overlap = shape.common(mirrored).Volume
    return abs(volume - overlap) <= SYMMETRY_TOLERANCE * volume


def _handedness_findings(spec, body):
    """A component declared not handed must be symmetric, or Apply puts
    it on the wrong side at a datum of the other parity (STRICT). A
    handed template whose components are all symmetric pays for a
    mirroring it never needs (ADVISORY, per component)."""
    from . import measure
    symmetric = is_mirror_symmetric(measure.local_shape(body))
    if spec.handed is False and not symmetric:
        return [Finding("template-handed", STRICT, body.Name, body.Label,
                        f"the template says {naming.PROP_TEMPLATE_HANDED} = False, "
                        f"but this component is not its own mirror image across "
                        f"its datum's X — applied at a datum of the other parity "
                        f"(the opposite face or end) it would land on the wrong "
                        f"side. Set {naming.PROP_TEMPLATE_HANDED} = True")]
    if spec.handed is True and symmetric:
        return [Finding("template-handed", ADVISORY, body.Name, body.Label,
                        f"this component is its own mirror image; if every "
                        f"component is, set {naming.PROP_TEMPLATE_HANDED} = False "
                        f"and Apply will not mirror it")]
    return []


def check_geometry(path, persist=True):
    """FreeCAD half of the bar, on a copy opened hidden: each timber one
    solid at defaults; each component's solid on the correct side of its
    origin, and symmetric if the template says it is not handed; and
    every numeric parameter swept across its declared range
    (or 25-150 % of its default), recording where a timber stops being
    one valid solid. With `persist`, the sweep result is written to the
    VarSet's SweepFindings so the apply dialog can warn from it."""
    import FreeCAD as App
    from . import datums, measure
    from .template import JointError, TemplateSpec
    try:
        spec = TemplateSpec(path)
    except JointError:
        return []                      # load_findings already said so
    out = []
    with template_library.open_hidden(path) as doc:
        doc.recompute()
        timbers = [doc.getObjectsByLabel(r)[0] for r in spec.roles
                   if doc.getObjectsByLabel(r)]
        for t in timbers:
            if not measure.is_whole(t):
                out.append(Finding("template-geometry", STRICT, t.Name, t.Label,
                                   f"{measure.solid_count(t)} solids at the "
                                   f"template's default parameters"))
        for c in spec.components:
            body = doc.getObject(c["name"])
            if body is None:
                continue
            bb = measure.local_shape(body).BoundBox
            if c["role"] == naming.COMPONENT_CUTTER and bb.ZMax > 1e-6:
                out.append(Finding("growth-direction", ADVISORY, body.Name, body.Label,
                                   f"a cutter is modelled in -Z, but this one "
                                   f"reaches to z = {bb.ZMax:.3f} mm"))
            if c["role"] == naming.COMPONENT_ADDER and bb.ZMin < -1e-6:
                out.append(Finding("growth-direction", ADVISORY, body.Name, body.Label,
                                   f"an adder is modelled in +Z, but this one "
                                   f"reaches to z = {bb.ZMin:.3f} mm"))
            out.extend(_handedness_findings(spec, body))
        vs = doc.getObjectsByLabel(spec.varset_label)
        vs = vs[0] if vs else None
        failures = []
        if vs is not None and spec.components:
            for p in spec.parameters:
                domain = _sweep_domain(spec, p["name"])
                if domain is None:
                    continue
                original = getattr(vs, p["name"])
                lo, hi = domain
                for i in range(SWEEP_STEPS):
                    value = lo + (hi - lo) * i / (SWEEP_STEPS - 1)
                    setattr(vs, p["name"], value)
                    doc.recompute()
                    bad = [t for t in timbers
                           if "Invalid" in t.State or not measure.is_whole(t)]
                    if bad:
                        failures.append((p["name"], value, [t.Label for t in bad]))
                setattr(vs, p["name"], original)
                doc.recompute()
            text = "; ".join(f"{n} = {v:.3f} mm -> {', '.join(b)}"
                             for n, v, b in failures)
            for n, v, b in failures:
                out.append(Finding("template-sweep", ADVISORY, vs.Name, vs.Label,
                                   f"at {n} = {App.Units.Quantity(v, 'mm').UserString} "
                                   f"the timber(s) {', '.join(b)} stop being one "
                                   f"valid solid"))
            if persist:
                if not hasattr(vs, naming.PROP_SWEEP_FINDINGS):
                    vs.addProperty("App::PropertyString", naming.PROP_SWEEP_FINDINGS,
                                   naming.TEMPLATE_META_GROUP,
                                   "Parameter values at which the template's "
                                   "timbers stop being one valid solid, found "
                                   "by the registration sweep. Empty = none.")
                setattr(vs, naming.PROP_SWEEP_FINDINGS, text)
                doc.recompute()
                doc.save()
    return out


def format_report(path, findings):
    lines = [f"== {Path(path).name} =="]
    if not findings:
        lines.append("Clean: lints strict and advisory silent, skeleton "
                     "complete, loads as a template.")
        return "\n".join(lines)
    for severity, title in ((STRICT, "STRICT"), (ADVISORY, "ADVISORY")):
        group = [f for f in findings if f.severity == severity]
        if group:
            lines.append(f"{title}: {len(group)} finding(s)")
            for f in group:
                lines.append(f"  {f}")
    return "\n".join(lines)
