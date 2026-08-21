"""Is this file fit to ship as a joint template?

The linter is a *correctness* bar: it catches wrongness, and every one
of its frame rules only fires once frames exist. A half-built template —
two timbers and no frames at all — lints completely silent, which is a
false green on the one question Save-as-joint-template has to answer.
This module is the *completeness* half: the skeleton every template
carries, stated as rules over the same semantic model, emitting the same
``linter.Finding`` so one report covers both halves.

The rules were lifted from ``tests/test_linter.py``'s
``TemplateSkeletonCompleteness`` mixin, which now asserts against this
module — one implementation, proven by the library controls against
templates known to be complete. Messages cite the build-doc part that
creates the missing piece, so a report reads as a checklist.

Pure Python over the fcstd reader; no FreeCAD import, same as the
linter it sits beside.
"""

from __future__ import annotations

import os

from . import naming
from .fcstd import FcstdDocument, expression_refs
from .linter import ADVISORY, STRICT, Finding, Model, lint_document

# Two timbers, three frames: one Landing per role (the anchor's, and the
# entering timber's end frame) plus the single Mate.
EXPECTED_FRAMES = 3
EXPECTED_LANDING = 2
EXPECTED_MATE = 1

MATE_OFFSET_PATH = ".AttachmentOffset.Base.z"


def _frames(model):
    return [o for o in model.doc.objects.values()
            if o.is_type("Part::LocalCoordinateSystem")]


def _role_of(frame):
    return getattr(frame.prop(naming.FRAME_ROLE_PROP), "value", None)


def _joint_varsets(model):
    """VarSets labelled J-<Kind>-<serial>. Deliberately label-parsed
    rather than taken from Model.kind: a template whose joint VarSet is
    mislabelled is exactly what this check exists to report, and
    TemplateSpec parses the label too."""
    return [vs for vs in model.varsets if naming.parse_joint_label(vs.label)]


def _companions(model):
    return [vs for vs in model.varsets
            if getattr(vs.prop(naming.VARSET_ROLE_PROP), "value", None)
            == naming.VARSET_ROLE_LAYOUT]


def _doc_finding(rule, severity, message):
    """A finding about the document as a whole rather than one object."""
    return Finding(rule, severity, "-", "(document)", message)


# --------------------------------------------------------------------------
# Skeleton rules
# --------------------------------------------------------------------------

def rule_two_timbers(model):
    """Part A: the anchor and the entering timber, each parametric."""
    findings = []
    bodies = model.bodies
    if len(bodies) != 2:
        findings.append(_doc_finding(
            "template-timbers", STRICT,
            f"expected 2 timber bodies (the anchor and the entering "
            f"timber), got {[b.label for b in bodies]} — see Part A"))
    for body in bodies:
        if body.name not in model.dims_of:
            findings.append(Finding(
                "template-timbers", STRICT, body.name, body.label,
                "no Dims VarSet drives this timber's base pad Length — "
                "the body is not parametric — see Part A"))
    return findings


def rule_joint_varset(model):
    """Part B/C: exactly one joint VarSet, and it declares its abbrev."""
    findings = []
    joints = _joint_varsets(model)
    if len(joints) != 1:
        got = [vs.label for vs in joints] or [vs.label for vs in model.varsets]
        findings.append(_doc_finding(
            "template-joint-varset", STRICT,
            f"expected exactly 1 joint VarSet labelled "
            f"J-<Kind>-<serial>, got {got} — the VarSet IS the joint — "
            f"see Part B"))
    for vs in joints:
        abbrev = getattr(vs.prop(naming.TEMPLATE_ABBREV), "value", None)
        if not abbrev:
            findings.append(Finding(
                "template-joint-varset", ADVISORY, vs.name, vs.label,
                f"declares no {naming.TEMPLATE_ABBREV} — Apply-Joint "
                f"rewrites exactly that suffix on every feature label, "
                f"so without one the labels keep the long "
                f"'_J-<Kind>-<serial>' form — see Part C"))
    return findings


def rule_layout_companion(model):
    """Part G.1: the companion holding the length-consuming parameters.

    Advisory when absent — a template without one still applies; it just
    cannot drive a timber's Length from a layout distance, so Drive
    Length refuses on every joint made from it."""
    companions = _companions(model)
    if len(companions) == 1:
        return []
    if not companions:
        return [_doc_finding(
            "template-layout-companion", ADVISORY,
            f"no companion layout VarSet (a VarSet carrying "
            f"{naming.VARSET_ROLE_PROP} = '{naming.VARSET_ROLE_LAYOUT}') "
            f"— joints from this template cannot drive a timber's "
            f"Length from a layout distance — see Part G.1")]
    return [_doc_finding(
        "template-layout-companion", STRICT,
        f"more than one companion layout VarSet "
        f"({[vs.label for vs in companions]}) — a joint may have at "
        f"most one, and the template will not load — see Part G.1")]


