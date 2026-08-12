"""Face numbers and end labels in the 3D view — a toggle, GUI-only.

Apply Timber Joint asks for a face (1–4) and an end (A/B), and nothing in
the viewport said which was which; you had to hold the convention in your
head and check the result. These marks answer it directly.

**Nothing here is an object.** The marks are a scene graph hung on each
timber Body's existing view provider — no document object, no property,
no Placement, nothing saved. A document opened without the workbench, or
opened with the toggle off, is untouched, which is a stronger guarantee
than the joint handle can make (it is at least a real group holding a
VarSet). Because the nodes sit under the view provider's root they are
*after* its placement transform, so every position below is in the
timber's own coordinates and the marks follow a body wherever its bent
seats it, with no tracking code.

The face convention is the workflow document's, and it is the same table
`apply_joint.FACES` places joints against:

    Face 1  the XZ reference face, y = 0        Face 3  opposite it
    Face 2  the YZ reference face, x = 0        Face 4  opposite it
    End A   z = 0                               End B   z = Length

Reference-face crow's-foot marks are a separate, later job (roadmap):
they are drawn at *half* the reference edge's width precisely so a framer
cannot mistake them for a carpenter's triangle, which is a real drawing
convention rather than decoration, and it deserves its own pass.
"""

from __future__ import annotations

import FreeCAD as App

from .apply_joint import dims_varset

# `pivy.coin` is imported inside the drawing functions, not here, so the
# placement arithmetic below stays importable — and therefore testable —
# without a GUI. Getting face 1 and face 3 the wrong way round is exactly
# the kind of error that costs a GUI-test round trip, so `mark_positions`
# is checked headlessly against apply_joint.FACES.

_FONT_SIZE = 30.0                    # points; SoText2 is screen-sized
_FACE_COLOR = (0.86, 0.60, 0.20)     # timber amber, as the joint marker
_END_COLOR = (0.45, 0.70, 0.95)      # cool blue — ends are not faces
_OFFSET = 0.12                       # stand-off, as a fraction of the
                                     # section dimension it measures from

# node name we tag our own scene graph with, so hide() can find exactly
# what show() added and never touch anything else in the view provider
_NODE_NAME = "BentWizardFaceMarks"

_SHOWN = set()                       # document names currently marked


def _dims(body):
    """(Width, Depth, Length) in mm for a timber body, or None.

    Read from the body's Dims VarSet — resolved structurally by
    `dims_varset`, from the base pad's Length expression, so a renamed
    VarSet still answers. A body without one is not a BentWizard timber
    and gets no marks.
    """
    vs = dims_varset(body)
    if vs is None:
        return None
    try:
        return (float(vs.Width), float(vs.Depth), float(vs.Length))
    except AttributeError:
        return None


def mark_positions(width, depth, length):
    """[(text, (x, y, z), color)] in the timber's own coordinates.

    Pure arithmetic, no scene graph — the face convention is the one
    thing here worth testing, and this is the piece that holds it.

    Faces 1 and 2 are the REFERENCE faces and sit at zero (y = 0 and
    x = 0); 3 and 4 are opposite them, at Depth and Width. That pairing
    is what makes `apply_joint.FACES[n]["ddim"]` come out as it does —
    faces 1/3 are perpendicular to Y so their through-dimension is
    Depth, faces 2/4 perpendicular to X so theirs is Width.

    Every label stands off by the same distance, scaled to the SECTION
    (not the length): a 4x4 and a 12x12 both read, while a 20 ft beam
    keeps its end labels at the ends instead of flinging them two feet
    into space, which is what scaling the along-axis stand-off by length
    does.
    """
    off = max(width, depth) * _OFFSET
    mid = length / 2.0
    return [
        ("1", (width / 2.0, -off, mid), _FACE_COLOR),
        ("2", (-off, depth / 2.0, mid), _FACE_COLOR),
        ("3", (width / 2.0, depth + off, mid), _FACE_COLOR),
        ("4", (width + off, depth / 2.0, mid), _FACE_COLOR),
        ("A", (width / 2.0, depth / 2.0, -off), _END_COLOR),
        ("B", (width / 2.0, depth / 2.0, length + off), _END_COLOR),
    ]


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
    # justify about the point, so a numeral sits centred on its face
    label.justification.setValue(coin.SoText2.CENTER)
    sep.addChild(label)
    return sep


def _marks_node(body):
    """The full mark set for one timber, or None if it is not a timber."""
    dims = _dims(body)
    if dims is None:
        return None
    if not all(v > 0 for v in dims):
        return None
    places = mark_positions(*dims)

    from pivy import coin
    # SoAnnotation draws last and ignores the depth buffer, so a numeral
    # on the far side of a post stays readable instead of being swallowed
    # by the timber — the same reason the joint marker uses it.
    marks = coin.SoAnnotation()
    marks.setName(_NODE_NAME)
    pick = coin.SoPickStyle()
    pick.style.setValue(coin.SoPickStyle.UNPICKABLE)   # never steal a click
    marks.addChild(pick)
    for text, position, color in places:
        marks.addChild(_label(text, position, color))
    return marks


def _existing(vobj):
    """Our node already on this view provider, or None."""
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
    """Remove every mark from `doc`. Safe to call when nothing is shown."""
    for body in _timber_bodies(doc):
        vobj = body.ViewObject
        node = _existing(vobj) if vobj is not None else None
        if node is not None:
            vobj.RootNode.removeChild(node)
    _SHOWN.discard(doc.Name)


def shown(doc):
    return doc is not None and doc.Name in _SHOWN


def refresh(doc):
    """Rebuild the marks if they are showing.

    Positions are computed from the Dims VarSet, so a section or length
    edit moves them; nothing in the scene graph recomputes itself. Bodies
    *moving* needs no refresh at all — the nodes hang below the view
    provider's placement transform.
    """
    if shown(doc):
        hide(doc)
        show(doc)
        _SHOWN.add(doc.Name)


def toggle(doc):
    """Flip the marks for `doc`; returns True if they are now showing."""
    if shown(doc):
        hide(doc)
        return False
    show(doc)
    return True


class _FaceMarkObserver:
    """Keeps shown marks in step with edits, and drops closed documents.

    Only a recompute can move a mark (Width, Depth or Length changed), and
    only for documents currently showing them, so this costs nothing when
    the toggle is off.
    """

    def slotRecomputedDocument(self, doc):
        refresh(doc)

    def slotDeletedDocument(self, doc):
        _SHOWN.discard(doc.Name)


_OBSERVER = None


def install():
    """Start the observer. Called when the workbench activates."""
    global _OBSERVER
    if _OBSERVER is None:
        _OBSERVER = _FaceMarkObserver()
        App.addDocumentObserver(_OBSERVER)
    return _OBSERVER
