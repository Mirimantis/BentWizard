"""The variable highlight in the 3D view — GUI-only, transient.

A row in the Timber Variables panel lights every timber its value drives:
an outline of each timber's design solid, drawn over everything else so
a timber behind another still shows, with its name written along it.
Nothing here is an
object or a property, and no colour of the timber's own is touched: the
outline is a scene graph hung on each timber Body's view provider, as
the face marks are (`view_face_marks`), so it sits after the Body's
placement and follows a seated timber without tracking code. Nothing is
saved.

The name runs along the timber, beside it rather than across it (Adam's
GUI round, 2026-10-11: on the axis it crossed too many edges to read),
turned to face the viewer and to read left to right. Box selection is
broken upstream, so for now the names are how a framer matches the
outlines to the panel; they may go once picking in the 3D view works.
"""

from __future__ import annotations

from .timber import dims_varset
from .view_text import upright

# pivy is imported in the drawing functions, so `outline` stays
# importable, and testable, without a GUI

_NODE_NAME = "BentWizardVariableHighlight"
_COLOR = (0.90, 0.25, 0.75)     # magenta: apart from the selection green,
                                # the face marks' amber and the ends' blue
_LINE_WIDTH = 3.0
_FONT = "Arial:Bold"
_TEXT_HEIGHT = 0.45             # of the larger section width
_LABEL_AT = 0.62                # along the length: past the face marks at 1/2
_MIDDLE = 0.35                  # of the height: the middle of a capital, above
                                # the baseline — the pivot the text turns on

_LIT = {}                       # document Name -> {timber Name}


def outline(width_x, width_y, length_z):
    """(corners, edges) of a timber's design solid in its own
    coordinates: the section centred on the axis, end A at z = 0 and
    end B at z = LengthZ. `edges` are index pairs into `corners`."""
    hx, hy = width_x / 2.0, width_y / 2.0
    ring = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    corners = [(x, y, z) for z in (0.0, length_z) for x, y in ring]
    edges = []
    for i in range(4):
        edges.append((i, (i + 1) % 4))           # end A
        edges.append((4 + i, 4 + (i + 1) % 4))   # end B
        edges.append((i, 4 + i))                 # along the length
    return corners, edges


def label_frame(width_x, width_y, length_z):
    """(height, clearance, middle) of a timber's name, in its own
    coordinates: letters `height` tall, the near edge of the letters
    `clearance` off the timber's axis, so they clear the timber's
    corners however it is turned, and centred `middle` along it from
    end A."""
    height = max(width_x, width_y) * _TEXT_HEIGHT
    clearance = (width_x ** 2 + width_y ** 2) ** 0.5 / 2.0 + height * 0.3
    return height, clearance, length_z * _LABEL_AT


def _label(text, dims):
    """The timber's name, written along its length beside it, turning
    about the timber's axis to face the viewer (a VRML billboard) and end
    for end to read left to right (`view_text.upright`), so it is read
    side-on from anywhere around it and never crosses the timber's
    edges."""
    from pivy import coin
    height, clearance, middle = label_frame(*dims)
    sep = coin.SoSeparator()
    # the billboard turns about its own Y: lay Y along the timber's axis
    along = coin.SoRotation()
    along.rotation.setValue(coin.SbVec3f(1, 0, 0), 1.5707963267948966)
    sep.addChild(along)
    board = coin.SoVRMLBillboard()
    board.axisOfRotation.setValue(0, 1, 0)
    sep.addChild(board)
    # in the billboard: Y along the timber, Z toward the viewer. Run the
    # text along Y; its letters then stand toward -X, so set it off -X.
    # The pivot is the middle of the letters, so turning end for end
    # leaves them where they were.
    at = coin.SoTranslation()
    at.translation.setValue(-(clearance + height * _MIDDLE), middle, 0.0)
    board.addChild(at)
    turn = coin.SoRotation()
    turn.rotation.setValue(coin.SbVec3f(0, 0, 1), 1.5707963267948966)
    board.addChild(turn)
    upright_cb = coin.SoCallback()
    upright_cb.setCallback(upright)
    board.addChild(upright_cb)
    down = coin.SoTranslation()
    down.translation.setValue(0.0, -height * _MIDDLE, 0.0)
    board.addChild(down)
    font = coin.SoFont()
    font.name.setValue(_FONT)
    font.size.setValue(height)
    board.addChild(font)
    words = coin.SoAsciiText()
    words.string.setValue(text)
    words.justification.setValue(coin.SoAsciiText.CENTER)
    board.addChild(words)
    return sep


def _dims(body):
    vs = dims_varset(body)
    try:
        dims = (float(vs.WidthX), float(vs.WidthY), float(vs.LengthZ))
    except AttributeError:
        return None
    return dims if all(v > 0 for v in dims) else None


def _node(body):
    dims = _dims(body)
    if dims is None:
        return None
    from pivy import coin
    corners, edges = outline(*dims)

    root = coin.SoAnnotation()         # drawn last, over everything
    root.setName(_NODE_NAME)
    pick = coin.SoPickStyle()
    pick.style.setValue(coin.SoPickStyle.UNPICKABLE)   # never steal a click
    root.addChild(pick)
    light = coin.SoLightModel()
    light.model.setValue(coin.SoLightModel.BASE_COLOR)
    root.addChild(light)
    color = coin.SoBaseColor()
    color.rgb.setValue(*_COLOR)
    root.addChild(color)
    style = coin.SoDrawStyle()
    style.lineWidth.setValue(_LINE_WIDTH)
    root.addChild(style)

    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(corners), corners)
    root.addChild(coords)
    lines = coin.SoIndexedLineSet()
    index = []
    for a, b in edges:
        index += [a, b, -1]
    lines.coordIndex.setValues(0, len(index), index)
    root.addChild(lines)

    root.addChild(_label(body.Label, dims))
    return root


def _remove(body):
    vobj = getattr(body, "ViewObject", None)
    root = getattr(vobj, "RootNode", None) if vobj is not None else None
    if root is None:
        return
    for i in reversed(range(root.getNumChildren())):
        if root.getChild(i).getName() == _NODE_NAME:
            root.removeChild(i)


def clear(doc):
    """Take the highlight off every timber in `doc`."""
    for name in _LIT.pop(doc.Name, set()):
        body = doc.getObject(name)
        if body is not None:
            _remove(body)


def show(doc, names):
    """Light exactly the timbers named (internal Names) in `doc`,
    rebuilding each outline from the timber's current Dims."""
    clear(doc)
    lit = set()
    for name in sorted(names):
        body = doc.getObject(name)
        vobj = getattr(body, "ViewObject", None) if body is not None else None
        if vobj is None or getattr(vobj, "RootNode", None) is None:
            continue
        node = _node(body)
        if node is None:
            continue
        vobj.RootNode.addChild(node)
        lit.add(name)
    if lit:
        _LIT[doc.Name] = lit
    return lit


def lit(doc):
    return set(_LIT.get(doc.Name, set()))


def forget(doc_name):
    """A closed document: nothing left to take down."""
    _LIT.pop(doc_name, None)
