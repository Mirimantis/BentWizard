"""Template discovery, starters, and the save / new-from-starter round trip."""

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

from freecad.bentwizard import template_library  # noqa: E402

LIBRARY = REPO_ROOT / "library"


class Discovery(unittest.TestCase):
    def test_shipped_library(self):
        stems = [s for s, _p in template_library.templates(LIBRARY)]
        self.assertEqual(stems, ["Joint_Butt", "Joint_HousedMT"])
        self.assertEqual(template_library.find("Joint_Butt", LIBRARY).name, "Joint_Butt.FCStd")
        self.assertIsNone(template_library.find("Nope", LIBRARY))

    def test_user_folder_shadows_shipped(self):
        with tempfile.TemporaryDirectory() as td:
            mine = Path(td) / "Joint_HousedMT.FCStd"
            mine.write_bytes((LIBRARY / "Joint_HousedMT.FCStd").read_bytes())
            found = dict(template_library.templates([td, LIBRARY]))
            self.assertEqual(found["Joint_HousedMT"], mine)

    def test_starters_are_the_jointless_ones(self):
        self.assertEqual([s for s, _p in template_library.starters(LIBRARY)], ["Joint_Butt"])
        self.assertTrue(template_library.is_starter(LIBRARY / "Joint_Butt.FCStd"))
        self.assertFalse(template_library.is_starter(LIBRARY / "Joint_HousedMT.FCStd"))

    def test_names(self):
        self.assertEqual(template_library.stem_for("BraceMT"), "Joint_BraceMT")
        self.assertEqual(template_library.stem_for("Joint_BraceMT"), "Joint_BraceMT")
        self.assertEqual(template_library.wanted_label("BraceMT"), "J-BraceMT-000")
        with self.assertRaises(template_library.TemplateError):
            template_library.stem_for("")


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class HiddenOpen(unittest.TestCase):
    """`open_hidden` gives the template back and leaves the user's
    document active — openDocument(hidden=True) steals the active
    document, and in the GUI closing the hidden one left *none* (every
    command that needs one went grey in Adam's first rev-2 GUI round)."""

    def test_active_document_is_restored(self):
        mine = App.newDocument("Mine")
        try:
            self.assertIs(App.ActiveDocument, mine)
            with template_library.open_hidden(LIBRARY / "Joint_Butt.FCStd") as tdoc:
                self.assertEqual(tdoc.Label, "Joint_Butt")
                self.assertIs(App.ActiveDocument, tdoc)      # the theft
                name = tdoc.Name
            self.assertNotIn(name, App.listDocuments())         # closed again
            self.assertIs(App.ActiveDocument, mine)             # and restored
        finally:
            App.closeDocument(mine.Name)

    def test_closes_and_restores_on_error(self):
        mine = App.newDocument("Mine")
        try:
            with self.assertRaises(RuntimeError):
                with template_library.open_hidden(LIBRARY / "Joint_Butt.FCStd") as tdoc:
                    name = tdoc.Name
                    raise RuntimeError("boom")
            self.assertNotIn(name, App.listDocuments())
            self.assertIs(App.ActiveDocument, mine)
        finally:
            App.closeDocument(mine.Name)

    def test_restore_active_tolerates_none_and_closed(self):
        template_library.restore_active(None)
        gone = App.newDocument("Gone")
        App.closeDocument(gone.Name)
        template_library.restore_active(gone)                   # no raise


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class RoundTrip(unittest.TestCase):
    def test_save_as_template_relabels_and_passes_the_bar(self):
        from freecad.bentwizard import template_check
        from freecad.bentwizard.template import TemplateSpec
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / "authoring.FCStd"
            work.write_bytes((LIBRARY / "Joint_HousedMT.FCStd").read_bytes())
            doc = App.openDocument(str(work), hidden=True)
            try:
                self.assertEqual(template_library.rename_needed(doc, "MyMT"), "J-MyMT-000")
                out = template_library.save_as_template(doc, Path(td) / "lib", "MyMT")
                self.assertEqual(out.name, "Joint_MyMT.FCStd")
                labels = {o.Label for o in doc.Objects}
                self.assertIn("J-MyMT-000", labels)
                self.assertIn("Mortise.MyMT.000", labels)
                self.assertIn("Cut.Mortise.MyMT.000", labels)
                self.assertIsNone(template_library.rename_needed(doc, "MyMT"))
                self.assertEqual(Path(doc.FileName), work)     # saveCopy, not save
            finally:
                App.closeDocument(doc.Name)
            self.assertEqual([str(f) for f in template_check.check(out)], [])
            spec = TemplateSpec(out)
            self.assertEqual(spec.kind, "MyMT")
            self.assertEqual([c["label"] for c in spec.components],
                             ["Mortise.MyMT.000", "Tenon.MyMT.000"])

    def test_new_from_starter(self):
        from freecad.bentwizard import template_check
        with tempfile.TemporaryDirectory() as td:
            path, doc = template_library.new_from_starter(
                LIBRARY / "Joint_Butt.FCStd", Path(td) / "lib", "Lap")
            try:
                self.assertEqual(path.name, "Joint_Lap.FCStd")
                self.assertTrue(path.exists())
                self.assertEqual(doc.getObjectsByLabel("J-Lap-000")[0].TypeId, "App::VarSet")
            finally:
                App.closeDocument(doc.Name)
            self.assertEqual([str(f) for f in template_check.check(path)], [])
            self.assertTrue(template_library.is_starter(path))


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class LastTemplateTest(unittest.TestCase):
    """The Apply dialog opens on the template last applied — stored as a
    stem in the workbench's preferences, the user's own value restored
    after the test."""

    def setUp(self):
        from freecad.bentwizard import template_library as tl
        self.grp = App.ParamGet(tl.PARAM_PATH)
        self.saved = (self.grp.GetString(tl.LAST_TEMPLATE_KEY, "")
                      if tl.LAST_TEMPLATE_KEY in self.grp.GetStrings() else None)

    def tearDown(self):
        from freecad.bentwizard import template_library as tl
        if self.saved is None:
            self.grp.RemString(tl.LAST_TEMPLATE_KEY)
        else:
            self.grp.SetString(tl.LAST_TEMPLATE_KEY, self.saved)

    def test_round_trip(self):
        from freecad.bentwizard import template_library as tl
        self.grp.RemString(tl.LAST_TEMPLATE_KEY)
        self.assertEqual(tl.last_template(), "")
        tl.set_last_template("Joint_HousedMT")
        self.assertEqual(tl.last_template(), "Joint_HousedMT")
        # the stem is one the library actually lists
        self.assertIn("Joint_HousedMT", [s for s, _p in tl.templates()])


if __name__ == "__main__":
    unittest.main()
