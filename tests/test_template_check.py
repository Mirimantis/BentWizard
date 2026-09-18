"""The template bar: the shipped library clears it, a half-built
template is caught, and the geometry half finds a hole the pure half
cannot see."""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402

try:
    import FreeCAD as App
    _repo_path.graft()
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False

LIBRARY = REPO_ROOT / "library"


class LibraryIsShippable(unittest.TestCase):
    """Pure half: every shipped template lints strict AND advisory
    silent, carries the full skeleton, keeps the stem contract and
    loads as a TemplateSpec."""

    def test_every_template(self):
        from freecad.bentwizard import template_check
        paths = sorted(LIBRARY.glob("*.FCStd"))
        self.assertEqual([p.stem for p in paths], ["Joint_Butt", "Joint_HousedMT"])
        for path in paths:
            findings = template_check.check(path)
            self.assertEqual([str(f) for f in findings], [], path.name)
            self.assertIn("Clean", template_check.format_report(path, findings))


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class GeometryHalf(unittest.TestCase):
    def test_library_geometry_clean(self):
        from freecad.bentwizard import template_check
        for path in sorted(LIBRARY.glob("*.FCStd")):
            with tempfile.TemporaryDirectory() as td:
                copy = Path(td) / path.name
                copy.write_bytes(path.read_bytes())
                findings = template_check.check_geometry(copy, persist=True)
                self.assertEqual([str(f) for f in findings], [], path.name)
                # the sweep result is persisted (empty: nothing found)
                from freecad.bentwizard.fcstd import FcstdDocument
                doc = FcstdDocument.from_file(copy)
                vs = [o for o in doc.of_type("App::VarSet") if o.label.startswith("J-")][0]
                if "HousedMT" in path.name:
                    self.assertIsNotNone(vs.prop("SweepFindings"))
                    self.assertEqual(vs.prop("SweepFindings").value, "")

    def test_sweep_finds_a_hole(self):
        """On a post no wider than the girt, a housing deeper than the
        post severs it (a through mortise merely holes it) — the sweep
        must say so."""
        from freecad.bentwizard import template_check
        src = LIBRARY / "Joint_HousedMT.FCStd"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "Joint_Deep.FCStd"
            copy.write_bytes(src.read_bytes())
            doc = App.openDocument(str(copy), hidden=True)
            vs = doc.getObjectsByLabel("J-HousedMT-000")[0]
            vs.Label = "J-Deep-000"
            doc.getObjectsByLabel("TDim_T-Post-000")[0].WidthX = "6 in"
            vs.addProperty("App::PropertyLength", "HousingDepthMax", "Ranges", "max")
            vs.HousingDepthMax = "10 in"      # past the post's 8 in depth
            doc.recompute()
            doc.save()
            App.closeDocument(doc.Name)
            findings = template_check.check_geometry(copy, persist=False)
            rules = {f.rule for f in findings}
            self.assertIn("template-sweep", rules)

    def test_half_built_template_is_caught(self):
        from freecad.bentwizard import template_check
        from freecad.bentwizard.timber import new_timber
        doc = App.newDocument("Half")
        new_timber(doc, "T-Post-000", "8 in", "8 in", "8 ft")
        new_timber(doc, "T-Girt-000", "6 in", "8 in", "6 ft")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "Joint_Half.FCStd"
            doc.saveAs(str(path))
            App.closeDocument(doc.Name)
            rules = {f.rule for f in template_check.check(path)}
        self.assertIn("template-joint-varset", rules)
        self.assertIn("template-load", rules)

    def test_component_without_a_boolean_is_caught(self):
        from freecad.bentwizard import template_check
        src = LIBRARY / "Joint_HousedMT.FCStd"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "Joint_HousedMT.FCStd"
            copy.write_bytes(src.read_bytes())
            doc = App.openDocument(str(copy), hidden=True)
            cut = doc.getObjectsByLabel("Cut.Mortise.HousedMT.000")[0]
            body = cut.getParentGeoFeatureGroup()
            body.Tip = cut.BaseFeature
            body.removeObject(cut)
            doc.removeObject(cut.Name)
            doc.recompute()
            doc.save()
            App.closeDocument(doc.Name)
            rules = {f.rule for f in template_check.check(copy)}
        self.assertIn("template-components", rules)


if __name__ == "__main__":
    unittest.main()
