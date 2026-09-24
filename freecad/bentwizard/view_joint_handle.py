"""The timber-joint handle's marker — ViewProvider and live tracking.

GUI-only. The class path below is written into the Gui document when a
handle is created, so **this module and class must never be renamed**:
older files name them by string. A file opened without the workbench
simply gets FreeCAD's default view provider — the handle is still an
ordinary group holding its VarSet (Tier 2).

Drawn like the Assembly workbench's grounded-joint padlock: a billboarded,
screen-scaled annotation that stays legible at any zoom and reads through
the timber it sits in — a joint is usually buried in wood, and the point
of the marker is to see that the intersection IS joined without cutting
a section.

The handle owns no Placement (nothing it does may touch geometry), so the marker's position is read from the joint's host datum
at draw time and refreshed after every document recompute by one shared
observer. That covers what an object-local update cannot: a host datum
moving with Joint_Station, and a whole bent seating in the frame — the
same blind spot a moved container leaves in FreeCAD's own markers.
"""

from __future__ import annotations

import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

from . import joint_handle

# marker geometry, in the screen-scaled space of SoShapeScale
_SIZE = 4.0                 # half-length of each bar
_BAR = 1.4                  # half-thickness of the crossed bars
_SCALE = 2.5                # SoShapeScale factor (as Assembly's padlock)
_COLOR = (0.72, 0.42, 0.13)     # timber amber, apart from the padlock red

# Tree icon: the same crossed bars as the 3D marker, inline as XPM so it
# depends on no resource file — this workbench ships none.
_ICON = """/* XPM */
static char * timber_joint_handle[] = {
"16 16 3 1",
" 	c None",
".	c #B76B21",
"+	c #6E3E10",
"                ",
"                ",
"      +..+      ",
"      +..+      ",
"      +..+      ",
"   +++++++++    ",
"   .........    ",
"   .........    ",
"   +++++++++    ",
"      +..+      ",
"      +..+      ",
"      +..+      ",
"                ",
"                ",
"                ",
"                "};
"""