def rule_frame_set(model):
    """Parts D, E, F: three frames, every one declaring its role, one
    landing frame owned by each timber."""
    findings = []
    frames = _frames(model)
    if len(frames) != EXPECTED_FRAMES:
        findings.append(_doc_finding(
            "template-frame-set", STRICT,
            f"expected {EXPECTED_FRAMES} joint frames (one landing per "
            f"role plus the single mate), got "
            f"{[f.label for f in frames]} — see Parts D, E and F"))
    for frame in frames:
        if _role_of(frame) not in naming.FRAME_ROLES:
            findings.append(Finding(
                "template-frame-set", STRICT, frame.name, frame.label,
                f"no valid {naming.FRAME_ROLE_PROP} property — the role "
                f"is Tier-2 data read by Preview, Assemble and "
                f"Duplicate, never a label substring — see Parts D and E"))
    landing = [f for f in frames if _role_of(f) == naming.FRAME_ROLE_LANDING]
    mate = [f for f in frames if _role_of(f) == naming.FRAME_ROLE_MATE]
    if len(landing) != EXPECTED_LANDING:
        findings.append(_doc_finding(
            "template-frame-set", STRICT,
            f"expected {EXPECTED_LANDING} "
            f"'{naming.FRAME_ROLE_LANDING}' frames, one per role, got "
            f"{[f.label for f in landing]} — see Parts D and E"))
    if len(mate) != EXPECTED_MATE:
        findings.append(_doc_finding(
            "template-frame-set", STRICT,
            f"expected {EXPECTED_MATE} '{naming.FRAME_ROLE_MATE}' frame "
            f"— only the half that enters carries one — got "
            f"{[f.label for f in mate]} — see Part F"))

    owners = {}
    for frame in landing:
        body = model.owner.get(frame.name)
        owners.setdefault(body.label if body else None, []).append(frame.label)
    if None in owners:
        findings.append(_doc_finding(
            "template-frame-set", STRICT,
            f"landing frame(s) outside any body: {owners[None]} — "
            f"activate the target body before creating a datum, or the "
            f"frame lands at the document root — see Part D"))
        del owners[None]
    expected_owners = sorted(b.label for b in model.bodies)
    if sorted(owners) != expected_owners:
        findings.append(_doc_finding(
            "template-frame-set", STRICT,
            f"each timber gets exactly one landing frame; got {owners} "
            f"for timbers {expected_owners} — see Parts D and E"))
    return findings


def rule_mate_frame_driven_from_joint(model):
    """Part F: the mate frame's offset from the stick end IS the
    clear-span allowance, read from the JOINT VarSet's consumed copy."""
    findings = []
    joints = {vs.name for vs in _joint_varsets(model)}
    for frame in _frames(model):
        if _role_of(frame) != naming.FRAME_ROLE_MATE:
            continue
        paths = {e.path: e.expression for e in frame.expressions}
        if MATE_OFFSET_PATH not in paths:
            findings.append(Finding(
                "template-mate-frame", STRICT, frame.name, frame.label,
                f"no {MATE_OFFSET_PATH} expression — the mate frame's "
                f"offset from the stick end IS the clear-span "
                f"allowance, and a typed literal would not follow an "
                f"author's edit — see Part F"))
            continue
        refs = {t.name for t, _ in
                expression_refs(paths[MATE_OFFSET_PATH], model.doc)}
        if not refs & joints:
            findings.append(Finding(
                "template-mate-frame", STRICT, frame.name, frame.label,
                f"{MATE_OFFSET_PATH} does not reference the joint "
                f"VarSet ({paths[MATE_OFFSET_PATH]!r}) — joint_members "
                f"closes over the literal <<J-Kind-serial>> token, "
                f"which <<Layout_J-Kind-serial>> does not contain, so a "
                f"mate frame reading the companion directly is not a "
                f"joint member — see Part G.1"))
    return findings


