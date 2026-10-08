"""What sets a timber, or a timber joint: the values a framer edits, and
where each one comes from. The model behind the Timber Variables panel
(`view_variables`). FreeCAD, no GUI, and read-only.

Almost every expression in a frame is plumbing. A datum's WidthU copies
its own timber's WidthX, an accessor VarSet reads two datums, a seat is
the placement formula, a component reads its accessors. Telling plumbing
from a governing value in arbitrary expressions is the hard, general
problem, and this module does not attempt it. It lists the few places
the workbench puts a framer's values (a timber's Dims, a datum's
Station, a timber joint's parameters, the frame origin) and resolves
where each one comes from:

- **here**: a value typed on the property itself;
- **follows**: a single reference, followed to its end. A LengthZ that
  copies another timber's LengthZ, which reads ProjectVars.Span, shows
  Span · ProjectVars; the step in between is kept as `via`;
- **formula**: shown as written, with the values it reads;
- **fixed**: a parameter its template marks ReadOnly.

An expression the workbench did not write, inside a timber or its timber
joints' components, that reads a value outside that plumbing is listed
under "Other", so a hand-added binding is never silently missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import FreeCAD as App

from . import datums, facetable, frame, joint_handle, naming
from .apply import joint_datums, joint_varsets
from .timber import dims_varset, is_timber, timber_bodies

HERE = "here"            # typed on the property itself
FOLLOWS = "follows"      # a chain of single references, ending in a typed value
FORMULA = "formula"      # a formula, on the property or at the end of the chain
FIXED = "fixed"          # ReadOnly: fixed by the joint's template
BROKEN = "broken"        # a reference that names nothing

DIMS = ("WidthX", "WidthY", "LengthZ")

# App::Property::PropDynamic. getPropertyStatus reports it as a bare
# number on 26.3 (['ReadOnly', 21] for a read-only user property).
_PROP_DYNAMIC = 21

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_REF_LABEL = re.compile(naming.LABEL_REF.pattern + rf"\.({_IDENT})")
_REF_BARE = re.compile(rf"(?<![\w.<>])({_IDENT})\.({_IDENT})")
_ONE_LABEL = re.compile(rf"\s*{_REF_LABEL.pattern}\s*")
_ONE_BARE = re.compile(rf"\s*({_IDENT})\.({_IDENT})\s*")
_CAMEL_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


# --------------------------------------------------------------------------
# Reading expressions
# --------------------------------------------------------------------------

def _lookup(doc, text, quoted):
    """The object an expression names: `<<Label>>` by label, a bare name
    by internal Name first, then by label."""
    if quoted:
        hits = doc.getObjectsByLabel(naming.unquote_label(text))
        return hits[0] if hits else None
    obj = doc.getObject(text)
    if obj is not None:
        return obj
    hits = doc.getObjectsByLabel(text)
    return hits[0] if hits else None


def references(doc, expr):
    """[(object, property)] an expression reads, each once, in order.
    A bare `Name.Prop` counts only when it names a real object and
    property, so `Placement.Base` on the object itself is not one."""
    out, seen = [], set()

    def add(obj, prop):
        if obj is not None and hasattr(obj, prop) and (obj.Name, prop) not in seen:
            seen.add((obj.Name, prop))
            out.append((obj, prop))

    for label, prop in _REF_LABEL.findall(expr):
        add(_lookup(doc, label, True), prop)
    for name, prop in _REF_BARE.findall(_REF_LABEL.sub(" ", expr)):
        add(_lookup(doc, name, False), prop)
    return out


def _single(doc, expr):
    """(object or None, property) when `expr` is exactly one reference
    to another object's property; None when it is anything more."""
    m = _ONE_LABEL.fullmatch(expr)
    if m:
        return _lookup(doc, m.group(1), True), m.group(2)
    m = _ONE_BARE.fullmatch(expr)
    if m:
        obj = _lookup(doc, m.group(1), False)
        if obj is not None:
            return obj, m.group(2)
    return None


def expression_of(obj, prop):
    """The expression bound to `obj.prop`, or None."""
    for path, expr in obj.ExpressionEngine:
        if path.lstrip(".") == prop:
            return expr
    return None