class ViewProviderTimberJointHandle:
    """Marker at a timber joint: a 3D click selects the joint's handle;
    the operations are reached from the tree.

    `doubleClicked` and `setupContextMenu` are **tree-only hooks** —
    FreeCAD does not dispatch either from the 3D view (doubleClicked is
    "called by the tree"; repeated 3D clicks walk the container
    hierarchy instead). Verified in GUI testing against 1.1.1, and open
    upstream for FreeCAD's own Assembly joint markers (#14701, #11429,
    #12826). Nothing here is missing: the 3D marker locates a joint and
    selects it, and every BentWizard command preselects from that
    selection. Do not "fix" this by reimplementing the hooks.
    """

    def __init__(self, vobj):
        # The Proxy is deliberately NOT saved. A persisted view provider
        # makes every open WITHOUT this workbench print a
        # ModuleNotFoundError traceback (seen in GUI testing) and freezes
        # this module's name forever, since the Gui document would name
        # it by string. Instead `install()` and the restore observer
        # attach the marker at runtime — workbench-gated behavior on a
        # native object, which is what Tier 2 asks for.
        try:
            vobj.setPropertyStatus("Proxy", "Transient")
        except Exception:
            pass            # older API: a saved proxy still works
        vobj.Proxy = self
        # The tree renders a group's children from the VIEW provider, not
        # from the App-side Group property. Without this the handle's
        # VarSet did not nest under it and could not be dragged onto it —
        # it fell through to the container level instead (GUI testing),
        # even though handle.Group held it all along. App-side extension
        # and Gui-side extension are a pair; BIM, CAM and FEM add them
        # the same way.
        try:
            if not vobj.hasExtension("Gui::ViewProviderGroupExtension"):
                vobj.addExtension("Gui::ViewProviderGroupExtensionPython")
        except Exception:
            pass            # already extended (a reopened Gui document)

    # --- scene graph --------------------------------------------------

    def attach(self, vobj):
        self.Object = vobj.Object
        self.transform = coin.SoTransform()

        color = coin.SoBaseColor()
        color.rgb.setValue(*_COLOR)

        marker = coin.SoAnnotation()        # drawn on top of the timber
        marker.addChild(color)
        marker.addChild(self._crossed_bars())

        billboard = coin.SoVRMLBillboard()  # always faces the camera
        billboard.addChild(marker)

        scale = coin.SoType.fromName("SoShapeScale").createInstance()
        scale.setPart("shape", billboard)
        scale.scaleFactor = _SCALE

        pick = coin.SoPickStyle()
        pick.style.setValue(coin.SoPickStyle.SHAPE_ON_TOP)

        # SoFCSelection, not a plain separator: it is what routes a 3D
        # pick back to THIS object. Without it the click resolves to the
        # nearest ancestor that does have routing — the marker's own
        # container — so the 3D view escalated the selection instead of
        # calling doubleClicked, and never offered the context menu
        # (GUI testing). Same node Assembly's joint markers use.
        root = coin.SoType.fromName("SoFCSelection").createInstance()
        obj = vobj.Object
        if obj is not None:
            root.documentName.setValue(obj.Document.Name)
            root.objectName.setValue(obj.Name)
            root.subElementName.setValue("")     # the whole handle
        root.addChild(self.transform)
        root.addChild(pick)
        root.addChild(scale)
        vobj.addDisplayMode(root, "Marker")
        self.refresh()
        observer().watch(self)

    @staticmethod
    def _crossed_bars():
        """Two crossed bars — an intersection, joined."""
        sep = coin.SoSeparator()
        for a, b in ((_SIZE, _BAR), (_BAR, _SIZE)):
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, 4, [(-a, -b, 0), (a, -b, 0),
                                          (a, b, 0), (-a, b, 0)])
            face = coin.SoFaceSet()
            face.numVertices.setValue(4)
            bar = coin.SoSeparator()
            bar.addChild(coords)
            bar.addChild(face)
            sep.addChild(bar)
        return sep

    def refresh(self):
        """Move the marker to the joint's host datum. Cheap, and
        purely view-side: no property is written, nothing is touched.

        Returns False only when the handle is gone — the observer reads
        that as "stop watching". Anything else (a link not yet resolved
        mid-restore, a frame briefly missing) keeps the watch alive to
        try again on the next recompute.
        """
        try:
            obj = getattr(self, "Object", None)
            transform = getattr(self, "transform", None)
            if obj is None or transform is None:
                return True                 # not ready yet
            frame = getattr(obj, joint_handle.DATUM_PROP, None)
            if frame is None:
                return True                 # handle alive, nothing to draw
            pos = joint_handle.marker_position(obj, frame)
        except ReferenceError:
            return False                    # the handle was deleted
        except (AttributeError, RuntimeError):
            return True
        transform.translation.setValue(pos.x, pos.y, pos.z)
        return True

    def updateData(self, _obj, prop):
        if prop == joint_handle.DATUM_PROP:
            self.refresh()

    def getDisplayModes(self, _vobj):
        return ["Marker"]

    def getDefaultDisplayMode(self):
        return "Marker"

    def getIcon(self):
        return _ICON       # inline: the workbench ships no icon resources

    def onChanged(self, _vp, _prop):
        pass

    def dumps(self):
        return None         # Coin nodes are not serializable

    def loads(self, _state):
        return None

    # --- interaction --------------------------------------------------

    def doubleClicked(self, vobj):
        """Select the joint's VarSet — its parameters land in the Data
        property editor, editable in place. Tree only (see the class
        docstring)."""
        varset = joint_handle.handle_varset(vobj.Object)
        if varset is None:
            return False
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(varset)
        return True

    def setupContextMenu(self, vobj, menu):
        """Whole-joint operations, from the shared registry — a joint
        spans many objects, and this handle is where it is one thing.
        Tree only (see the class docstring)."""
        varset = joint_handle.handle_varset(vobj.Object)
        if varset is None:
            return
        for text, action in joint_handle.CONTEXT_ACTIONS:
            menu.addAction(text).triggered.connect(
                lambda _checked=False, fn=action, vs=varset: fn(vs))

    def canDelete(self, _obj):
        return True

    def onDelete(self, vobj, _subelements):
        """Deleting the marker must never delete joinery: the parameter
        and accessor VarSets, the seat, the cuts and the datums all stay
        exactly as they are, and the timbers stay seated (Remove Timber
        Joint is the context-menu action that removes a joint). What the
        handle holds moves out beside it first; Seat Timbers gives the
        joint a new handle and files it all back."""
        joint_handle.release_contents(vobj.Object)
        observer().forget(self)
        return True


