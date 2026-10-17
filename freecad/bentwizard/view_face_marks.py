"""Face and end marks in the 3D view — a toggle, GUI-only.

Apply Timber Joint and Add Datum ask for a face (+X, -X, +Y, -Y) and an
end (A/B), and nothing in the viewport said which was which. These
marks answer it directly.

**Lettered on the faces, like a chalk mark.** Each face carries its
name painted on it, sized to the face; the ends carry A and B on the end
grain, and each side face a small A and B near its ends, so a post seen
side-on still says which way it runs. Each lettering turns in quarter
turns as the view moves, to read as near level as it can — along a
beam, across a post (`view_text.level`). The lettering is depth-tested
like the timber, so a face turned away is hidden behind the timber and
only the faces you can see are named. The first marks floated beside
each face and were drawn over everything, so the far face's label showed
through the timber and "-X" could be either face in an isometric view
(Adam, 2026-10-11).

**They follow the selection.** While the toggle is on, the timbers
selected — or the timbers of a selected timber joint — are marked, and
nothing else: marking every timber at once piled the labels of a frame
into each other.

**Nothing here is an object.** The marks are a scene graph hung on each
timber Body's existing view provider — no document object, no property,
no Placement, nothing saved. A document opened without the workbench, or
opened with the toggle off, is untouched. Because the nodes sit under
the view provider's root they are *after* its placement transform, so
every position below is in the timber's own coordinates and the marks
follow a body wherever its bent seats it, with no tracking code. They
are unpickable: a click goes through them to the face, which is how a
face is picked for Add Datum and Apply.

The face vocabulary is ``facetable``'s, the same table the datums are
placed against: +X is the face at x = WidthX/2, and so on; end A is
z = 0, end B is z = LengthZ.
"""

from __future__ import annotations

from collections import namedtuple

import FreeCAD as App

from . import facetable
from .timber import dims_varset

# `pivy.coin` is imported inside the drawing functions, not here, so the
# layout arithmetic below stays importable — and therefore testable —
# without a GUI. A name on the wrong face is worse than none, because it
# is believed, so `lettering` is checked headlessly against the face
# table.

_FACE_COLOR = (0.86, 0.60, 0.20)     # timber amber, as the joint marker
_END_COLOR = (0.80, 0.12, 0.12)      # red — ends are not faces; clear of
                                     # grey, and of a blue or green selection
_FONT = "Arial:Bold"
# Letter heights, of the face's width (the section's smaller width on end
# grain). "+X" is about 1.3 heights wide, so at these sizes it fits its
# face whichever way `view_text.level` turns it.
_FACE_HEIGHT = 0.55
_END_HEIGHT = 0.55
_SIDE_END_HEIGHT = 0.35              # the small A/B on a side face
_STAND_OFF = 0.004                   # of the larger section width: just
                                     # proud of the face, never in it
_MIDDLE = 0.35                       # of the height: the middle of a capital,
                                     # above the baseline — the pivot

_NODE_NAME = "BentWizardFaceMarks"
_SHOWN = set()                       # document names with the toggle on
_MARKED = {}                         # document name -> {timber Name}