def pretty(expr):
    """An expression as the framer reads it: labels without their
    `<<...>>` quoting."""
    return naming.LABEL_REF.sub(lambda m: naming.unquote_label(m.group(1)), expr)


def _read_only(obj, prop):
    try:
        return "ReadOnly" in obj.getPropertyStatus(prop)
    except Exception:
        return False


# --------------------------------------------------------------------------
# Where a value comes from
# --------------------------------------------------------------------------

@dataclass
class Source:
    """Where the value of `start` comes from. `holder.prop` is where it
    is edited: the property itself, the end of a chain of references, or
    the property carrying a formula."""
    kind: str
    start: tuple                                  # (object, property) asked about
    holder: object
    prop: str
    via: list = field(default_factory=list)       # [(object, property)] passed through
    expression: str = ""                          # the formula, or the broken reference
    reads: list = field(default_factory=list)     # [(object, property)] a formula reads

    @property
    def elsewhere(self):
        """True when the value is edited somewhere other than `start`."""
        obj, prop = self.start
        return self.holder.Name != obj.Name or self.prop != prop


def _follow(doc, start, expr):
    chain = [start]
    seen = {(start[0].Name, start[1])}
    while True:
        cur, name = chain[-1]
        if expr is None:
            if len(chain) == 1:
                kind = FIXED if _read_only(cur, name) else HERE
            else:
                kind = FOLLOWS
            return Source(kind, start, cur, name, chain[1:-1])
        one = _single(doc, expr)
        if one is None:
            return Source(FORMULA, start, cur, name, chain[1:-1], expr,
                          references(doc, expr))
        nxt, prop = one
        if nxt is None or not hasattr(nxt, prop) or (nxt.Name, prop) in seen:
            return Source(BROKEN, start, cur, name, chain[1:-1], expr)
        seen.add((nxt.Name, prop))
        chain.append((nxt, prop))
        expr = expression_of(nxt, prop)


def resolve(obj, prop):
    """Where the value of `obj.prop` comes from, as a Source."""
    return _follow(obj.Document, (obj, prop), expression_of(obj, prop))


def resolve_expression(obj, path, expr):
    """A Source for an expression bound at any `path` on `obj` — a
    sketch constraint's, say, which is not a property of its own."""
    return _follow(obj.Document, (obj, path.lstrip(".")), expr)


def leaf_keys(source, _depth=0):
    """{(object Name, property)} every value `source` finally rests on:
    its holder, and for a formula each value the formula reads, followed
    to its own end."""
    keys = {(source.holder.Name, source.prop)}
    if source.kind == FORMULA and _depth < 8:
        for obj, prop in source.reads:
            keys |= leaf_keys(resolve(obj, prop), _depth + 1)
    return keys


# --------------------------------------------------------------------------
# Words
# --------------------------------------------------------------------------

def spaced(name):
    """'TenonLength' -> 'Tenon Length', as FreeCAD's property editor
    shows it."""
    return _CAMEL_BREAK.sub(" ", name)


def face_words(datum):
    """'+Y face' or 'End B' for a datum."""
    face = datums.face_of(datum)
    shown = facetable.display(face)
    return shown if facetable.is_end(face) else f"{shown} face"


def _owning_timber(obj):
    parent = obj.getParentGeoFeatureGroup()
    return parent if parent is not None and is_timber(parent) else None


def holder_name(obj):
    """How the panel names the object holding a value: the timber for a
    timber's Dims VarSet, the timber and face for a datum, else its
    label."""
    if datums.is_datum(obj):
        body = datums.owner(obj)
        return f"{body.Label if body is not None else '?'} {face_words(obj)}"
    if obj.TypeId == "App::VarSet":
        body = _owning_timber(obj)
        if body is not None and dims_varset(body) is obj:
            return body.Label
    return obj.Label


def location(obj, prop):
    """'Span · ProjectVars': a variable and the object holding it."""
    return f"{spaced(prop)} · {holder_name(obj)}"


def describe(source):
    """The 'Var. Location' text for a Source: always the variable where
    the value is edited, so a typed value reads like a shared one; a
    fixed parameter and a formula say so after it."""
    if source.kind == BROKEN:
        return f"broken reference: {pretty(source.expression)}"
    text = location(source.holder, source.prop)
    if source.kind == FIXED:
        text += " (fixed)"
    elif source.kind == FORMULA:
        text += f" = {pretty(source.expression)}"
    return text


