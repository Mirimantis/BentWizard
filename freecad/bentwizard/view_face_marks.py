"""Face and end marks in the 3D view — a toggle, GUI-only.

Apply Timber Joint and Add Datum ask for a face (+X, -X, +Y, -Y) and an
end (A/B), and nothing in the viewport said which was which. These
marks answer it directly.

**Nothing here is an object.** The marks are a scene graph hung on each
timber Body's existing view provider — no document object, no property,
no Placement, nothing saved. A document opened without the workbench, or
opened with the toggle off, is untouched. Because the nodes sit under
the view provider's root they are *after* its placement transform, so
every position below is in the timber's own coordinates and the marks
follow a body wherever its bent seats it, with no tracking code.

The face vocabulary is ``facetable``'s, the same table the datums are
placed against: +X is the face at x = WidthX/2, and so on; end A is
z = 0, end B is z = LengthZ.
"""

from __future__ import annotations

import FreeCAD as App

from . import facetable
from .timber import dims_varset

# `pivy.coin` is imported inside the drawing functions, not here, so the
# placement arithmetic below stays importable — and therefore testable —
# without a GUI. A numeral on the wrong face is worse than none, because
# it is believed, so `mark_positions` is checked headlessly against the
# face table.

_FONT_SIZE = 30.0                    # points; SoText2 is screen-sized
_FACE_COLOR = (0.86, 0.60, 0.20)     # timber amber, as the joint marker
_END_COLOR = (0.45, 0.70, 0.95)      # cool blue — ends are not faces
_OFFSET = 0.12                       # stand-off, as a fraction of the
                                     # section dimension it measures from

_NODE_NAME = "BentWizardFaceMarks"
_SHOWN = set()                       # document names currently marked


def _dims(body):
    """(WidthX, WidthY, LengthZ) in mm for a timber body, or None."""
    vs = dims_varset(body)
    if vs is None:
        return None
    try:
        return (float(vs.WidthX), float(vs.WidthY), float(vs.LengthZ))
    except AttributeError:
        return None


def mark_positions(width_x, width_y, length_z):
    """[(text, (x, y, z), color)] in the timber's own coordinates.

    Pure arithmetic from the face table: each face mark sits at the
    centre of its face, stood off along the face's outward normal; the
    end marks sit beyond the ends on the axis. Every stand-off is
    scaled to the SECTION, not the length, so a 20 ft beam keeps its
    end labels at its ends.
    """
    off = max(width_x, width_y) * _OFFSET
    half = {"x": width_x / 2.0, "y": width_y / 2.0}
    out = []
    for face in facetable.FACES:
        row = facetable.FACE_TABLE[face]
        ox, oy, _ = row.outward
        pos = (ox * (half["x"] + off), oy * (half["y"] + off), length_z / 2.0)
        out.append((row.display, pos, _FACE_COLOR))
    out.append(("A", (0.0, 0.0, -off), _END_COLOR))
    out.append(("B", (0.0, 0.0, length_z + off), _END_COLOR))
    return out


def _label(text, position, color):
    """One screen-aligned label at a body-local position."""
    from pivy import coin
    sep = coin.SoSeparator()

    translation = coin.SoTranslation()
    translation.translation.setValue(*position)
    sep.addChild(translation)

    base = coin.SoBaseColor()
    base.rgb.setValue(*color)
    sep.addChild(base)

    font = coin.SoFont()
    font.size.setValue(_FONT_SIZE)
    sep.addChild(font)

    label = coin.SoText2()
    label.string.setValue(text)
    label.justification.setValue(coin.SoText2.CENTER)
    sep.addChild(label)
    return sep


def _marks_node(body):
    """The full mark set for one timber, or None if it is not a timber."""
    dims = _dims(body)
    if dims is None or not all(v > 0 for v in dims):
        return None
    places = mark_positions(*dims)

    from pivy import coin
    marks = coin.SoAnnotation()
    marks.setName(_NODE_NAME)
    pick = coin.SoPickStyle()
    pick.style.setValue(coin.SoPickStyle.UNPICKABLE)   # never steal a click
    marks.addChild(pick)
    for text, position, color in places:
        marks.addChild(_label(text, position, color))
    return marks


def _existing(vobj):
    root = getattr(vobj, "RootNode", None)
    if root is None:
        return None
    for i in range(root.getNumChildren()):
        child = root.getChild(i)
        if child.getName() == _NODE_NAME:
            return child
    return None


def _timber_bodies(doc):
    return [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]


def show(doc):
    """Mark every timber in `doc`. Idempotent."""
    marked = 0
    for body in _timber_bodies(doc):
        vobj = body.ViewObject
        if vobj is None or getattr(vobj, "RootNode", None) is None:
            continue
        if _existing(vobj) is not None:
            marked += 1
            continue
        node = _marks_node(body)
        if node is None:
            continue
        vobj.RootNode.addChild(node)
        marked += 1
    _SHOWN.add(doc.Name)
    return marked


def hide(doc):
    for body in _timber_bodies(doc):
        vobj = body.ViewObject
        node = _existing(vobj) if vobj is not None else None
        if node is not None:
            vobj.RootNode.removeChild(node)
    _SHOWN.discard(doc.Name)


def shown(doc):
    return doc is not None and doc.Name in _SHOWN


def refresh(doc):
    """Rebuild the marks if they are showing (a section or length edit
    moves them; bodies MOVING needs no refresh — the nodes hang below
    the view provider's placement transform)."""
    if shown(doc):
        hide(doc)
        show(doc)
        _SHOWN.add(doc.Name)


def toggle(doc):
    if shown(doc):
        hide(doc)
        return False
    show(doc)
    return True


class _FaceMarkObserver:
    def slotRecomputedDocument(self, doc):
        refresh(doc)

    def slotDeletedDocument(self, doc):
        _SHOWN.discard(doc.Name)


_OBSERVER = None


def install():
    global _OBSERVER
    if _OBSERVER is None:
        _OBSERVER = _FaceMarkObserver()
        App.addDocumentObserver(_OBSERVER)
    return _OBSERVER