Lettering = namedtuple("Lettering", (
    "text",
    "place",        # the facetable place it names (or sits on)
    "origin",       # centre of the lettering, timber coordinates (mm)
    "baseline",     # unit direction the text runs along
    "normal",       # unit direction it faces: out of the material
    "height",       # letter height (mm)
    "color",
))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def lettering(width_x, width_y, length_z):
    """[Lettering] for one timber, in its own coordinates.

    Pure arithmetic from the face table: each side face's name lies on
    that face at mid-length, facing out along the row's outward normal
    and running along the timber; A and B lie on the end grain; and a
    small A and B sit near each end of every side face. Every size is
    scaled to the section, never the length, so a 20 ft beam's letters
    are the size of an 8 ft one's."""
    off = max(width_x, width_y) * _STAND_OFF
    half = {"x": width_x / 2.0, "y": width_y / 2.0}
    out = []
    for face in facetable.FACES:
        row = facetable.FACE_TABLE[face]
        ox, oy, _ = row.outward
        face_width = width_y if ox else width_x
        height = face_width * _FACE_HEIGHT
        small = face_width * _SIDE_END_HEIGHT
        inset = min(face_width, length_z * 0.2)

        def at(z):
            return (ox * (half["x"] + off), oy * (half["y"] + off), z)

        along = (0.0, 0.0, 1.0)
        out.append(Lettering(row.display, face, at(length_z / 2.0), along,
                             row.outward, height, _FACE_COLOR))
        out.append(Lettering("A", face, at(inset), along, row.outward,
                             small, _END_COLOR))
        out.append(Lettering("B", face, at(length_z - inset), along,
                             row.outward, small, _END_COLOR))
    end_height = min(width_x, width_y) * _END_HEIGHT
    # on end grain the text runs along timber X, turned so it reads from
    # outside that end: -X on end A (seen from -Z), +X on end B
    out.append(Lettering("A", "EndA", (0.0, 0.0, -off), (-1.0, 0.0, 0.0),
                         facetable.FACE_TABLE["EndA"].outward, end_height,
                         _END_COLOR))
    out.append(Lettering("B", "EndB", (0.0, 0.0, length_z + off),
                         (1.0, 0.0, 0.0), facetable.FACE_TABLE["EndB"].outward,
                         end_height, _END_COLOR))
    return out


def _dims(body):
    """(WidthX, WidthY, LengthZ) in mm for a timber body, or None."""
    vs = dims_varset(body)
    if vs is None:
        return None
    try:
        dims = (float(vs.WidthX), float(vs.WidthY), float(vs.LengthZ))
    except AttributeError:
        return None
    return dims if all(v > 0 for v in dims) else None


def _letters(mark):
    """One lettering, lying on its face and facing out of it."""
    from pivy import coin
    from .view_text import level
    sep = coin.SoSeparator()
    up = _cross(mark.normal, mark.baseline)
    rot = App.Rotation(App.Vector(*mark.baseline), App.Vector(*up),
                       App.Vector(*mark.normal), "ZXY")
    xf = coin.SoTransform()
    xf.translation.setValue(*mark.origin)
    xf.rotation.setValue(*rot.Q)
    sep.addChild(xf)
    # seen from behind — inside the timber, or through a transparent
    # one — the letters would read mirrored: draw the front only
    hints = coin.SoShapeHints()
    hints.vertexOrdering.setValue(coin.SoShapeHints.COUNTERCLOCKWISE)
    hints.shapeType.setValue(coin.SoShapeHints.SOLID)
    sep.addChild(hints)
    color = coin.SoBaseColor()
    color.rgb.setValue(*mark.color)
    sep.addChild(color)
    turn = coin.SoCallback()
    turn.setCallback(level)
    sep.addChild(turn)
    down = coin.SoTranslation()
    down.translation.setValue(0.0, -mark.height * _MIDDLE, 0.0)
    sep.addChild(down)
    font = coin.SoFont()
    font.name.setValue(_FONT)
    font.size.setValue(mark.height)
    sep.addChild(font)
    text = coin.SoAsciiText()
    text.string.setValue(mark.text)
    text.justification.setValue(coin.SoAsciiText.CENTER)
    sep.addChild(text)
    return sep


def _marks_node(body):
    """The full mark set for one timber, or None if it is not a timber."""
    dims = _dims(body)
    if dims is None:
        return None
    from pivy import coin
    marks = coin.SoSeparator()       # depth-tested: the timber hides the
    marks.setName(_NODE_NAME)        # faces turned away from the viewer
    pick = coin.SoPickStyle()
    pick.style.setValue(coin.SoPickStyle.UNPICKABLE)   # a click is the face's
    marks.addChild(pick)
    light = coin.SoLightModel()
    light.model.setValue(coin.SoLightModel.BASE_COLOR)  # flat, readable colour
    marks.addChild(light)
    for mark in lettering(*dims):
        marks.addChild(_letters(mark))
    return marks


def _remove(body):
    vobj = getattr(body, "ViewObject", None)
    root = getattr(vobj, "RootNode", None) if vobj is not None else None
    if root is None:
        return
    for i in reversed(range(root.getNumChildren())):
        if root.getChild(i).getName() == _NODE_NAME:
            root.removeChild(i)