def chain_text(source):
    """The tooltip: how the value gets there. A chain reads 'T-Beam-002
    .LengthZ ← T-Beam-001.LengthZ ← ProjectVars.Span'."""
    obj, prop = source.start
    if source.kind == HERE:
        return (f"Typed in on {holder_name(obj)}'s {spaced(prop)}; "
                f"not read from another variable.")
    if source.kind == FIXED:
        return (f"Fixed by its template: {holder_name(obj)}'s {spaced(prop)} "
                f"is read-only.")
    steps = [source.start] + list(source.via)
    if source.elsewhere:
        steps.append((source.holder, source.prop))
    text = " ← ".join(f"{holder_name(o)}.{p}" for o, p in steps)
    if source.kind == FORMULA:
        text += f" = {pretty(source.expression)}"
    elif source.kind == BROKEN:
        text += f" ← {pretty(source.expression)}, which names nothing"
    return text


def format_value(value):
    """A property value in the framer's unit schema."""
    if hasattr(value, "UserString"):
        return value.UserString
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, App.Placement):
        base = value.Base
        text = ", ".join(App.Units.Quantity(c, App.Units.Length).UserString
                         for c in (base.x, base.y, base.z))
        if abs(value.Rotation.Angle) > 1e-9:
            text += ", rotated"
        return text
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def value_text(obj, prop):
    try:
        return format_value(getattr(obj, prop))
    except Exception:
        return "?"


def _section_location(body):
    return f"Width X × Width Y · {body.Label}"


def section_text(body):
    """A timber's section, 'WidthX × WidthY'."""
    dims = dims_varset(body)
    if dims is None:
        return "?"
    return f"{dims.WidthX.UserString} × {dims.WidthY.UserString}"


# --------------------------------------------------------------------------
# The listing
# --------------------------------------------------------------------------

@dataclass
class Row:
    label: str
    value: str
    set_by: str
    target: object = None        # selected when the row is clicked
    source: Source = None
    tip: str = ""
    own: frozenset = frozenset() # timber Names the row is about
    drives: list = field(default_factory=list)   # other timbers' labels


@dataclass
class Section:
    title: str
    rows: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    target: object = None        # selected when the heading is clicked


@dataclass
class Listing:
    subject: object
    title: str
    subtitle: str = ""
    sections: list = field(default_factory=list)


def _value_row(obj, prop, label=None, own=frozenset()):
    src = resolve(obj, prop)
    return Row(label or spaced(prop), value_text(obj, prop), describe(src),
               target=src.holder, source=src, tip=chain_text(src), own=own)


def joint_parameters(varset):
    """The names of a timber joint's parameters: the user-added
    properties the framer edits, in the VarSet's order."""
    out = []
    for name in varset.PropertiesList:
        try:
            status = varset.getPropertyStatus(name)
        except Exception:
            continue
        if _PROP_DYNAMIC not in status:
            continue
        if naming.is_joint_parameter(name, varset.getGroupOfProperty(name)):
            out.append(name)
    return out


def _joint_timbers(varset):
    """Names of the timbers a joint's datums sit on."""
    return frozenset(b.Name for b in (datums.owner(d) for d in joint_datums(varset))
                     if b is not None)


def _station_row(datum, label, own):
    return _value_row(datum, naming.PROP_STATION, label=label, own=own)


