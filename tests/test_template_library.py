"""Where templates live, and getting a user's own joint into the library.

Discovery is pure Python and always runs. The save/create round trip
needs FreeCAD (it opens documents) and is skipped under a plain
interpreter, like the other document-level suites.

Run with:  python -m unittest discover -s tests
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402, F401

try:
    import FreeCAD as App
    _repo_path.graft()
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False

from freecad.bentwizard import naming, template_check  # noqa: E402
from freecad.bentwizard import template_library as tl  # noqa: E402

LIBRARY = REPO_ROOT / "library"
STARTER = LIBRARY / "Joint_Butt.FCStd"


class Discovery(unittest.TestCase):
    def test_lists_the_shipped_library(self):
        stems = [stem for stem, _ in tl.templates(LIBRARY)]
        self.assertIn("Joint_HousedMT", stems)
        self.assertEqual(stems, sorted(stems))

    def test_a_missing_directory_is_not_an_error(self):
        # The user's template folder does not exist until they save into
        # it; listing must not blow up before that.
        self.assertEqual(tl.templates(LIBRARY / "does-not-exist"), [])

    def test_user_folder_shadows_the_shipped_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "Joint_HousedMT.FCStd"
            shutil.copyfile(STARTER, local)
            found = dict(tl.templates([tmp, LIBRARY]))
            self.assertEqual(found["Joint_HousedMT"], local)
            # and the shipped ones it does not shadow are still there
            self.assertIn("Joint_WedgedHalfDovetail", found)

    def test_find_resolves_a_stem(self):
        self.assertEqual(tl.find("Joint_Butt", LIBRARY), STARTER)
        self.assertIsNone(tl.find("Joint_NoSuchThing", LIBRARY))


class Starters(unittest.TestCase):
    """A starter is a skeleton with no joinery in it — structural, not a
    declared flag, because what matters is that there is nothing to
    inherit (finding #12)."""

    def test_only_the_jointless_template_is_a_starter(self):
        self.assertEqual([stem for stem, _ in tl.starters(LIBRARY)],
                         ["Joint_Butt"])

    def test_a_template_with_cuts_is_not_a_starter(self):
        self.assertFalse(tl.is_starter(LIBRARY / "Joint_HousedMT.FCStd"))

    def test_a_non_template_file_is_not_a_starter(self):
        with tempfile.TemporaryDirectory() as tmp:
            junk = Path(tmp) / "not-a-model.FCStd"
            junk.write_text("nonsense")
            self.assertFalse(tl.is_starter(junk))


class Names(unittest.TestCase):
    def test_stem_carries_the_library_prefix(self):
        self.assertEqual(tl.stem_for("BraceMT"), "Joint_BraceMT")

    def test_an_already_prefixed_kind_does_not_stutter(self):
        self.assertEqual(tl.stem_for("Joint_BraceMT"), "Joint_BraceMT")

    def test_the_stem_round_trips_to_the_applied_kind(self):
        # The stem is what applied joints take their kind from.
        self.assertEqual(
            naming.kind_token_from_source(tl.stem_for("BraceMT")), "BraceMT")

    def test_reserved_characters_are_refused(self):
        with self.assertRaises(tl.TemplateError):
            tl.stem_for("Brace>MT")

    def test_an_empty_kind_is_refused(self):
        with self.assertRaises(tl.TemplateError):
            tl.stem_for("   ")


@unittest.skipUnless(HAVE_FREECAD,
                     "FreeCAD not importable — run with the bundled python")
class SaveRoundTrip(unittest.TestCase):
    """Saving an authoring document into the library, and the document
    it was saved from carrying on unchanged."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.work = self.tmp / "authoring.FCStd"
        shutil.copyfile(STARTER, self.work)
        self.doc = App.openDocument(str(self.work))

    def tearDown(self):
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def joint(self):
        return tl._joint_varset(self.doc)

    def test_saves_under_the_chosen_kind(self):
        path = tl.save_as_template(self.doc, self.tmp, "BraceMT", "BMT")
        self.assertEqual(path.name, "Joint_BraceMT.FCStd")
        self.assertTrue(path.is_file())

    def test_the_authoring_document_is_not_saved_over(self):
        """saveCopy, not saveAs: the user goes on editing the document
        they were editing, under its own name."""
        before = self.doc.FileName
        tl.save_as_template(self.doc, self.tmp, "BraceMT", "BMT")
        self.assertEqual(self.doc.FileName, before)

    def test_relabels_the_joint_and_its_companion(self):
        tl.save_as_template(self.doc, self.tmp, "BraceMT", "BMT")
        labels = {o.Label for o in self.doc.Objects
                  if o.TypeId == "App::VarSet"}
        self.assertIn("J-BraceMT-000", labels)
        self.assertIn("Layout_J-BraceMT-000", labels)

    def test_relabels_every_feature_suffix(self):
        """Apply-Joint rewrites exactly the '.<Abbrev>.<serial>' suffix,
        so a feature left on the old token reaches every applied model
        unchanged and two applications collide."""
        tl.save_as_template(self.doc, self.tmp, "BraceMT", "BMT")
        frames = [o.Label for o in self.doc.Objects
                  if o.TypeId.startswith("Part::LocalCoordinateSystem")]
        self.assertTrue(frames)
        for label in frames:
            self.assertTrue(label.endswith(".BMT.000"), label)

    def test_expressions_survive_the_relabel(self):
        tl.save_as_template(self.doc, self.tmp, "BraceMT", "BMT")
        stale = [(o.Label, path, expr) for o in self.doc.Objects
                 for path, expr in (getattr(o, "ExpressionEngine", None) or [])
                 if "<<J-Butt-000>>" in expr
                 or "<<Layout_J-Butt-000>>" in expr]
        self.assertEqual(stale, [])
        self.assertFalse([o.Name for o in self.doc.Objects
                          if "Invalid" in o.State or "Error" in o.State])

    def test_declining_the_rename_leaves_the_document_alone(self):
        tl.save_as_template(self.doc, self.tmp, "BraceMT", "BMT",
                            rename=False)
        self.assertEqual(self.joint().Label, "J-Butt-000")

    def test_the_saved_file_is_a_working_template(self):
        from freecad.bentwizard.apply_joint import TemplateSpec
        path = tl.save_as_template(self.doc, self.tmp, "BraceMT", "BMT")
        spec = TemplateSpec(path)
        self.assertEqual(spec.kind_token, "BraceMT")
        self.assertEqual(spec.abbrev, "BMT")
        self.assertEqual(spec.layout_label, "Layout_J-BraceMT-000")
        self.assertEqual([str(f) for f in template_check.check(path)], [])

    def test_rename_needed_is_quiet_when_nothing_would_change(self):
        tl.save_as_template(self.doc, self.tmp, "BraceMT", "BMT")
        self.assertIsNone(tl.rename_needed(self.doc, "BraceMT", "BMT"))
        self.assertIsNotNone(tl.rename_needed(self.doc, "TuskTenon", "BMT"))


@unittest.skipUnless(HAVE_FREECAD,
                     "FreeCAD not importable — run with the bundled python")
class NewFromStarter(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.doc = None

    def tearDown(self):
        if self.doc is not None and self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_an_open_authoring_document(self):
        path, self.doc = tl.new_from_starter(STARTER, self.tmp,
                                             "TuskTenon", "TT")
        self.assertEqual(path.name, "Joint_TuskTenon.FCStd")
        self.assertEqual(Path(self.doc.FileName), path)
        labels = {o.Label for o in self.doc.Objects
                  if o.TypeId == "App::VarSet"}
        self.assertIn("J-TuskTenon-000", labels)
        self.assertIn("Layout_J-TuskTenon-000", labels)

    def test_the_new_file_already_clears_the_bar(self):
        """The starter's whole value: authoring begins from something
        valid, not from a copy of a jointed template."""
        path, self.doc = tl.new_from_starter(STARTER, self.tmp,
                                             "TuskTenon", "TT")
        self.assertEqual([str(f) for f in template_check.check(path)], [])

    def test_a_template_from_the_starter_applies_to_real_timbers(self):
        """The end of the road the two commands make: a file the user
        created is a template Apply-Joint can use, under the kind they
        named it."""
        from freecad.bentwizard.apply_joint import TemplateSpec, apply_joint
        from freecad.bentwizard.timber import new_timber
        path, self.doc = tl.new_from_starter(STARTER, self.tmp,
                                             "TuskTenon", "TT")
        App.closeDocument(self.doc.Name)
        self.doc = None

        spec = TemplateSpec(path)
        target = App.newDocument("StarterApply")
        try:
            body_map = {}
            for index, role in enumerate(sorted(spec.roles)):
                body, _dims = new_timber(target, f"T-Test-{index:03d}",
                                         "8 in", "8 in", "10 ft")
                body_map[role] = body
            target.recompute()
            varset = apply_joint(target, spec, "001", body_map)
            self.assertEqual(varset.Label, "J-TuskTenon-001")
            self.assertFalse([o.Name for o in target.Objects
                              if "Invalid" in o.State or "Error" in o.State])
        finally:
            App.closeDocument(target.Name)

    def test_it_refuses_to_overwrite(self):
        path, self.doc = tl.new_from_starter(STARTER, self.tmp,
                                             "TuskTenon", "TT")
        with self.assertRaises(tl.TemplateError):
            tl.new_from_starter(STARTER, self.tmp, "TuskTenon", "TT")
        self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
