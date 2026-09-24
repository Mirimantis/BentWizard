"""The flat frame: a pi bent seats by expression, a Bay edit re-spaces on
a plain recompute, a second bent ties in and swings into place, a loop
closer places nothing and still closes, Remove Joint takes the seat with
it, and the anchored timber never moves."""

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

IN = 25.4
TEMPLATE = REPO_ROOT / "library" / "Joint_HousedMT.FCStd"


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class FlatFrameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.template import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        self.doc = App.newDocument("FrameTest")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    # --- fixtures -------------------------------------------------------

    def timber(self, label, w="8 in", d="8 in", length="8 ft"):
        from freecad.bentwizard.timber import new_timber
        body, _dims = new_timber(self.doc, label, w, d, length)
        return body

    def joint(self, serial, post, beam, face="YPos", end="EndA",
              station="48 in", place=True):
        from freecad.bentwizard.apply import apply_joint
        from freecad.bentwizard.frame import place_on_apply
        vs = apply_joint(self.doc, self.spec, serial, {
            self.spec.host_role: {"body": post, "face": face, "station": station},
            self.spec.mate_role: {"body": beam, "face": end}}).varset
        if place:
            place_on_apply(self.doc, vs)
        return vs

    def pi_bent(self, tag="1", place=True, span="10 ft"):
        """post1 --end A--> beam <--end B-- post2: the beam's end A on
        post1's +Y face, its end B on post2's -Y face."""
        post1 = self.timber(f"T-Post-{tag}01")
        post2 = self.timber(f"T-Post-{tag}02")
        beam = self.timber(f"T-Beam-{tag}01", "6 in", "8 in", span)
        j1 = self.joint(f"{tag}01", post1, beam, face="YPos", end="EndA",
                        place=place)
        j2 = self.joint(f"{tag}02", post2, beam, face="YNeg", end="EndB",
                        place=place)
        self.doc.recompute()
        return post1, post2, beam, j1, j2

    def assertSeated(self, joints, mm=1e-6, deg=1e-9):
        from freecad.bentwizard.frame import joint_misfit
        for vs in joints:
            got_mm, got_deg = joint_misfit(vs)
            self.assertLess(got_mm, mm, vs.Label)
            self.assertLess(got_deg, deg, vs.Label)

    # --- the pi bent ----------------------------------------------------

    def test_pi_bent_seats(self):
        from freecad.bentwizard import frame
        post1, post2, beam, j1, j2 = self.pi_bent()
        # no Assembly anywhere: the frame is a Std Group holding timbers
        self.assertEqual([o.Label for o in self.doc.Objects
                          if o.TypeId == "Assembly::AssemblyObject"], [])
        group = frame.containing_frame(post1)
        self.assertEqual(group.TypeId, "App::DocumentObjectGroup")
        self.assertTrue(frame.is_frame_group(group))
        self.assertEqual(sorted(b.Label for b in frame.member_bodies(group)),
                         sorted([post1.Label, post2.Label, beam.Label]))
        # post1 anchors the frame; the others are seated from it
        self.assertIs(frame.anchored_timber(self.doc), post1)
        self.assertIsNotNone(frame.seat_driving(beam))
        self.assertIsNotNone(frame.seat_driving(post2))
        self.assertIs(frame.places(j1), beam)
        self.assertIs(frame.places(j2), post2)
        self.assertSeated([j1, j2])
        self.assertEqual(post1.Placement.Rotation.Angle, 0)
        self.assertEqual(post1.Placement.Base.Length, 0)
        # post centrelines 120 in + two half posts apart, along post1's +Y
        self.assertAlmostEqual(post2.Placement.Base.y / IN, 120 + 8, places=6)
        self.assertAlmostEqual(post2.Placement.Base.x / IN, 0, places=6)
        self.assertLess(post1.Shape.common(beam.Shape).Volume, 1e-6)
        self.assertLess(post2.Shape.common(beam.Shape).Volume, 1e-6)

    def test_the_seat_nests_under_the_handle(self):
        from freecad.bentwizard import frame, joint_handle
        _p1, _p2, _beam, j1, _j2 = self.pi_bent()
        seat = frame.seat_of_joint(j1)
        self.assertEqual(seat.Label, f"Seat_{j1.Label}")
        handle = joint_handle.find_handle(j1)
        self.assertIs(seat.getParentGroup(), handle)
        self.assertIs(frame.joint_of_seat(seat), j1)

    def test_bay_width_follows_the_beam(self):
        from freecad.bentwizard import frame
        from freecad.bentwizard.timber import dims_varset
        post1, post2, beam, j1, j2 = self.pi_bent()
        dims_varset(beam).LengthZ = "12 ft"
        self.doc.recompute()                 # no solve: it is an expression
        self.assertAlmostEqual(post2.Placement.Base.y / IN, 144 + 8, places=6)
        self.assertSeated([j1, j2])
        # a project variable drives it just the same
        pv = frame.project_varset(self.doc)
        pv.addProperty("App::PropertyLength", "BayClear", "Layout", "clear span")
        pv.BayClear = "10 ft"
        dims_varset(beam).setExpression("LengthZ", "<<ProjectVars>>.BayClear")
        self.doc.recompute()
        self.assertAlmostEqual(post2.Placement.Base.y / IN, 120 + 8, places=6)
        self.assertEqual(post1.Placement.Base.Length, 0)

    # --- two bents, a bay, and a loop ------------------------------------

    def bay_frame(self):
        """Two pi bents tied by two ties whose length is <<ProjectVars>>.Bay
        — the second tie closes a loop."""
        from freecad.bentwizard import frame
        post1, post2, beam1, j1, j2 = self.pi_bent("1")
        post3, post4, beam2, j3, j4 = self.pi_bent("2")
        pv = frame.project_varset(self.doc)
        pv.addProperty("App::PropertyLength", "Bay", "Layout", "bent spacing")
        pv.Bay = "10 ft"
        ties = []
        for n, (near, far) in enumerate(((post1, post3), (post2, post4)), 1):
            tie = self.timber(f"T-Tie-{n:03d}", "6 in", "8 in",
                              "=<<ProjectVars>>.Bay")
            ties.append((
                tie,
                self.joint(f"30{2 * n - 1}", near, tie, face="XPos", end="EndA"),
                self.joint(f"30{2 * n}", far, tie, face="XNeg", end="EndB"),
            ))
        self.doc.recompute()
        joints = [j1, j2, j3, j4] + [j for _t, a, b in ties for j in (a, b)]
        return pv, (post1, post2, post3, post4), ties, joints

    def test_second_bent_ties_into_the_frame(self):
        from freecad.bentwizard import datums, frame
        post1, _post2, _beam1, _j1, _j2 = self.pi_bent("1")
        post3, _post4, _beam2, _j3, _j4 = self.pi_bent("2")
        # bent 2 was built loose: only one timber in a document is ever
        # anchored, the rest of a second component roots provisionally
        self.assertIs(frame.anchored_timber(self.doc), post1)
        tie = self.timber("T-Tie-001", "6 in", "8 in", "12 ft")
        t1 = self.joint("301", post1, tie, face="XPos", end="EndA")
        t2 = self.joint("302", post3, tie, face="XNeg", end="EndB")
        self.doc.recompute()
        # bent 2 swung in behind the tie; bent 1 never moved
        self.assertAlmostEqual(datums.global_placement(post3).Base.x / IN,
                               144 + 8, places=6)
        self.assertEqual(datums.global_placement(post1).Base.Length, 0)
        self.assertIs(frame.anchored_timber(self.doc), post1)
        self.assertSeated([t1, t2])
        self.assertIs(frame.root_of(post3), post1)

    def test_second_bent_ties_in_away_from_its_root(self):
        """The re_root path: the tie lands on post4, which bent 2 does
        NOT root at (post3 → beam2 → post4), so the seats between post4
        and post3 reverse and the whole bent swings in rigidly behind
        the tie. The simple test above ties at the root and never
        reverses anything."""
        from freecad.bentwizard import datums, frame
        post1, _post2, _beam1, _j1, _j2 = self.pi_bent("1")
        post3, post4, _beam2, _j3, _j4 = self.pi_bent("2")
        self.assertIs(frame.root_of(post4), post3)      # not its own root
        before = (datums.global_placement(post4).Base
                  - datums.global_placement(post3).Base).Length
        tie = self.timber("T-Tie-001", "6 in", "8 in", "12 ft")
        t1 = self.joint("301", post1, tie, face="XPos", end="EndA")
        t2 = self.joint("302", post4, tie, face="XNeg", end="EndB")
        self.doc.recompute()
        # bent 2 is rigid: post3 kept its offset from post4 through the
        # reversal, and bent 1 and the anchor never moved
        after = (datums.global_placement(post4).Base
                 - datums.global_placement(post3).Base).Length
        self.assertAlmostEqual(after, before, places=6)
        self.assertEqual(datums.global_placement(post1).Base.Length, 0)
        self.assertIs(frame.anchored_timber(self.doc), post1)
        self.assertAlmostEqual(datums.global_placement(post4).Base.x / IN,
                               144 + 8, places=6)
        # every joint in both bents still seated, and the whole document
        # is now one placement component rooted at the anchor
        self.assertSeated([t1, t2, *self.doc.getObjectsByLabel("J-HousedMT-101"),
                           *self.doc.getObjectsByLabel("J-HousedMT-102"),
                           *self.doc.getObjectsByLabel("J-HousedMT-201"),
                           *self.doc.getObjectsByLabel("J-HousedMT-202")])
        for body in (post3, post4):
            self.assertIs(frame.root_of(body), post1, body.Label)

    def test_loop_closer_places_nothing_and_still_closes(self):
        from freecad.bentwizard import frame
        _pv, posts, ties, joints = self.bay_frame()
        closers = [vs for vs in joints if frame.places(vs) is None]
        self.assertEqual(len(closers), 1)
        self.assertIsNone(frame.seat_of_joint(closers[0]))
        self.assertSeated(joints, mm=1e-9, deg=1e-9)
        self.assertIs(frame.anchored_timber(self.doc), posts[0])

    def test_bay_edit_respaces_exactly(self):
        """The headline: one variable, a plain recompute, every joint
        still seated — loop closers included — and nothing left Touched."""
        from freecad.bentwizard import datums, frame
        pv, posts, _ties, joints = self.bay_frame()
        group = frame.containing_frame(posts[0])
        for value, want in (("12 ft", 144), ("8 ft", 96)):
            pv.Bay = value
            self.doc.recompute()             # no solve, anywhere
            self.assertAlmostEqual(datums.global_placement(posts[2]).Base.x / IN,
                                   want + 8, places=6)
            self.assertSeated(joints, mm=1e-9, deg=1e-9)
            self.assertEqual(datums.global_placement(posts[0]).Base.Length, 0)
            self.assertTrue(group.Placement.isIdentity()
                            if hasattr(group, "Placement") else True)
            unhealthy = [o.Label for o in self.doc.Objects
                         if "Touched" in o.State or "Invalid" in o.State
                         or "Error" in o.State]
            self.assertEqual(unhealthy, [], value)

    # --- removal, repair, re-seating -------------------------------------

    def test_remove_joint_removes_the_seat_and_moves_nothing(self):
        from freecad.bentwizard import frame
        from freecad.bentwizard.apply import remove_joint
        _post1, post2, _beam, j1, j2 = self.pi_bent()
        where = App.Placement(post2.Placement)
        self.assertIsNotNone(frame.seat_of_joint(j2))
        remove_joint(j2)
        self.doc.recompute()
        self.assertEqual([o.Label for o in self.doc.Objects
                          if frame.is_seat(o) and "002" in o.Label], [])
        # the timber it placed stays exactly where it stood, now loose
        self.assertIsNone(frame.seat_driving(post2))
        self.assertLess((post2.Placement.Base - where.Base).Length, 1e-9)
        self.assertIsNotNone(frame.seat_of_joint(j1))

    def test_reseating_replaces(self):
        from freecad.bentwizard import frame
        _p1, _p2, _beam, _j1, j2 = self.pi_bent()
        seat = frame.seat_of_joint(j2)
        frame.place_on_apply(self.doc, j2)
        self.doc.recompute()
        self.assertIs(frame.seat_of_joint(j2), seat)
        self.assertEqual(len([o for o in self.doc.Objects if frame.is_seat(o)]), 2)

    def test_seat_timbers_bulk(self):
        from freecad.bentwizard import frame
        post1, post2, beam, j1, j2 = self.pi_bent(place=False)
        built = frame.rebuild_seats(self.doc, [post1, post2, beam],
                                    label="Frame-A", principal=post1)
        self.doc.recompute()
        self.assertEqual(built.frame.Label, "Frame-A")
        self.assertEqual((built.closures, built.misfits, built.skipped),
                         ([], [], []))
        self.assertEqual(sorted(v.Label for v in built.seated),
                         sorted([j1.Label, j2.Label]))
        self.assertIs(frame.containing_frame(beam), built.frame)
        self.assertIs(frame.anchored_timber(self.doc), post1)
        self.assertSeated([j1, j2])

    def test_repair_rebuilds_only_what_is_missing(self):
        from freecad.bentwizard import frame
        post1, post2, beam, j1, j2 = self.pi_bent()
        seat1 = frame.seat_of_joint(j1)
        frame.unseat(j2)
        built = frame.rebuild_seats(self.doc, [post1, post2, beam])
        self.doc.recompute()
        self.assertIs(frame.seat_of_joint(j1), seat1)       # untouched
        self.assertEqual([v.Label for v in built.seated], [j2.Label])
        self.assertSeated([j1, j2])

    def test_output_lints_clean(self):
        from freecad.bentwizard.linter import lint
        self.pi_bent()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "frame.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