def _position_section(body):
    s = Section("Position")
    own = frozenset({body.Name})
    tp = frame.timber_placement(body)
    if tp.state == frame.ANCHORED:
        s.notes.append("Anchored: this timber sets the frame's position; "
                       "every seated timber is placed from it.")
        s.rows.append(_value_row(body, frame.PLACEMENT, label="Frame Origin", own=own))
    elif tp.state == frame.SEATED and tp.joint is not None:
        anchor = tp.anchor
        s.target = tp.joint
        s.notes.append(f"Seated on {anchor.Label if anchor else '?'} "
                       f"by {tp.joint.Label}.")
        chain = [b for _seat, b in frame.seat_path(body)]
        root = frame.root_of(body)
        labels = [b.Label for b in chain] + [root.Label]
        how = ("the anchored timber" if frame.is_anchored(root)
               else "provisional, not tied to the frame yet")
        if len(labels) > 2:
            s.notes.append(f"Placed through {' → '.join(labels)} ({how}).")
        else:
            s.notes.append(f"{root.Label} is {how}.")
        mates = _joint_timbers(tp.joint)
        for d in joint_datums(tp.joint):
            if facetable.is_end(datums.face_of(d)):
                continue
            b = datums.owner(d)
            where = ("this timber" if b is not None and b.Name == body.Name
                     else (b.Label if b is not None else "?"))
            s.rows.append(_station_row(d, f"Station on {where}, {face_words(d)}",
                                       mates))
    elif tp.state == frame.PROVISIONAL:
        s.notes.append("Provisional: timbers are seated from it, but no timber "
                       "joint ties it to the frame yet.")
    elif tp.state == frame.EXPRESSION:
        s.rows.append(_value_row(body, frame.PLACEMENT, own=own))
    else:
        s.notes.append("Loose: no timber joint places it.")
    return s


def _parameter_rows(varset, own):
    return [_value_row(varset, name, own=own) for name in joint_parameters(varset)]


def _joint_section(varset, body, shown=frozenset()):
    """One timber joint, as seen from `body`. A datum whose Station is in
    `shown` (the Position group's, already listed) is not listed again."""
    s = Section(f"Timber joint {varset.Label}", target=varset)
    own = _joint_timbers(varset)
    pair = joint_datums(varset)
    mine = [d for d in pair if (datums.owner(d) or body).Name == body.Name]
    theirs = [d for d in pair if d not in mine]
    if mine and theirs:
        other = datums.owner(theirs[0])
        s.notes.append(f"This timber's {face_words(mine[0])} meets "
                       f"{other.Label}'s {face_words(theirs[0])}.")
    for d in mine:
        if not facetable.is_end(datums.face_of(d)) and d.Name not in shown:
            s.rows.append(_station_row(d, f"Station on this timber, {face_words(d)}",
                                       own))
    s.rows += _parameter_rows(varset, own)
    for d in theirs:
        other = datums.owner(d)
        if other is None:
            continue
        if not facetable.is_end(datums.face_of(d)) and d.Name not in shown:
            s.rows.append(_station_row(d, f"Station on {other.Label}, {face_words(d)}",
                                       own))
        s.rows.append(Row(f"Mating Timber {other.Label}", section_text(other),
                          _section_location(other), target=dims_varset(other) or other,
                          tip=f"{other.Label}'s WidthX × WidthY: the timber joint's "
                              f"cut follows it.", own=own))
    return s


# --- Other: hand-added bindings --------------------------------------------

def _plumbing(obj, scope_names):
    """True for an object whose values are the workbench's own wiring,
    or already listed: datums, accessor and seat VarSets, timber joint
    VarSets, and anything in `scope_names` (the timbers and Dims being
    listed)."""
    if obj.Name in scope_names or datums.is_datum(obj):
        return True
    if obj.TypeId == "App::VarSet":
        return (naming.is_accessors_label(obj.Label) or frame.is_seat(obj)
                or naming.is_joint_varset_label(obj.Label))
    return False


def _component_bodies(varset):
    from .apply import joint_components
    return joint_components(varset)


def _other_section(bodies, scope_names, own):
    """Expressions inside `bodies` that read a value outside the
    workbench's plumbing — a hand-added binding."""
    s = Section("Other")
    for body in bodies:
        doc = body.Document
        for obj in body.Group:
            if datums.is_datum(obj) or obj.TypeId == "App::VarSet":
                continue
            for path, expr in obj.ExpressionEngine:
                outside = [o for o, _p in references(doc, expr)
                           if o.Name != obj.Name
                           and o.getParentGeoFeatureGroup() is not body
                           and not _plumbing(o, scope_names)]
                if not outside:
                    continue
                src = resolve_expression(obj, path, expr)
                try:
                    value = format_value(obj.evalExpression(expr))
                except Exception:
                    value = "?"
                s.rows.append(Row(f"{obj.Label} · {_path_words(path)}", value,
                                  describe(src),
                                  target=src.holder if src.elsewhere else obj,
                                  source=src, tip=chain_text(src), own=own))
    return s


