"""Datums: the face table, accessors, pairing, and the seat.

Sections are deliberately asymmetric (6 x 10 post, 4 x 8 girt) so a
wrong U/V/W binding or a swapped host/mate is visible as a wrong number,
never a coincidence. The face-table rows are asserted against the
resolved placement (finding #10), and the seat against all four faces
x both ends.
"""

import itertools
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


def inches(q):
    """A quantity in inches, rounded past float noise."""
    return round(float(q) / IN, 6)


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class DatumTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("DatumTest")
        from freecad.bentwizard.timber import new_timber
        self.post, self.pdims = new_timber(self.doc, "T-Post-001", "6 in", "10 in", "8 ft")
        self.girt, self.gdims = new_timber(self.doc, "T-Girt-001", "4 in", "8 in", "6 ft")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    # --- the face table ----------------------------------------------

    def test_every_row_places_and_verifies(self):
        from freecad.bentwizard import datums, facetable
        for face in facetable.FACES:
            d = datums.add_datum(self.post, face, "48 in")
            self.assertEqual(datums.verify_datum(d), [], face)
            self.assertEqual(d.MapMode, "Deactivated")
            self.assertTrue(facetable.same_rotation(
                d.Placement.Rotation.Q, facetable.FACE_TABLE[face].quaternion), face)
            self.assertAlmostEqual(d.Placement.Base.z / IN, 48, places=9)

    def test_axis_rule_on_every_row(self):
        """Local Z outward, local Y toward end A on a side face, X = Y x Z;
        and -Z is into the material."""
        from freecad.bentwizard import datums, facetable
        for face in facetable.PLACES:
            if face in facetable.FACES:
                d = datums.add_datum(self.post, face, "48 in")
            else:
                d = datums.end_datum(self.post, face)
            r = d.Placement.Rotation
            x, y, z = (r.multVec(App.Vector(*v)) for v in
                       ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
            self.assertLess((z - App.Vector(*facetable.FACE_TABLE[face].outward)).Length,
                            1e-9, face)
            if face in facetable.FACES:
                self.assertLess((y - App.Vector(0, 0, -1)).Length, 1e-9, face)
            self.assertLess((x - y.cross(z)).Length, 1e-9, face)
            inside = d.Placement.Base + z * (-1.0)
            self.assertTrue(self.post.Shape.isInside(inside, 1e-6, True), face)

    def test_positions_follow_the_section(self):
        from freecad.bentwizard import datums
        xp = datums.add_datum(self.post, "XPos", "48 in")
        yn = datums.add_datum(self.post, "YNeg", "48 in")
        self.assertAlmostEqual(xp.Placement.Base.x / IN, 3, places=9)
        self.assertAlmostEqual(yn.Placement.Base.y / IN, -5, places=9)
        self.pdims.WidthX = "8 in"
        self.pdims.WidthY = "12 in"
        self.doc.recompute()
        self.assertAlmostEqual(xp.Placement.Base.x / IN, 4, places=9)
        self.assertAlmostEqual(yn.Placement.Base.y / IN, -6, places=9)
        self.assertEqual(datums.verify_datum(xp), [])

    def test_accessors_read_the_host_per_row(self):
        from freecad.bentwizard import datums
        yp = datums.add_datum(self.post, "YPos", "48 in")
        self.assertEqual(tuple(map(inches, (yp.WidthU, yp.WidthV, yp.DepthW))), (6, 96, 10))
        xp = datums.add_datum(self.post, "XPos", "48 in")
        self.assertEqual(tuple(map(inches, (xp.WidthU, xp.WidthV, xp.DepthW))), (10, 96, 6))
        b = datums.end_datum(self.post, "EndB")
        self.assertEqual(tuple(map(inches, (b.WidthU, b.WidthV, b.DepthW))), (6, 10, 96))
        self.assertEqual(inches(b.Station), 96)
        a = datums.end_datum(self.post, "EndA")
        self.assertEqual(a.Station, 0)

    def test_station_may_be_an_expression(self):
        from freecad.bentwizard import datums
        pv = self.doc.addObject("App::VarSet", "PV")
        pv.Label = "ProjectVars"
        pv.addProperty("App::PropertyLength", "GirtLine", "Layout", "girt line")
        pv.GirtLine = "48 in"
        d = datums.add_datum(self.post, "YPos", "=<<ProjectVars>>.GirtLine")
        self.assertAlmostEqual(d.Placement.Base.z / IN, 48, places=9)
        pv.GirtLine = "60 in"
        self.doc.recompute()
        self.assertAlmostEqual(d.Placement.Base.z / IN, 60, places=9)
        self.assertEqual(datums.verify_datum(d), [])

    def test_labels_and_names(self):
        from freecad.bentwizard import datums
        d1 = datums.add_datum(self.post, "YPos", "48 in")
        d2 = datums.add_datum(self.post, "YPos", "60 in")
        self.assertEqual(d1.Label, "D_T-Post-001_YPos_001")
        self.assertEqual(d2.Label, "D_T-Post-001_YPos_002")
        self.assertEqual(d1.Name, "D_T_Post_001_YPos_001")
        self.assertEqual(datums.describe(d1).split(" @ ")[0], "+Y")
        self.assertEqual(len(datums.datums_of(self.post)), 4)   # ends + 2

    def test_refusals(self):
        from freecad.bentwizard import datums
        from freecad.bentwizard.datums import DatumError
        with self.assertRaises(DatumError):
            datums.add_datum(self.post, "YPos")          # side face needs a station
        with self.assertRaises(DatumError):
            datums.add_datum(self.post, "Top", "48 in")  # not a face
        loose = self.doc.addObject("PartDesign::Body", "Loose")
        with self.assertRaises(DatumError):
            datums.add_datum(loose, "EndA")              # not a timber
        before = len(self.doc.Objects)
        with self.assertRaises(DatumError):
            datums.add_datum(self.post, "YPos", "=<<Nowhere>>.Nothing")
        self.assertEqual(len(self.doc.Objects), before)  # no debris

    # --- pairing ---------------------------------------------------------

    def joint_varset(self, label="J-Test-001"):
        vs = self.doc.addObject("App::VarSet", "JointVS")
        vs.Label = label
        return vs

    def test_pair_binds_the_varset_accessors_through_both_datums(self):
        from freecad.bentwizard import datums
        host = datums.add_datum(self.post, "YPos", "48 in")
        mate = datums.end_datum(self.girt, "EndB")
        vs = self.joint_varset()
        datums.pair(host, mate, vs)
        self.doc.recompute()
        self.assertEqual(host.MateDatum, mate.Name)
        self.assertEqual(mate.MateDatum, host.Name)
        self.assertEqual(host.Joint, vs.Name)
        self.assertIs(datums.mate_of(host), mate)
        self.assertIs(datums.joint_of(mate), vs)
        # the accessors live on the joint's own Accessors_ VarSet, not on
        # the joint VarSet, which holds only what a framer edits
        acc = datums.accessors_varset(vs)
        self.assertIsNot(acc, vs)
        self.assertEqual(acc.Label, "Accessors_" + vs.Label)
        self.assertFalse(hasattr(vs, "HostWidthU"))
        self.assertEqual(tuple(map(inches, (acc.HostWidthU, acc.HostWidthV,
                                            acc.HostDepthW))),
                         (6, 96, 10))
        self.assertEqual(tuple(map(inches, (acc.MateWidthU, acc.MateWidthV,
                                            acc.MateDepthW))),
                         (4, 8, 72))
        self.assertEqual(datums.datums_of_joint(vs), [host, mate])
        # the host is recorded, not inferred from an expression
        self.assertEqual(vs.HostDatum, host.Name)
        self.assertIs(datums.host_datum(vs), host)
        # the placement accessors: what a component binds to, so that no
        # Body ever reads a datum directly
        self.assertEqual(acc.HostPlacement, host.Placement)
        self.assertEqual(acc.MatePlacement, mate.Placement)
        self.assertEqual(datums.side_of(vs, host), "Host")
        self.assertEqual(datums.side_of(vs, mate), "Mate")
        self.assertEqual(datums.placement_binding(vs, mate),
                         f"<<{acc.Label}>>.MatePlacement")
        with self.assertRaises(datums.DatumError):
            datums.placement_binding(vs, datums.end_datum(self.girt, "EndA"))
        # the girt's section change reaches the host side through the accessors
        self.gdims.WidthX = "5 in"
        self.doc.recompute()
        self.assertEqual(inches(acc.MateWidthU), 5)
        # no datum reads another datum (object-granular cycle)
        for d in (host, mate):
            self.assertFalse(any("D_" in e for _p, e in d.ExpressionEngine))

    def test_pair_refuses_paired_or_same_timber(self):
        from freecad.bentwizard import datums
        from freecad.bentwizard.datums import DatumError
        host = datums.add_datum(self.post, "YPos", "48 in")
        mate = datums.end_datum(self.girt, "EndB")
        datums.pair(host, mate, self.joint_varset())
        with self.assertRaises(DatumError):
            datums.pair(host, datums.end_datum(self.girt, "EndA"),
                        self.joint_varset("J-Test-002"))
        with self.assertRaises(DatumError):
            datums.pair(datums.end_datum(self.post, "EndA"),
                        datums.end_datum(self.post, "EndB"),
                        self.joint_varset("J-Test-003"))

    def test_unpair_clears_both_sides(self):
        from freecad.bentwizard import datums
        host = datums.add_datum(self.post, "YPos", "48 in")
        mate = datums.end_datum(self.girt, "EndB")
        vs = self.joint_varset()
        datums.pair(host, mate, vs)
        datums.unpair(mate)
        self.doc.recompute()
        for d in (host, mate):
            self.assertFalse(datums.is_paired(d))
            self.assertEqual(d.Joint, "")
        acc = datums.accessors_varset(vs)
        self.assertEqual(acc.HostWidthU, 0)
        self.assertEqual(acc.HostPlacement, App.Placement())
        self.assertEqual(acc.ExpressionEngine, [])
        self.assertEqual(vs.HostDatum, "")
        self.assertEqual(datums.datums_of_joint(vs), [])
        # and the datums can pair again
        datums.pair(host, mate, vs)

    # --- the seat ----------------------------------------------------------

    def test_seat_delta_lands_the_mate_antiparallel_on_every_face_and_end(self):
        from freecad.bentwizard import datums, facetable
        from freecad.bentwizard.timber import new_timber
        for face, end in itertools.product(facetable.FACES, facetable.ENDS):
            girt, _ = new_timber(self.doc, f"T-G-{face}-{end}", "4 in", "8 in", "6 ft")
            girt.Placement = App.Placement(App.Vector(700, 300, -200),
                                           App.Rotation(App.Vector(1, 1, 0), 37))
            host = datums.add_datum(self.post, face, "48 in")
            mate = datums.end_datum(girt, end)
            self.doc.recompute()
            girt.Placement = datums.seat_delta(host, mate).multiply(girt.Placement)
            self.doc.recompute()
            mm, deg = datums.misfit(host, mate)
            self.assertLess(mm, 1e-6, (face, end))
            self.assertLess(deg, 1e-9, (face, end))
            # antiparallel: the mate's Z is the host's -Z
            hz = host.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
            mz = mate.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
            self.assertLess((hz + mz).Length, 1e-9, (face, end))
            # the girt sits outboard of the post, touching at the face, centred
            self.assertLess(self.post.Shape.common(girt.Shape).Volume, 1e-6, (face, end))
            n = hz
            gc = girt.Shape.CenterOfMass - host.getGlobalPlacement().Base
            along = gc.dot(n)
            self.assertAlmostEqual(along / IN, 36, places=6, msg=(face, end))
            self.assertLess((gc - n * along).Length, 1e-6, (face, end))
            # the girt's WidthY runs along the post (the Y-flip convention)
            gy = girt.Placement.Rotation.multVec(App.Vector(0, 1, 0))
            self.assertAlmostEqual(abs(gy.z), 1, places=9, msg=(face, end))

    def test_parity(self):
        from freecad.bentwizard import datums, facetable
        self.assertEqual([facetable.parity(f) for f in facetable.PLACES],
                         [1, -1, 1, -1, -1, 1])
        self.assertEqual(datums.parity(datums.end_datum(self.post, "EndA")), -1)

    # --- persistence --------------------------------------------------------

    def test_survives_reload(self):
        from freecad.bentwizard import datums
        host = datums.add_datum(self.post, "XNeg", "48 in")
        datums.pair(host, datums.end_datum(self.girt, "EndA"), self.joint_varset())
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "d.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.doc.recompute()
            host = self.doc.getObject("D_T_Post_001_XNeg_001")
            self.assertEqual(datums.verify_datum(host), [])
            self.assertTrue(datums.is_paired(host))
            vs = datums.joint_of(host)
            # the accessor VarSet and the HostDatum record survive a
            # round trip, so the pairing resolves without the old sniff
            self.assertEqual(inches(datums.accessors_varset(vs).MateWidthU), 4)
            self.assertEqual(datums.datums_of_joint(vs)[0], host)
            self.assertIs(datums.host_datum(vs), host)


if __name__ == "__main__":
    unittest.main()
