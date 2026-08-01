"""Tests for the expression-autocomplete candidate list.

FreeCAD-dependent — run with the bundled interpreter; skips under
plain Python. commands.py imports FreeCADGui, which is importable in
console mode (only its widget calls need a running GUI).
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402 — this repo's code must win the import

try:
    import FreeCAD as App
    _repo_path.graft()
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False


@unittest.skipUnless(HAVE_FREECAD,
                     "FreeCAD not importable — run with the bundled python")
class ExpressionCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ExprCand")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def varset(self, label, props, group="Base"):
        """A VarSet built the way the GUI's 'add property' dialog does —
        group defaults to 'Base'."""
        vs = self.doc.addObject("App::VarSet", "VarSet")
        vs.Label = label
        for name, type_id in props:
            vs.addProperty(type_id, name, group, "tip")
        return vs

    def candidates(self, **kw):
        from freecad.bentwizard.commands import _expression_candidates
        return _expression_candidates(self.doc, **kw)

    def test_hand_authored_project_varset_is_offered(self):
        """Regression: properties added through FreeCAD's own dialog land
        in group 'Base', and the old group-based filter dropped them, so
        a hand-built Project_Main was invisible to every fx field."""
        self.varset("Project_Main",
                    [("Bay_Span_OC", "App::PropertyLength"),
                     ("Tie_Stick_Length", "App::PropertyLength")])
        got = self.candidates()
        self.assertIn("<<Project_Main>>.Bay_Span_OC", got)
        self.assertIn("<<Project_Main>>.Tie_Stick_Length", got)

    def test_framework_properties_stay_out(self):
        self.varset("Project_Main", [("Bay_Span_OC", "App::PropertyLength")])
        got = self.candidates()
        for junk in ("Label", "Label2", "Visibility", "ExpressionEngine"):
            self.assertNotIn(f"<<Project_Main>>.{junk}", got)

    def test_non_numeric_properties_stay_out(self):
        self.varset("Project_Main",
                    [("Bay_Span_OC", "App::PropertyLength"),
                     ("Position_Tag", "App::PropertyString")])
        self.assertNotIn("<<Project_Main>>.Position_Tag", self.candidates())

    def test_several_project_varsets_all_offered(self):
        """A user may keep one VarSet per part of the structure."""
        self.varset("Project_Main", [("Bay_Span_OC", "App::PropertyLength")])
        self.varset("Group_Roof", [("Pitch", "App::PropertyAngle")])
        self.varset("Group_Balcony", [("Post_Height", "App::PropertyLength")])
        got = self.candidates()
        for want in ("<<Project_Main>>.Bay_Span_OC",
                     "<<Group_Roof>>.Pitch",
                     "<<Group_Balcony>>.Post_Height"):
            self.assertIn(want, got)

    def test_include_dims_false_drops_only_dims_varsets(self):
        from freecad.bentwizard.timber import new_timber
        new_timber(self.doc, "T-Post-001", "8 in", "8 in", "10 ft")
        self.varset("Project_Main", [("Bay_Span_OC", "App::PropertyLength")])
        self.doc.recompute()
        got = self.candidates(include_dims=False)
        self.assertIn("<<Project_Main>>.Bay_Span_OC", got)
        self.assertFalse([c for c in got if c.startswith("<<TDim_")],
                         f"Dims VarSets leaked into the list: {got}")
        # ...and they come back when dims are allowed (joint parameters)
        self.assertTrue([c for c in self.candidates(include_dims=True)
                         if c.startswith("<<TDim_")])

    def test_non_varset_objects_ignored(self):
        self.doc.addObject("App::DocumentObjectGroup", "SomeGroup")
        self.varset("Project_Main", [("Bay_Span_OC", "App::PropertyLength")])
        self.assertEqual(self.candidates(),
                         ["<<Project_Main>>.Bay_Span_OC"])


if __name__ == "__main__":
    unittest.main()