def _path_words(path):
    parts = path.lstrip(".").split(".")
    if len(parts) == 2 and parts[0] == "Constraints":
        return f"{parts[1]} constraint"
    return ".".join(parts)


# --- The two listings -----------------------------------------------------

def timber_listing(body, index=None):
    """What sets a timber: its section and length, its position, each
    timber joint on it, datums not yet paired, and hand-added bindings."""
    doc = body.Document
    own = frozenset({body.Name})
    dims = dims_varset(body)
    tag = getattr(dims, naming.PROP_POSITION_TAG, "") if dims is not None else ""
    listing = Listing(body, body.Label, tag)
    s = Section("Section and Length", target=dims)
    for prop in DIMS:
        if dims is not None and hasattr(dims, prop):
            s.rows.append(_value_row(dims, prop, own=own))
    listing.sections.append(s)
    position = _position_section(body)
    listing.sections.append(position)
    shown = frozenset(r.source.start[0].Name for r in position.rows
                      if r.source is not None and datums.is_datum(r.source.start[0]))

    joints, loose = [], []
    for d in datums.datums_of(body):
        vs = datums.joint_of(d)
        if vs is not None:
            if vs.Name not in {j.Name for j in joints}:
                joints.append(vs)
        elif not facetable.is_end(datums.face_of(d)):
            loose.append(d)
    if loose:
        s = Section("Datums")
        s.notes.append("Not paired with a timber joint yet.")
        for d in loose:
            s.rows.append(_station_row(d, f"Station, {face_words(d)}", own))
        listing.sections.append(s)
    joints.sort(key=lambda j: j.Label)
    for vs in joints:
        listing.sections.append(_joint_section(vs, body, shown))

    scope = {body.Name} | ({dims.Name} if dims is not None else set())
    comps = [c for vs in joints for c in _component_bodies(vs)]
    other = _other_section([body] + comps, scope, own)
    if other.rows:
        listing.sections.append(other)
    fill_drives(listing, index if index is not None else drives_index(doc))
    return listing


def joint_listing(varset, index=None):
    """What sets a timber joint: the two timbers it joins, where it sits
    on each, its parameters, and hand-added bindings in its components."""
    doc = varset.Document
    own = _joint_timbers(varset)
    kind = naming.parse_joint_label(varset.Label)
    listing = Listing(varset, f"Timber joint {varset.Label}",
                      f"{kind[0]} timber joint" if kind else "")
    s = Section("Timbers")
    jp = frame.joint_placement(varset)
    s.notes.append({
        frame.PLACES: f"Places {jp.placed.Label if jp.placed else '?'}.",
        frame.CLOSES: "Closes a loop: places nothing; checked for fit.",
        frame.UNSEATED: "Not seated yet: Seat Timbers can seat it.",
        frame.UNPAIRED: "Not paired: its two datums are not on two timbers.",
    }.get(jp.state, ""))
    scope = set()
    for d in joint_datums(varset):
        b = datums.owner(d)
        if b is None:
            continue
        dims = dims_varset(b)
        scope |= {b.Name} | ({dims.Name} if dims is not None else set())
        s.rows.append(Row(f"{b.Label}, {face_words(d)}", section_text(b),
                          _section_location(b),
                          target=dims or b,
                          tip=f"{b.Label}'s WidthX × WidthY, and the face or end "
                              f"the timber joint is on.", own=own))
        if not facetable.is_end(datums.face_of(d)):
            s.rows.append(_station_row(d, f"Station on {b.Label}, {face_words(d)}",
                                       own))
    listing.sections.append(s)
    s = Section("Parameters", target=varset)
    s.rows = _parameter_rows(varset, own)
    listing.sections.append(s)
    other = _other_section(_component_bodies(varset), scope, own)
    if other.rows:
        listing.sections.append(other)
    fill_drives(listing, index if index is not None else drives_index(doc))
    return listing


# --------------------------------------------------------------------------
# What each value also drives
# --------------------------------------------------------------------------