def rule_geometry_reads_the_joint_varset(model):
    """Geometry binds to the JOINT VarSet, never to the companion.

    ``joint_members`` closes over the literal ``<<J-Kind-serial>>``
    token, which ``<<Layout_J-Kind-serial>>`` does not contain. A cut
    reading the companion directly is therefore not part of the joint:
    Apply-Joint never clones it, and the applied joint is quietly
    missing that feature. The companion is authoritative for the
    length-consuming parameters, but the joint VarSet carries a consumed
    copy and geometry reads that — the same rule the mate frame follows
    (see Part G.1).
    """
    companions = {vs.name: vs for vs in _companions(model)}
    if not companions:
        return []
    joints = {vs.name for vs in _joint_varsets(model)}
    findings = []
    for obj in model.doc.objects.values():
        if obj.is_type("App::VarSet"):
            continue          # the consumed copy is exactly this binding
        reads_companion, reads_joint = set(), False
        for e in obj.expressions:
            for target, _sub in expression_refs(e.expression, model.doc):
                if target.name in companions:
                    reads_companion.add(companions[target.name].label)
                elif target.name in joints:
                    reads_joint = True
        if reads_companion and not reads_joint:
            findings.append(Finding(
                "template-companion-binding", STRICT, obj.name, obj.label,
                f"binds to the companion layout VarSet "
                f"({', '.join(sorted(reads_companion))}) and to no joint "
                f"VarSet, so it is not part of the joint — Apply-Joint "
                f"closes over the <<J-Kind-serial>> token and would "
                f"never clone this feature. Add a consumed copy of the "
                f"parameter on the joint VarSet and read that — "
                f"see Part G.1"))
    return findings


SKELETON_RULES = [
    rule_two_timbers,
    rule_joint_varset,
    rule_layout_companion,
    rule_frame_set,
    rule_mate_frame_driven_from_joint,
    rule_geometry_reads_the_joint_varset,
]


def skeleton_findings(model):
    """The completeness half, over an already-built linter Model."""
    findings = []
    for rule in SKELETON_RULES:
        findings.extend(rule(model))
    return findings


# --------------------------------------------------------------------------
# The whole bar
# --------------------------------------------------------------------------

def stem_findings(path, model):
    """The file stem is load-bearing: ``kind_token_from_source`` takes
    the user-visible joint kind from it, so 'Joint_BraceMT.FCStd' makes
    every applied joint J-BraceMT-<serial> regardless of what the VarSet
    inside is called. A mismatch is not an error — it is a surprise,
    which is worse in a name a cut list carries."""
    stem = os.path.splitext(os.path.basename(str(path)))[0]
    token = naming.kind_token_from_source(stem)
    findings = []
    for vs in _joint_varsets(model):
        kind = naming.parse_joint_label(vs.label)[0]
        if kind != token:
            findings.append(Finding(
                "template-kind-matches-stem", ADVISORY, vs.name, vs.label,
                f"joint VarSet kind '{kind}' does not match the file "
                f"stem '{stem}' — applied joints take their kind from "
                f"the FILE, so they will be labelled J-{token}-<serial> "
                f"while this VarSet says J-{kind}-<serial>"))
    return findings


def load_findings(path):
    """The real acceptance test: does Apply-Joint's own loader accept
    this file? Imported inside the function — apply_joint reaches for
    FreeCAD-free code only, but keeping the import local leaves this
    module importable from the linter's context unchanged."""
    from .apply_joint import JointError, TemplateSpec
    try:
        TemplateSpec(path)
    except JointError as exc:
        return [_doc_finding(
            "template-loads", STRICT,
            f"Apply-Joint cannot load this file as a template: {exc}")]
    return []


def check(path):
    """Every bar a library template must clear: the linter's rules, the
    skeleton, the file-stem contract, and an actual TemplateSpec load."""
    doc = FcstdDocument.from_file(path)
    model = Model(doc)
    findings = lint_document(doc)
    findings.extend(skeleton_findings(model))
    findings.extend(stem_findings(path, model))
    findings.extend(load_findings(path))
    return findings


def format_report(path, findings):
    """Same shape as the linter's report, with the clean case said out
    loud — a silent report is the one result a user cannot interpret."""
    lines = [f"== {path} =="]
    if not findings:
        lines.append("Clean: no findings. This template is fit to ship.")
        return "\n".join(lines)
    for severity, title in ((STRICT, "MUST FIX"), (ADVISORY, "SHOULD FIX")):
        group = [f for f in findings if f.severity == severity]
        lines.append(f"{title}: {len(group)} finding(s)")
        for f in group:
            lines.append(f"  {f}")
    return "\n".join(lines)