class _MarkerObserver:
    """Refreshes every live marker after a document recompute.

    A handle has no Placement of its own, so no property change announces
    that its joint moved — the frame it draws on lives inside a body
    inside a bent, and either can move without the handle hearing a word.
    One document observer covers every case for the cost of a few vector
    writes per recompute.
    """

    def __init__(self):
        self._views = []

    def watch(self, view):
        if view not in self._views:
            self._views.append(view)

    def forget(self, view):
        if view in self._views:
            self._views.remove(view)

    def refresh_all(self):
        self._views = [v for v in self._views if v.refresh()]

    # --- FreeCAD document observer hooks ---
    def slotRecomputedDocument(self, _doc):
        self.refresh_all()

    def slotActivateDocument(self, doc):
        """Re-attach markers to a document as it becomes active — which
        is how a reopened file gets them back.

        This used to be `slotFinishRestoreDocument`, which the App
        document observer never calls (the name exists only in
        FreeCADGui, and not even the Gui observer fires it on an open),
        so a file opened with the workbench already active — as at
        startup — never got its markers back; only activating the
        workbench afterwards did. Measured on 26.3 and 1.1.3: an open
        fires `slotActivateDocument` twice, the second time AFTER the
        view providers are restored (Proxy already the restored 1).
        FreeCAD's own BIM module hooks the same slot.

        Also fires on every switch between documents; `attach_missing`
        skips handles that already have their marker, so that is cheap.
        The attach waits one event-loop tick, so the open has finished."""
        from PySide import QtCore

        def later():
            try:
                attach_missing(doc)
                self.refresh_all()
            except ReferenceError:
                pass            # closed before the tick
        QtCore.QTimer.singleShot(0, later)


_OBSERVER = None


def observer():
    """The one marker observer, installed on first use."""
    global _OBSERVER
    if _OBSERVER is None:
        _OBSERVER = _MarkerObserver()
        App.addDocumentObserver(_OBSERVER)
    return _OBSERVER


def attach_missing(doc):
    """Give a marker to every handle in a document that has none.

    A handle built headless (a script, a test, another machine's batch
    run) carries no view provider — the class is written into the *Gui*
    document, which headless FreeCAD never writes. Nothing is wrong with
    such a file; it just has no marker until a GUI sees it. Also the
    upgrade path for documents whose handles predate this module.
    """
    for obj in doc.Objects:
        if not joint_handle.is_handle(obj):
            continue
        vobj = obj.ViewObject
        if vobj is None:
            continue
        # Test for OUR view provider, never for an empty slot: a reopened
        # file restores the (deliberately unsaved) Proxy as the int 1, on
        # 26.3 and 1.1.3 alike — so an `is None` test skipped every handle
        # and no marker ever came back after a reopen (Adam, 2026-09-22:
        # "the handles' visibility is turned off and I can't get them to
        # display again" — there was nothing to display).
        if isinstance(getattr(vobj, "Proxy", None), ViewProviderTimberJointHandle):
            continue
        # each handle on its own: one that fails must not strand the rest
        try:
            ViewProviderTimberJointHandle(vobj)
            # The restored DisplayMode is '' with an enumeration built
            # before this view provider existed, so it lacks 'Marker' and
            # assigning it outright raises. Give it its options, then the
            # value — without a display mode the marker draws nothing.
            if vobj.DisplayMode != "Marker":
                vobj.DisplayMode = vobj.listDisplayModes() or ["Marker"]
                vobj.DisplayMode = "Marker"
        except Exception as exc:
            App.Console.PrintWarning(
                f"BentWizard: could not restore the marker for "
                f"{obj.Label}: {exc}\n")


def install():
    """Start the marker machinery: adopt every open document, and watch
    for the ones opened later. Called when the workbench activates."""
    observer()
    for doc in App.listDocuments().values():
        attach_missing(doc)
