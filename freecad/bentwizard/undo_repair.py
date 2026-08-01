"""Re-arm expression bindings on objects that undo brought back.

Upstream FreeCAD 1.1.1 defect (finding #15): undoing a deletion restores
the objects with their ``ExpressionEngine`` strings intact — the text is
right there in the property editor — but the *dependency* each of those
expressions stands for is never re-registered. The restored object drops
out of its driver's ``InList``, so changing the driver no longer touches
it and no recompute ever re-evaluates the expression. Nothing reports an
error: the object count matches, every object is valid and up to date,
the geometry is the right shape. It is simply no longer parametric.

For BentWizard that is the difference between "undo Remove Joint" giving
back a joint and giving back a fossil of one: the joint VarSet returns,
the pockets return in the right places, and editing ``Housing_Depth``
does nothing forever after.

The breakage is always on the *restored* side of a binding. Deleting and
undoing the object an expression **points at** is fine — the surviving
dependent re-resolves it. Deleting and undoing the object that **carries**
the expression is what breaks. So the repair set is exactly the objects
FreeCAD just re-created, which it announces one by one through
``slotCreatedObject`` — no label matching, no guessing which objects
"belong" to the undone operation.

Re-setting an expression to the identical string is a no-op (the property
compares and skips), so each binding is cleared and written back. The
value the property already holds is the value the expression yields, so
nothing moves in the gap.

Workbench-gated *functionality* over native data, which Tier 2 allows:
the documents stay ordinary FreeCAD files, and without BentWizard loaded
they behave exactly as stock FreeCAD does today — which is to say, with
the upstream bug.
"""

from __future__ import annotations

import FreeCAD as App


def rearm(objs):
    """Re-register the expression bindings carried by ``objs``.

    Returns the objects that actually carried expressions. Objects
    without an ``ExpressionEngine``, and documents already closed, are
    skipped silently — this runs from an observer, where raising would
    abort somebody else's undo.
    """
    repaired = []
    for obj in objs:
        engine = getattr(obj, "ExpressionEngine", None)
        if not engine:
            continue
        touched = False
        for path, expr in list(engine):
            try:
                obj.setExpression(path, None)
                obj.setExpression(path, expr)
                touched = True
            except Exception as exc:      # one bad binding must not
                App.Console.PrintWarning(  # cost the rest their repair
                    f"BentWizard: could not re-arm {obj.Name}.{path} "
                    f"after undo: {exc}\n")
        if touched:
            repaired.append(obj)
    return repaired


class _UndoObserver:
    """Collects the objects FreeCAD re-creates, re-arms them on undo.

    ``slotCreatedObject`` fires for ordinary creation too, so the buffer
    is emptied whenever a transaction closes — during an undo FreeCAD
    opens no transaction, which is what makes the leftovers at
    ``slotUndoDocument`` time precisely the restored objects.
    """

    def __init__(self):
        self._created = {}         # document name -> list of object names
        self._busy = False

    # --- bookkeeping ---
    def _forget(self, doc):
        self._created.pop(getattr(doc, "Name", doc), None)

    def _take(self, doc):
        names = self._created.pop(doc.Name, [])
        objs = [doc.getObject(n) for n in names]
        return [o for o in objs if o is not None]

    # --- FreeCAD document observer hooks ---
    def slotCreatedObject(self, obj):
        if self._busy:
            return
        doc = getattr(obj, "Document", None)
        if doc is not None:
            self._created.setdefault(doc.Name, []).append(obj.Name)

    def slotCommitTransaction(self, doc):
        self._forget(doc)

    def slotAbortTransaction(self, doc):
        self._forget(doc)

    def slotDeletedDocument(self, doc):
        self._forget(doc)

    def slotUndoDocument(self, doc):
        self._repair(doc)

    def slotRedoDocument(self, doc):
        self._repair(doc)

    def _repair(self, doc):
        if self._busy:
            return
        restored = self._take(doc)
        if not restored:
            return                  # an undo that restored nothing costs
        self._busy = True           # nothing — no touch, no recompute
        try:
            if rearm(restored):
                # re-arming touches; settle it here rather than leave the
                # document blue until the user's next edit
                try:
                    doc.recompute()
                except Exception as exc:
                    App.Console.PrintWarning(
                        f"BentWizard: recompute after undo repair "
                        f"failed: {exc}\n")
        finally:
            self._busy = False


_OBSERVER = None


def install():
    """Start watching for undos that restore expression-driven objects.

    Idempotent; called when the workbench activates and directly by
    headless callers that want the repair.
    """
    global _OBSERVER
    if _OBSERVER is None:
        _OBSERVER = _UndoObserver()
        App.addDocumentObserver(_OBSERVER)
    return _OBSERVER


def uninstall():
    """Stop watching (tests, and workbench teardown)."""
    global _OBSERVER
    if _OBSERVER is not None:
        App.removeDocumentObserver(_OBSERVER)
        _OBSERVER = None
