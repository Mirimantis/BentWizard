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

    def _lopsided(self, td, handed):
        """A template whose cutter and adder sit off-centre (+1, +1/2 in):
        a joint with a hand. `handed` None leaves the flag undeclared."""
        import importlib.util
        from freecad.bentwizard import component, naming
        spec_ = importlib.util.spec_from_file_location(
            "build_library", REPO_ROOT / "scripts" / "build_library.py")
        bl = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(bl)
        doc = App.newDocument("Lopsided")
        post, girt, host, mate, vs = bl.skeleton(doc, "Lop", handed=handed)
        J = f"<<{vs.Label}>>"
        bl.add_param(vs, "Depth", "App::PropertyLength", 3 * 25.4, "cut depth")
        for label, role, order, datum, direction, timber in (
                ("Notch.Lop.000", naming.COMPONENT_CUTTER, 1, host, -1, post),
                ("Tongue.Lop.000", naming.COMPONENT_ADDER, 2, mate, +1, girt)):
            c = component.new_component(doc, label, role, order, vs, datum)
            component.add_prism(c, label.split(".")[0] + "Prism", "2 in", "3 in",
                                J + ".Depth", direction=direction,
                                offset=(1 * 25.4, 0.5 * 25.4))
            doc.recompute()
            component.apply_boolean(timber, c, role)
        doc.recompute()
        path = Path(td) / "Joint_Lop.FCStd"
        doc.saveAs(str(path))
        App.closeDocument(doc.Name)
        return path

    def test_handedness_is_declared_and_checked(self):
        """Handed = False on an asymmetric component is STRICT (it would
        land on the wrong side at the opposite face or end); undeclared
        is advisory; a handed template whose components are symmetric
        gets an advisory to drop the flag."""
        from freecad.bentwizard import template_check
        from freecad.bentwizard.template import TemplateSpec

        def handed_findings(path):
            findings = template_check.check(path) + template_check.check_geometry(
                path, persist=False)
            return {(f.severity, f.label) for f in findings if f.rule == "template-handed"}

        with tempfile.TemporaryDirectory() as td:
            undeclared = self._lopsided(td, None)
            self.assertIsNone(TemplateSpec(undeclared).handed)
            self.assertTrue(TemplateSpec(undeclared).mirrors)
            self.assertEqual(handed_findings(undeclared),
                             {(template_check.ADVISORY, "J-Lop-000")})
        with tempfile.TemporaryDirectory() as td:
            wrong = self._lopsided(td, False)
            self.assertFalse(TemplateSpec(wrong).mirrors)
            self.assertEqual(handed_findings(wrong),
                             {(template_check.STRICT, "Notch.Lop.000"),
                              (template_check.STRICT, "Tongue.Lop.000")})
        with tempfile.TemporaryDirectory() as td:
            right = self._lopsided(td, True)
            self.assertEqual(handed_findings(right), set())
        # the shipped HousedMT is symmetric: declared False, checked clean;
        # flipped to True it earns the advisory
        spec = TemplateSpec(LIBRARY / "Joint_HousedMT.FCStd")
        self.assertIs(spec.handed, False)
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "Joint_HousedMT.FCStd"
            copy.write_bytes((LIBRARY / "Joint_HousedMT.FCStd").read_bytes())
            doc = App.openDocument(str(copy), hidden=True)
            doc.getObjectsByLabel("J-HousedMT-000")[0].Handed = True
            doc.save()
            App.closeDocument(doc.Name)
            self.assertEqual(handed_findings(copy),
                             {(template_check.ADVISORY, "Mortise.HousedMT.000"),
                              (template_check.ADVISORY, "Tenon.HousedMT.000")})

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
