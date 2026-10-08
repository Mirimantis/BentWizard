"""The Timber Variables listing: what sets a timber or a timber joint, and
where each value comes from — typed in place, followed through single
references to its end, a formula, or fixed by the template — plus the
timbers each shared value also drives, the selection mapping, and the
hand-added bindings under Other."""

import sys
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

IN = 25.4
TEMPLATE = REPO_ROOT / "library" / "Joint_HousedMT.FCStd"


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class VariablesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.template import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        from freecad.bentwizard import frame
        self.doc = App.newDocument("VariablesTest")
        self.pv = frame.project_varset(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    # --- fixtures -------------------------------------------------------

    def timber(self, label, w="8 in", d="8 in", length="8 ft"):
        from freecad.bentwizard.timber import new_timber
        body, _dims = new_timber(self.doc, label, w, d, length)
        return body

    def joint(self, serial, post, beam, face="YPos", end="EndA", station="48 in"):
        from freecad.bentwizard.apply import apply_joint
        from freecad.bentwizard.frame import place_on_apply
        vs = apply_joint(self.doc, self.spec, serial, {
            self.spec.host_role: {"body": post, "face": face, "station": station},
            self.spec.mate_role: {"body": beam, "face": end}}).varset
        place_on_apply(self.doc, vs)
        return vs

    def project(self, name, value, type_id="App::PropertyLength"):
        self.pv.addProperty(type_id, name, "Project")
        setattr(self.pv, name, value)

    def pi_bent(self, station="48 in"):
        post1 = self.timber("T-Post-101")
        post2 = self.timber("T-Post-102")
        beam = self.timber("T-Beam-101", "6 in", "8 in", "10 ft")
        j1 = self.joint("101", post1, beam, face="YPos", end="EndA", station=station)
        j2 = self.joint("102", post2, beam, face="YNeg", end="EndB", station=station)
        self.doc.recompute()
        return post1, post2, beam, j1, j2

    def dims(self, body):
        from freecad.bentwizard.timber import dims_varset
        return dims_varset(body)

    def row(self, listing, section, label):
        for s in listing.sections:
            if s.title == section:
                for r in s.rows:
                    if r.label == label:
                        return r
                self.fail(f"no row {label!r} in {section!r}: "
                          f"{[r.label for r in s.rows]}")
        self.fail(f"no section {section!r}: {[s.title for s in listing.sections]}")

    def section(self, listing, title):
        for s in listing.sections:
            if s.title == title:
                return s
        self.fail(f"no section {title!r}: {[s.title for s in listing.sections]}")

    # --- where a value comes from ------------------------------------------

    def test_typed_dimension_is_set_here(self):
        from freecad.bentwizard import variables as v
        post = self.timber("T-Post-001")
        r = self.row(v.timber_listing(post), "Section and Length", "Width X")
        self.assertEqual(r.source.kind, v.HERE)
        self.assertEqual(r.set_by, "Width X · T-Post-001")
        self.assertIn("not read from another variable", r.tip)
        self.assertIs(r.target, self.dims(post))
        self.assertEqual(r.value, App.Units.Quantity(8 * IN, App.Units.Length).UserString)

    def test_project_variable_is_followed(self):
        from freecad.bentwizard import variables as v
        self.project("Span", 12 * 12 * IN)
        beam = self.timber("T-Beam-001", "6 in", "8 in", "10 ft")
        self.dims(beam).setExpression("LengthZ", "<<ProjectVars>>.Span")
        self.doc.recompute()
        r = self.row(v.timber_listing(beam), "Section and Length", "Length Z")
        self.assertEqual(r.source.kind, v.FOLLOWS)
        self.assertIs(r.source.holder, self.pv)
        self.assertEqual(r.source.prop, "Span")
        self.assertEqual(r.set_by, "Span · ProjectVars")
        self.assertIs(r.target, self.pv)       # a click goes to where it is edited

    def test_pass_through_is_skipped_but_kept_as_via(self):
        from freecad.bentwizard import variables as v
        self.project("Span", 12 * 12 * IN)
        b1 = self.timber("T-Beam-001", "6 in", "8 in", "10 ft")
        b2 = self.timber("T-Beam-002", "6 in", "8 in", "10 ft")
        self.dims(b1).setExpression("LengthZ", "<<ProjectVars>>.Span")
        self.dims(b2).setExpression("LengthZ", "<<TDim_T-Beam-001>>.LengthZ")
        self.doc.recompute()
        r = self.row(v.timber_listing(b2), "Section and Length", "Length Z")
        self.assertEqual(r.source.kind, v.FOLLOWS)
        self.assertIs(r.source.holder, self.pv)
        self.assertEqual([(o.Name, p) for o, p in r.source.via],
                         [(self.dims(b1).Name, "LengthZ")])
        self.assertEqual(r.set_by, "Span · ProjectVars")
        self.assertEqual(r.tip, "T-Beam-002.LengthZ ← T-Beam-001.LengthZ "
                                "← ProjectVars.Span")

    def test_formula_is_shown_with_what_it_reads(self):
        from freecad.bentwizard import variables as v
        self.project("Span", 12 * 12 * IN)
        self.project("Overhang", 6 * IN)
        beam = self.timber("T-Beam-001", "6 in", "8 in", "10 ft")
        self.dims(beam).setExpression(
            "LengthZ", "<<ProjectVars>>.Span - 2 * <<ProjectVars>>.Overhang")
        self.doc.recompute()
        r = self.row(v.timber_listing(beam), "Section and Length", "Length Z")
        self.assertEqual(r.source.kind, v.FORMULA)
        self.assertEqual(r.set_by, "Length Z · T-Beam-001 = ProjectVars.Span - 2 "
                                   "* ProjectVars.Overhang")
        self.assertEqual([p for _o, p in r.source.reads], ["Span", "Overhang"])
        self.assertIs(r.target, self.dims(beam))    # the formula lives here

    def test_formula_elsewhere_names_where(self):
        from freecad.bentwizard import variables as v
        self.project("Span", 12 * 12 * IN)
        b1 = self.timber("T-Beam-001", "6 in", "8 in", "10 ft")
        b2 = self.timber("T-Beam-002", "6 in", "8 in", "10 ft")
        self.dims(b1).setExpression("LengthZ", "<<ProjectVars>>.Span / 2")
        self.dims(b2).setExpression("LengthZ", "<<TDim_T-Beam-001>>.LengthZ")
        self.doc.recompute()
        r = self.row(v.timber_listing(b2), "Section and Length", "Length Z")
        self.assertEqual(r.source.kind, v.FORMULA)
        self.assertEqual(r.set_by, "Length Z · T-Beam-001 = ProjectVars.Span / 2")
        self.assertIs(r.target, self.dims(b1))

    def test_quoted_label_reference(self):
        from freecad.bentwizard import variables as v
        vs = self.doc.addObject("App::VarSet", "Shop")
        vs.Label = "Shop's Vars"
        vs.addProperty("App::PropertyLength", "Stock", "Shop")
        vs.Stock = 8 * IN
        post = self.timber("T-Post-001")
        self.dims(post).setExpression("WidthX", "<<Shop's Vars>>.Stock")
        self.doc.recompute()
        r = self.row(v.timber_listing(post), "Section and Length", "Width X")
        self.assertIs(r.source.holder, vs)
        self.assertEqual(r.set_by, "Stock · Shop's Vars")

    # --- a jointed frame ---------------------------------------------------

    def test_timber_lists_each_of_its_joints(self):
        from freecad.bentwizard import variables as v
        _p1, _p2, beam, j1, j2 = self.pi_bent()
        listing = v.timber_listing(beam)
        titles = [s.title for s in listing.sections]
        self.assertIn(f"Timber joint {j1.Label}", titles)
        self.assertIn(f"Timber joint {j2.Label}", titles)
        s = self.section(listing, f"Timber joint {j1.Label}")
        labels = [r.label for r in s.rows]
        for name in ("Tenon Length", "Housing Depth", "Peg Count"):
            self.assertIn(name, labels)
        self.assertNotIn("Host Width U", labels)        # accessors are plumbing
        self.assertNotIn("Tenon Length Min", labels)    # ranges too
        self.assertIn("Mating Timber T-Post-101", labels)
        mating = next(r for r in s.rows if r.label == "Mating Timber T-Post-101")
        self.assertEqual(mating.set_by, "Width X × Width Y · T-Post-101")
        # the station that places the beam is listed once, under Position
        self.assertNotIn("Station on T-Post-101, +Y face", labels)
        self.assertIn("Station on T-Post-101, +Y face",
                      [r.label for r in self.section(listing, "Position").rows])
        self.assertEqual(s.notes, ["This timber's End A meets T-Post-101's +Y face."])

    def test_template_fixed_parameter(self):
        from freecad.bentwizard import variables as v
        _p1, _p2, beam, j1, _j2 = self.pi_bent()
        r = self.row(v.timber_listing(beam), f"Timber joint {j1.Label}", "Peg Count")
        self.assertEqual(r.source.kind, v.FIXED)
        self.assertEqual(r.set_by, f"Peg Count · {j1.Label} (fixed)")
        self.assertIn("Fixed by its template", r.tip)
        r = self.row(v.timber_listing(beam), f"Timber joint {j1.Label}", "Tenon Length")
        self.assertEqual(r.source.kind, v.HERE)

    def test_position_of_a_seated_timber(self):
        from freecad.bentwizard import variables as v
        self.project("BeamHeight", 84 * IN)
        p1, _p2, beam, j1, _j2 = self.pi_bent(station="=<<ProjectVars>>.BeamHeight")
        s = self.section(v.timber_listing(beam), "Position")
        self.assertEqual(s.notes[0], f"Seated on {p1.Label} by {j1.Label}.")
        r = self.row(v.timber_listing(beam), "Position", "Station on T-Post-101, +Y face")
        self.assertEqual(r.set_by, "Beam Height · ProjectVars")
        # BeamHeight also places post 2's timber joint: shared
        self.assertEqual(r.drives, ["T-Post-102"])

    def test_position_of_the_anchored_timber(self):
        from freecad.bentwizard import variables as v
        p1, _p2, _beam, _j1, _j2 = self.pi_bent()
        r = self.row(v.timber_listing(p1), "Position", "Frame Origin")
        self.assertEqual(r.source.kind, v.FOLLOWS)
        self.assertEqual(r.set_by, "Frame Origin · ProjectVars")

    def test_shared_value_names_the_other_timbers(self):
        from freecad.bentwizard import variables as v
        self.project("Span", 12 * 12 * IN)
        beams = [self.timber(f"T-Beam-00{i}", "6 in", "8 in", "10 ft") for i in (1, 2, 3)]
        for b in beams:
            self.dims(b).setExpression("LengthZ", "<<ProjectVars>>.Span")
        self.doc.recompute()
        r = self.row(v.timber_listing(beams[0]), "Section and Length", "Length Z")
        self.assertEqual(r.drives, ["T-Beam-002", "T-Beam-003"])
        r = self.row(v.timber_listing(beams[0]), "Section and Length", "Width X")
        self.assertEqual(r.drives, [])

    def test_joint_listing(self):
        from freecad.bentwizard import variables as v
        _p1, _p2, beam, j1, _j2 = self.pi_bent()
        listing = v.joint_listing(j1)
        self.assertEqual(listing.title, f"Timber joint {j1.Label}")
        timbers = self.section(listing, "Timbers")
        self.assertEqual(timbers.notes, [f"Places {beam.Label}."])
        self.assertEqual([r.label for r in timbers.rows],
                         ["T-Post-101, +Y face", "Station on T-Post-101, +Y face",
                          "T-Beam-101, End A"])
        params = [r.label for r in self.section(listing, "Parameters").rows]
        self.assertEqual(sorted(params), ["Housing Depth", "Mortise Fit", "Peg Count",
                                          "Tenon Length", "Tenon Thickness", "Tenon Width"])

    def test_hand_added_binding_is_listed_under_other(self):
        from freecad.bentwizard import variables as v
        self.project("Gap", 0.0)
        post = self.timber("T-Post-001")
        pad = next(o for o in post.Group if o.TypeId == "PartDesign::Pad")
        pad.setExpression("Offset", "<<ProjectVars>>.Gap")
        self.doc.recompute()
        listing = v.timber_listing(post)
        r = self.row(listing, "Other", f"{pad.Label} · Offset")
        self.assertEqual(r.set_by, "Gap · ProjectVars")
        # the workbench's own bindings (sketch to Dims, pad to LengthZ) are not
        self.assertEqual(len(self.section(listing, "Other").rows), 1)

    def test_no_other_section_without_hand_bindings(self):
        from freecad.bentwizard import variables as v
        _p1, _p2, beam, _j1, _j2 = self.pi_bent()
        self.assertNotIn("Other", [s.title for s in v.timber_listing(beam).sections])

    def test_listing_leaves_the_document_alone(self):
        from freecad.bentwizard import variables as v
        p1, p2, beam, j1, j2 = self.pi_bent()
        self.doc.recompute()
        before = {o.Name: (o.Label, tuple(o.State)) for o in self.doc.Objects}
        for subject in (p1, p2, beam, j1, j2):
            v.listing_for(subject)
        after = {o.Name: (o.Label, tuple(o.State)) for o in self.doc.Objects}
        self.assertEqual(before, after)

    # --- from the selection -----------------------------------------------

    def test_subject_of_selection(self):
        from freecad.bentwizard import datums, frame, joint_handle
        from freecad.bentwizard import variables as v
        from freecad.bentwizard.apply import joint_components
        p1, _p2, beam, j1, _j2 = self.pi_bent()
        comp = joint_components(j1)[0]
        boolean = next(o for o in p1.Group if o.TypeId == "PartDesign::Boolean")
        datum = next(d for d in datums.datums_of(p1) if datums.joint_of(d) is not None)
        cases = {
            "timber": (beam, beam),
            "its Dims": (self.dims(beam), beam),
            "its datum": (datum, p1),
            "its pad": (next(o for o in beam.Group if o.TypeId == "PartDesign::Pad"), beam),
            "joint VarSet": (j1, j1),
            "handle": (joint_handle.find_handle(j1), j1),
            "seat": (frame.seat_of_joint(j1), j1),
            "accessors": (v._accessors_of(j1), j1),
            "component": (comp, j1),
            "component feature": (comp.Group[-1], j1),
            "Boolean in the timber": (boolean, j1),
            "ProjectVars": (self.pv, None),
        }
        for what, (obj, expected) in cases.items():
            with self.subTest(what):
                self.assertIsNotNone(obj)
                self.assertIs(v.subject_of(obj), expected)


class VariablesWordsTest(unittest.TestCase):
    """The pure helpers, under any interpreter that can import them."""

    @unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable")
    def test_words(self):
        from freecad.bentwizard import variables as v
        self.assertEqual(v.spaced("TenonLength"), "Tenon Length")
        self.assertEqual(v.spaced("WidthX"), "Width X")
        self.assertEqual(v.pretty("<<T\\'1\\'>>.Span * 2"), "T'1'.Span * 2")
        self.assertEqual(v.drives_text(["A", "B"]), "A, B")
        self.assertEqual(v.drives_text(["A", "B", "C", "D", "E"]), "A, B, C +2 more")


if __name__ == "__main__":
    unittest.main()
