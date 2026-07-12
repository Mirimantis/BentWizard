"""Pure-Python reader for FCStd documents.

Parses Document.xml out of the FCStd zip archive into a light object
model — no FreeCAD import required. This is the file-inspection layer
the linter (and any headless verification) is built on.

Only the property types the linter needs are parsed into Python values;
every property also keeps its raw XML element so rules can dig further
without touching this module.
"""

from __future__ import annotations

import math
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class Expression:
    """One ExpressionEngine binding: `path` on the owning object = `expression`."""
    path: str
    expression: str


@dataclass
class Link:
    """A (object name, sub-element) reference, e.g. ('Origin', 'YZ_Plane.')."""
    obj: str
    sub: str = ""


@dataclass
class Placement:
    px: float = 0.0
    py: float = 0.0
    pz: float = 0.0
    q: tuple = (0.0, 0.0, 0.0, 1.0)
    angle: float = 0.0


@dataclass
class Geometry:
    """One sketch geometry element (line segment, circle, or unhandled)."""
    kind: str                      # "line", "circle", "other"
    type_id: str                   # e.g. "Part::GeomLineSegment"
    construction: bool = False
    start: tuple = None            # line: (x, y)
    end: tuple = None              # line: (x, y)
    center: tuple = None           # circle: (x, y)
    radius: float = None           # circle


@dataclass
class Constraint:
    """One sketch constraint. `type_id` is the Sketcher enum value."""
    type_id: int
    value: float
    first: int
    first_pos: int
    second: int
    second_pos: int
    third: int
    name: str = ""

    # Sketcher::ConstraintType values the linter cares about
    DISTANCE = 6
    DISTANCE_X = 7
    DISTANCE_Y = 8
    SYMMETRIC = 14

    def geo_ids(self):
        """Sketch geometry indices (>= 0) this constraint touches."""
        return [g for g in (self.first, self.second, self.third) if g >= 0]


@dataclass
class Property:
    name: str
    type_id: str
    group: str = None              # non-None marks a dynamic (user-added) property
    doc: str = None
    value: object = None           # float / str / bool / int when scalar
    links: list = field(default_factory=list)      # [Link] for link-type properties
    placement: Placement = None
    expressions: list = field(default_factory=list)  # ExpressionEngine only
    geometry: list = field(default_factory=list)     # GeometryList only
    constraints: list = field(default_factory=list)  # ConstraintList only
    cells: dict = field(default_factory=dict)        # Spreadsheet cells only
    element: object = None         # raw xml.etree Element


@dataclass
class DocObject:
    name: str
    type_id: str
    properties: dict = field(default_factory=dict)

    @property
    def label(self):
        p = self.properties.get("Label")
        return p.value if p and isinstance(p.value, str) else self.name

    def prop(self, name):
        return self.properties.get(name)

    @property
    def expressions(self):
        p = self.properties.get("ExpressionEngine")
        return p.expressions if p else []

    def is_type(self, *prefixes):
        return self.type_id.startswith(prefixes)


def _parse_placement(el):
    return Placement(
        px=float(el.get("Px", 0)), py=float(el.get("Py", 0)), pz=float(el.get("Pz", 0)),
        q=(float(el.get("Q0", 0)), float(el.get("Q1", 0)),
           float(el.get("Q2", 0)), float(el.get("Q3", 1))),
        angle=float(el.get("A", 0)),
    )


def _parse_geometry_list(el):
    geoms = []
    for g in el.findall("Geometry"):
        type_id = g.get("type", "")
        con = g.find("Construction")
        construction = con is not None and con.get("value") == "1"
        line = g.find("LineSegment")
        circle = g.find("Circle")
        if line is not None:
            geoms.append(Geometry(
                kind="line", type_id=type_id, construction=construction,
                start=(float(line.get("StartX")), float(line.get("StartY"))),
                end=(float(line.get("EndX")), float(line.get("EndY"))),
            ))
        elif circle is not None and type_id == "Part::GeomCircle":
            geoms.append(Geometry(
                kind="circle", type_id=type_id, construction=construction,
                center=(float(circle.get("CenterX")), float(circle.get("CenterY"))),
                radius=float(circle.get("Radius")),
            ))
        else:
            geoms.append(Geometry(kind="other", type_id=type_id,
                                  construction=construction))
    return geoms


def _parse_constraint_list(el):
    out = []
    for c in el.findall("Constrain"):
        out.append(Constraint(
            type_id=int(c.get("Type", 0)),
            value=float(c.get("Value", 0)),
            first=int(c.get("First", -2000)),
            first_pos=int(c.get("FirstPos", 0)),
            second=int(c.get("Second", -2000)),
            second_pos=int(c.get("SecondPos", 0)),
            third=int(c.get("Third", -2000)),
            name=c.get("Name", ""),
        ))
    return out