def drives_index(doc):
    """{(object Name, property): {timber Name}}: for every value the
    listings show, the timbers resting on it. A shared value (Span on
    ProjectVars) collects every timber that reads it."""
    index = {}

    def add(source, timbers):
        for key in leaf_keys(source):
            index.setdefault(key, set()).update(timbers)

    for body in timber_bodies(doc):
        own = {body.Name}
        dims = dims_varset(body)
        for prop in DIMS:
            if dims is not None and hasattr(dims, prop):
                add(resolve(dims, prop), own)
        for d in datums.datums_of(body):
            if facetable.is_end(datums.face_of(d)):
                continue
            vs = datums.joint_of(d)
            add(resolve(d, naming.PROP_STATION),
                own | (_joint_timbers(vs) if vs is not None else set()))
        if frame.placement_expression(body) and frame.is_anchored(body):
            add(resolve(body, frame.PLACEMENT), own)
    for vs in joint_varsets(doc):
        timbers = _joint_timbers(vs)
        for name in joint_parameters(vs):
            add(resolve(vs, name), timbers)
    return index


def fill_drives(listing, index):
    """Set each row's `drives`: the labels of other timbers resting on
    the same values, leaving out the timbers the row is about."""
    doc = listing.subject.Document
    for section in listing.sections:
        for row in section.rows:
            if row.source is None:
                continue
            names = set()
            for key in leaf_keys(row.source):
                names |= index.get(key, set())
            names -= row.own
            labels = [doc.getObject(n).Label for n in names
                      if doc.getObject(n) is not None]
            row.drives = sorted(labels)


def drives_text(labels, limit=3):
    """'T-Beam-002, T-Beam-003' — at most `limit` names, then '+N more'."""
    if len(labels) <= limit:
        return ", ".join(labels)
    return f"{', '.join(labels[:limit])} +{len(labels) - limit} more"


# --------------------------------------------------------------------------
# From the selection
# --------------------------------------------------------------------------

def _is_component(obj):
    return (obj is not None and obj.TypeId == "PartDesign::Body"
            and hasattr(obj, naming.PROP_COMPONENT_ROLE))


def _component_of(obj):
    """The component body `obj` is, sits in, applies (a Boolean) or
    mirrors, or None."""
    if _is_component(obj):
        return obj
    if obj.TypeId == "Part::Mirroring":
        src = getattr(obj, "Source", None)
        return src if _is_component(src) else None
    if obj.TypeId == "PartDesign::Boolean":
        for op in getattr(obj, "Group", []) or []:
            found = _component_of(op)
            if found is not None:
                return found
        return None
    parent = obj.getParentGeoFeatureGroup()
    return parent if _is_component(parent) else None


def _accessors_of(varset):
    """The joint's accessor VarSet, found the way `datums.accessors_varset`
    finds it but without its self-healing write: this runs on every
    selection change and must not touch the document."""
    doc = varset.Document
    name = getattr(varset, naming.PROP_ACCESSORS, "")
    obj = doc.getObject(name) if name else None
    if obj is not None:
        return obj
    hits = doc.getObjectsByLabel(naming.accessors_label(varset.Label))
    return hits[0] if hits else varset


def _joint_of_component(body):
    labels = set()
    for o in [body] + list(body.Group):
        for _path, expr in o.ExpressionEngine:
            labels.update(naming.referenced_labels(expr))
    for vs in joint_varsets(body.Document):
        if vs.Label in labels or _accessors_of(vs).Label in labels:
            return vs
    return None


def subject_of(obj):
    """The timber Body or timber joint VarSet a selected object belongs
    to, or None. A joint's handle, VarSet, accessors, seat, components,
    mirrorings and Booleans give the joint; a timber, its features, its
    Dims and its datums give the timber."""
    if obj is None:
        return None
    if joint_handle.is_handle(obj):
        return joint_handle.handle_varset(obj)
    if obj.TypeId == "App::VarSet":
        if naming.is_joint_varset_label(obj.Label):
            return obj
        if frame.is_seat(obj):
            return frame.joint_of_seat(obj)
        for vs in joint_varsets(obj.Document):
            if _accessors_of(vs) is obj:
                return vs
    comp = _component_of(obj)
    if comp is not None:
        return _joint_of_component(comp)
    if is_timber(obj):
        return obj
    return _owning_timber(obj)


def listing_for(subject, index=None):
    """The listing for a subject from `subject_of`."""
    if subject is None:
        return None
    if subject.TypeId == "App::VarSet":
        return joint_listing(subject, index)
    return timber_listing(subject, index)