def _add(body):
    vobj = getattr(body, "ViewObject", None)
    if vobj is None or getattr(vobj, "RootNode", None) is None:
        return False
    node = _marks_node(body)
    if node is None:
        return False
    vobj.RootNode.addChild(node)
    return True


def selected_timbers(doc):
    """The timbers the selection in `doc` names, each once: a timber or
    anything in it, or both timbers of a selected timber joint (its
    marker, VarSet, seat or a component) — `variables.subject_of`, the
    mapping the Timber Variables panel follows."""
    import FreeCADGui as Gui
    from . import apply, variables
    out = []
    for obj in Gui.Selection.getSelection(doc.Name):
        subject = variables.subject_of(obj)
        if subject is None:
            continue
        bodies = (apply.joint_bodies(subject)
                  if subject.TypeId == "App::VarSet" else [subject])
        for body in bodies:
            if body is not None and body not in out:
                out.append(body)
    return out


def update(doc):
    """Mark exactly the timbers selected in `doc`, if its toggle is on."""
    if doc is None or doc.Name not in _SHOWN:
        return 0
    want = {b.Name: b for b in selected_timbers(doc)}
    have = _MARKED.get(doc.Name, set())
    for name in have - set(want):
        body = doc.getObject(name)
        if body is not None:
            _remove(body)
    marked = {n for n in have if n in want}
    for name, body in want.items():
        if name not in marked and _add(body):
            marked.add(name)
    _MARKED[doc.Name] = marked
    return len(marked)


def show(doc):
    """Turn the marks on for `doc`: the selected timbers are marked now,
    and whatever is selected later."""
    _SHOWN.add(doc.Name)
    return update(doc)


def hide(doc):
    for name in _MARKED.pop(doc.Name, set()):
        body = doc.getObject(name)
        if body is not None:
            _remove(body)
    _SHOWN.discard(doc.Name)


def shown(doc):
    return doc is not None and doc.Name in _SHOWN


def refresh(doc):
    """Rebuild the marks showing (a section or length edit moves them;
    bodies MOVING needs no refresh — the nodes hang below the view
    provider's placement transform)."""
    if not shown(doc):
        return
    for name in _MARKED.pop(doc.Name, set()):
        body = doc.getObject(name)
        if body is not None:
            _remove(body)
    update(doc)


def toggle(doc):
    if shown(doc):
        hide(doc)
        return False
    show(doc)
    return True


def _report(err):
    App.Console.PrintError(f"BentWizard: face marks: "
                           f"{type(err).__name__}: {err}\n")


_PENDING = [False]


def _follow():
    _PENDING[0] = False
    for name in list(_SHOWN):
        doc = App.listDocuments().get(name)
        if doc is None:
            _SHOWN.discard(name)
            _MARKED.pop(name, None)
            continue
        try:
            update(doc)
        except Exception as err:        # never into FreeCAD's selection chain
            _report(err)


def _schedule(*_args):
    """Follow the selection once it settles: a box or a tree pick sends
    one notification per object."""
    if not _SHOWN or _PENDING[0]:
        return
    _PENDING[0] = True
    from PySide import QtCore
    QtCore.QTimer.singleShot(0, _follow)


class _SelectionObserver:
    addSelection = removeSelection = setSelection = clearSelection = \
        staticmethod(_schedule)


class _FaceMarkObserver:
    def slotRecomputedDocument(self, doc):
        try:
            refresh(doc)
        except Exception as err:
            _report(err)

    def slotDeletedDocument(self, doc):
        _SHOWN.discard(doc.Name)
        _MARKED.pop(doc.Name, None)


_OBSERVERS = []


def install():
    if not _OBSERVERS:
        import FreeCADGui as Gui
        _OBSERVERS.extend((_FaceMarkObserver(), _SelectionObserver()))
        App.addDocumentObserver(_OBSERVERS[0])
        Gui.Selection.addObserver(_OBSERVERS[1])
    return _OBSERVERS[0]