def _parse_property(el):
    prop = Property(
        name=el.get("name"),
        type_id=el.get("type", ""),
        group=el.get("group"),
        doc=el.get("doc"),
        element=el,
    )
    for child in el:
        tag = child.tag
        if tag == "Float":
            prop.value = float(child.get("value"))
        elif tag == "Integer":
            prop.value = int(child.get("value"))
        elif tag == "String":
            prop.value = child.get("value")
        elif tag == "Bool":
            prop.value = child.get("value") == "true"
        elif tag == "Link":
            prop.links.append(Link(obj=child.get("value") or ""))
        elif tag == "LinkSub":
            link = Link(obj=child.get("value") or "")
            subs = [s.get("value") or "" for s in child.findall("Sub")]
            if subs:
                link.sub = subs[0]
                prop.links.append(link)
                for s in subs[1:]:
                    prop.links.append(Link(obj=link.obj, sub=s))
            else:
                prop.links.append(link)
        elif tag == "LinkList":
            for l in child.findall("Link"):
                prop.links.append(Link(obj=l.get("value") or ""))
        elif tag == "LinkSubList":
            for l in child.findall("Link"):
                prop.links.append(Link(obj=l.get("obj") or "",
                                       sub=l.get("sub") or ""))
        elif tag == "XLink":
            name = child.get("name") or ""
            subs = [s.get("value") or "" for s in child.findall("Sub")]
            if subs:
                for s in subs:
                    prop.links.append(Link(obj=name, sub=s))
            elif name:
                prop.links.append(Link(obj=name))
        elif tag == "PropertyPlacement":
            prop.placement = _parse_placement(child)
        elif tag == "ExpressionEngine":
            for e in child.findall("Expression"):
                prop.expressions.append(
                    Expression(path=e.get("path", ""),
                               expression=e.get("expression", "")))
        elif tag == "GeometryList":
            prop.geometry = _parse_geometry_list(child)
        elif tag == "ConstraintList":
            prop.constraints = _parse_constraint_list(child)
        elif tag == "Cells":
            for cell in child.findall("Cell"):
                prop.cells[cell.get("address")] = cell.get("content", "")
    return prop


class FcstdDocument:
    """The parsed Document.xml of one FCStd file."""

    def __init__(self, objects):
        self.objects = objects                     # name -> DocObject
        self.by_label = {}                         # label -> DocObject
        for o in objects.values():
            self.by_label[o.label] = o

    @classmethod
    def from_file(cls, path):
        with zipfile.ZipFile(path) as z:
            with z.open("Document.xml") as f:
                return cls.from_xml(f.read())

    @classmethod
    def from_xml(cls, xml_bytes):
        root = ET.fromstring(xml_bytes)
        types = {}
        for o in root.find("Objects").findall("Object"):
            types[o.get("name")] = o.get("type", "")
        objects = {}
        for o in root.find("ObjectData").findall("Object"):
            name = o.get("name")
            obj = DocObject(name=name, type_id=types.get(name, ""))
            props = o.find("Properties")
            if props is not None:
                for p in props.findall("Property"):
                    parsed = _parse_property(p)
                    obj.properties[parsed.name] = parsed
            objects[name] = obj
        return cls(objects)

    def of_type(self, *prefixes):
        return [o for o in self.objects.values() if o.is_type(*prefixes)]

    def resolve(self, name_or_label):
        """Find an object by internal name first, then by label."""
        return self.objects.get(name_or_label) or self.by_label.get(name_or_label)


# --- Expression reference extraction -------------------------------------

_LABEL_REF = re.compile(r"<<([^<>]+)>>\.([A-Za-z_][A-Za-z0-9_]*)")
_BARE_REF = re.compile(r"(?<![\w.<>])([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)")


def expression_refs(expression, doc):
    """Extract (object, property-name) references from an expression string.

    Handles both `<<Label>>.Prop` and bare `Name.Prop` forms; bare names
    are only accepted when they resolve to a document object.
    Returns a list of (DocObject, prop_name) pairs.
    """
    refs = []
    stripped = expression
    for label, prop in _LABEL_REF.findall(expression):
        obj = doc.resolve(label)
        if obj is not None:
            refs.append((obj, prop))
    stripped = _LABEL_REF.sub(" ", expression)
    for name, prop in _BARE_REF.findall(stripped):
        obj = doc.resolve(name)
        if obj is not None:
            refs.append((obj, prop))
    return refs


# --- Loop building for island analysis -----------------------------------

def sketch_profile_loops(geometry, tol=1e-6):
    """Group non-construction geometry into closed loops.

    Returns (loops, complete) where loops is a list of loops — each either
    ("polygon", [(x, y) vertices]) or ("circle", center, radius) — and
    complete is False when unsupported geometry kinds prevented a full
    analysis (callers should then skip geometric rules rather than guess).
    """
    lines = []
    loops = []
    complete = True
    for g in geometry:
        if g.construction:
            continue
        if g.kind == "line":
            lines.append((g.start, g.end))
        elif g.kind == "circle":
            loops.append(("circle", g.center, g.radius))
        else:
            complete = False

    def same(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol

    remaining = list(lines)
    while remaining:
        start, end = remaining.pop(0)
        chain = [start, end]
        extended = True
        while extended and not same(chain[0], chain[-1]):
            extended = False
            for i, (s, e) in enumerate(remaining):
                if same(chain[-1], s):
                    chain.append(e)
                elif same(chain[-1], e):
                    chain.append(s)
                else:
                    continue
                remaining.pop(i)
                extended = True
                break
        if same(chain[0], chain[-1]) and len(chain) > 3:
            loops.append(("polygon", chain[:-1]))
        else:
            complete = False   # open chain — not a clean profile
    return loops, complete


def point_in_polygon(pt, vertices):
    """Ray-casting point-in-polygon (boundary not considered inside)."""
    x, y = pt
    inside = False
    n = len(vertices)
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def point_segment_distance(pt, a, b):
    px, py = pt
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
