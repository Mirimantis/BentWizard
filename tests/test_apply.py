"""Apply Timber Joint: the copy mechanism, the seat, and the mirror rule.

The acceptance bar for the rev-2 mechanism. Sections are asymmetric so
a wrong binding is a wrong number, and the placement matrix runs every
host face against both mate ends: the removed and added volumes must
not depend on where the joint lands, the seated girt's material must
lie exactly where the post's cut is, and both timbers must stay one
solid. The parity test uses a deliberately lopsided template to pin
"a component keeps its timber-local offsets" on ends AND opposite
faces.
"""

import importlib.util
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
    import Part
    _repo_path.graft()
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False

IN = 25.4
IN3 = IN ** 3
LIBRARY = REPO_ROOT / "library"
HOUSED_MT = LIBRARY / "Joint_HousedMT.FCStd"
BUTT = LIBRARY / "Joint_Butt.FCStd"

POST = (8, 8, 96)
GIRT = (6, 8, 72)
# Removed from the post: the housing, plus the mortise BELOW the housing
# floor (the prisms overlap by HousingDepth). Added to the girt: the
# shoulder block through the housing, plus the tenon beyond it.
HOUSING = 6 * 8 * 0.5                    # MateWidthU x MateWidthV x HousingDepth
MORTISE = 2 * 6 * (4 + 1 / 16)           # TenonThickness x TenonWidth x (length + fit)
SHOULDER = 6 * 8 * 0.5
TENON = 2 * 6 * 4


def _centroid(shape):
    """Volume-weighted centre of a shape's solids (a Boolean result is
    a Compound, which carries no CenterOfMass of its own)."""
    total = App.Vector()
    volume = 0.0
    for solid in shape.Solids:
        total += solid.CenterOfMass * solid.Volume
        volume += solid.Volume
    return total * (1.0 / volume)


def _build_library_module():
    """scripts/build_library.py as a module (its helpers author the
    lopsided template the parity test needs)."""
    path = REPO_ROOT / "scripts" / "build_library.py"
    spec = importlib.util.spec_from_file_location("build_library", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class ApplyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.template import TemplateSpec
        cls.spec = TemplateSpec(HOUSED_MT)
        cls.butt = TemplateSpec(BUTT)

    def setUp(self):
        from freecad.bentwizard.timber import new_timber
        self.doc = App.newDocument("ApplyTest")
        self.post, self.pdims = new_timber(self.doc, "T-Post-001", "8 in", "8 in", "8 ft")
        self.girt, self.gdims = new_timber(self.doc, "T-Girt-001", "6 in", "8 in", "6 ft")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def apply(self, spec=None, face="YPos", end="EndB", station="48 in",
              serial="001", values=None, post=None, girt=None):
        from freecad.bentwizard.apply import apply_joint
        spec = spec or self.spec
        targets = {spec.host_role: {"body": post or self.post, "face": face,
                                    "station": station},
                   spec.mate_role: {"body": girt or self.girt, "face": end}}
        return apply_joint(self.doc, spec, serial, targets, values=values)

    def volume(self, body):
        return round(body.Shape.Volume / IN3, 6)

    def lint(self):
        from freecad.bentwizard.linter import lint
        self.doc.recompute()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "a.FCStd")
            self.doc.saveAs(path)
            return [str(f) for f in lint(path)]

    # --- the basic application ------------------------------------------

    def test_datum_children_stay_with_their_timber(self):
        """Adam's second GUI round: editing a girt's WidthX raised
        'Link(s) to object(s) ... go out of the allowed scope'. FreeCAD
        files a datum's child axes under the FIRST GeoFeatureGroup in
        the datum's in-list, so a component Body whose Placement read
        the datum could claim them. Components bind to the VarSet's
        placement accessors instead; nothing but the owning timber may
        be a GeoFeatureGroup in a datum's in-list."""
        from freecad.bentwizard import datums
        from freecad.bentwizard.assemble import assimilate_joint
        from freecad.bentwizard.timber import new_timber
        post2, _ = new_timber(self.doc, "T-Post-002", "8 in", "8 in", "8 ft")
        j1 = self.apply(end="EndA").varset
        j2 = self.apply(post=post2, face="YNeg", end="EndB", serial="002").varset
        assimilate_joint(self.doc, j1)
        assimilate_joint(self.doc, j2)
        self.gdims.WidthX = "5 in"
        self.doc.recompute()
        bad = [o.Label for o in self.doc.Objects
               if "Invalid" in o.State or "Error" in o.State]
        self.assertEqual(bad, [])
        gfg = "App::GeoFeatureGroupExtension"
        for d in datums.all_datums(self.doc):
            owner = datums.owner(d)
            for child in d.OutList:
                if child.TypeId in ("App::Line", "App::Plane", "App::Point"):
                    self.assertIs(child.getParentGeoFeatureGroup(), owner, d.Label)
            groups = [o.Label for o in d.InList if o.hasExtension(gfg)]
            self.assertEqual(groups, [owner.Label], d.Label)
        for comp in [o for o in self.doc.Objects if hasattr(o, "ComponentRole")]:
            holder = next((m for m in self.doc.Objects
                           if m.TypeId == "Part::Mirroring" and m.Source is comp), comp)
            exprs = dict((p.lstrip("."), e) for p, e in holder.ExpressionEngine)
            self.assertRegex(exprs.get("Placement", ""),
                             r"<<J-HousedMT-00[12]>>\.(Host|Mate)Placement$", comp.Label)

    def test_volumes_and_objects(self):
        from freecad.bentwizard import datums, joint_handle, measure
        from freecad.bentwizard.apply import joint_components, joint_datums, joint_members
        applied = self.apply()
        vs = applied.varset
        self.assertEqual(vs.Label, "J-HousedMT-001")
        self.assertEqual(vs.TemplateSource, "Joint_HousedMT")
        self.assertEqual(self.volume(self.post), round(8 * 8 * 96 - HOUSING - MORTISE, 6))
        self.assertEqual(self.volume(self.girt), round(6 * 8 * 72 + SHOULDER + TENON, 6))
        self.assertTrue(measure.is_whole(self.post) and measure.is_whole(self.girt))
        self.assertEqual([c.Label for c in joint_components(vs)],
                         ["Mortise.HousedMT.001", "Tenon.HousedMT.001"])
        self.assertEqual(sorted(b.Label for b in applied.booleans),
                         ["Cut.Mortise.HousedMT.001", "Fuse.Tenon.HousedMT.001"])
        host, mate = joint_datums(vs)
        self.assertIs(datums.owner(host), self.post)
        self.assertIs(datums.owner(mate), self.girt)
        self.assertEqual(datums.face_of(host), "YPos")
        self.assertEqual(datums.face_of(mate), "EndB")
        self.assertEqual(round(vs.MateWidthU / IN, 6), 6)
        handle = joint_handle.find_handle(vs)
        self.assertIsNotNone(handle)
        self.assertIs(handle.Datum, host)
        self.assertIn(vs, handle.Group)
        members = {o.Label for o in joint_members(vs)}
        self.assertTrue({"Mortise.HousedMT.001", "Tenon.HousedMT.001",
                         "Cut.Mortise.HousedMT.001", "Fuse.Tenon.HousedMT.001"} <= members)
        self.assertEqual(applied.warnings, [])
        # order length reads the tenon
        self.assertAlmostEqual(measure.order_length(self.girt) / IN, 72 + 4.5, places=9)
        self.assertEqual(measure.end_projection(self.girt), (0.0, round(4.5 * IN, 6)))
        self.assertEqual(self.lint(), [])

    def test_parameters_drive_both_halves(self):
        applied = self.apply(values={"TenonLength": "5 in"})
        vs = applied.varset
        self.assertEqual(self.volume(self.post),
                         round(8 * 8 * 96 - HOUSING - 2 * 6 * (5 + 1 / 16), 6))
        self.assertEqual(self.volume(self.girt), round(6 * 8 * 72 + SHOULDER + 2 * 6 * 5, 6))
        vs.TenonThickness = "3 in"
        self.doc.recompute()
        self.assertEqual(self.volume(self.post),
                         round(8 * 8 * 96 - HOUSING - 3 * 6 * (5 + 1 / 16), 6))
        self.assertEqual(self.volume(self.girt), round(6 * 8 * 72 + SHOULDER + 3 * 6 * 5, 6))
        # the girt's section reaches the housing through the VarSet accessors
        self.gdims.WidthX = "5 in"
        self.doc.recompute()
        self.assertEqual(self.volume(self.post),
                         round(8 * 8 * 96 - 5 * 8 * 0.5 - 3 * 6 * (5 + 1 / 16), 6))

    def test_expression_parameter(self):
        pv = self.doc.addObject("App::VarSet", "PV")
        pv.Label = "ProjectVars"
        pv.addProperty("App::PropertyLength", "Tenon", "Layout", "tenon")
        pv.Tenon = "3 in"
        self.apply(values={"TenonLength": "=<<ProjectVars>>.Tenon"})
        self.assertEqual(self.volume(self.girt), round(6 * 8 * 72 + SHOULDER + 2 * 6 * 3, 6))
        pv.Tenon = "4 in"
        self.doc.recompute()
        self.assertEqual(self.volume(self.girt), round(6 * 8 * 72 + SHOULDER + TENON, 6))

    def test_station_moves_the_joint(self):
        from freecad.bentwizard.apply import joint_datums
        applied = self.apply()
        host = joint_datums(applied.varset)[0]
        cut_z_before = self._cut_centroid(self.post).z
        host.Station = "60 in"
        self.doc.recompute()
        self.assertAlmostEqual((self._cut_centroid(self.post).z - cut_z_before) / IN, 12,
                               places=6)
        self.assertEqual(self.volume(self.post), round(8 * 8 * 96 - HOUSING - MORTISE, 6))

    def _cut_centroid(self, timber):
        """Centroid of the material removed from a timber, in its own frame."""
        from freecad.bentwizard import measure
        stick = Part.makeBox(*(float(getattr(self.pdims if timber is self.post else self.gdims, d))
                               for d in ("WidthX", "WidthY", "LengthZ")))
        dims = self.pdims if timber is self.post else self.gdims
        stick.Placement = App.Placement(App.Vector(-float(dims.WidthX) / 2,
                                                   -float(dims.WidthY) / 2, 0),
                                        App.Rotation())
        removed = stick.cut(measure.local_shape(timber))
        return _centroid(removed)

    # --- the matrix -----------------------------------------------------

    def test_matrix_every_face_and_end(self):
        from freecad.bentwizard import assemble, facetable, measure
        from freecad.bentwizard.timber import new_timber
        post_cut = round(8 * 8 * 96 - HOUSING - MORTISE, 6)
        girt_add = round(6 * 8 * 72 + SHOULDER + TENON, 6)
        for face, end in itertools.product(facetable.FACES, facetable.ENDS):
            doc = App.newDocument("Matrix")
            try:
                post, _ = new_timber(doc, "T-Post-001", "8 in", "8 in", "8 ft")
                girt, _ = new_timber(doc, "T-Girt-001", "6 in", "8 in", "6 ft")
                girt.Placement = App.Placement(App.Vector(900, -400, 300),
                                               App.Rotation(App.Vector(1, 1, 0), 37))
                from freecad.bentwizard.apply import apply_joint
                vs = apply_joint(doc, self.spec, "001", {
                    self.spec.host_role: {"body": post, "face": face, "station": "48 in"},
                    self.spec.mate_role: {"body": girt, "face": end}}).varset
                self.assertEqual(round(post.Shape.Volume / IN3, 6), post_cut, (face, end))
                self.assertEqual(round(girt.Shape.Volume / IN3, 6), girt_add, (face, end))
                assemble.assimilate_joint(doc, vs)
                mm, deg = assemble.joint_misfit(vs)
                self.assertLess(mm, 1e-6, (face, end))
                self.assertLess(deg, 1e-9, (face, end))
                self.assertTrue(measure.is_whole(post) and measure.is_whole(girt), (face, end))
                self.assertEqual(post.Placement.Rotation.Angle, 0, (face, end))
                # the seated girt's material lies exactly where the post's cut is:
                # no interference, and shoulder + tenon inside the post's stick envelope
                self.assertLess(post.Shape.common(girt.Shape).Volume / IN3, 1e-6, (face, end))
                envelope = Part.makeBox(8 * IN, 8 * IN, 96 * IN)
                envelope.Placement = App.Placement(App.Vector(-4 * IN, -4 * IN, 0),
                                                   App.Rotation())
                envelope.Placement = post.getGlobalPlacement().multiply(envelope.Placement)
                inside = girt.Shape.common(envelope).Volume / IN3
                self.assertAlmostEqual(inside, SHOULDER + TENON, places=6, msg=(face, end))
            finally:
                App.closeDocument(doc.Name)

    def test_parity_keeps_timber_local_offsets(self):
        """A lopsided template — cutter and adder each displaced (+1, +1/2)
        in in their own X, Y — applied on every face and both ends: the
        cut sits at the same post-local offset on opposite faces, the
        tenon at the same girt-local offset on both ends. That is the
        mirror rule, verified rather than argued."""
        from freecad.bentwizard import component, datums, facetable, naming
        from freecad.bentwizard.apply import apply_joint
        from freecad.bentwizard.template import TemplateSpec
        from freecad.bentwizard.timber import new_timber
        bl = _build_library_module()
        with tempfile.TemporaryDirectory() as td:
            tdoc = App.newDocument("Lopsided")
            post, girt, host, mate, vs = bl.skeleton(tdoc, "Lop")
            J = f"<<{vs.Label}>>"
            bl.add_param(vs, "Depth", "App::PropertyLength", 3 * IN, "cut depth")
            cutter = component.new_component(tdoc, "Notch.Lop.000", naming.COMPONENT_CUTTER,
                                             1, vs, host)
            component.add_prism(cutter, "NotchPrism", "2 in", "3 in", J + ".Depth",
                                direction=-1, offset=(1 * IN, 0.5 * IN))
            adder = component.new_component(tdoc, "Tongue.Lop.000", naming.COMPONENT_ADDER,
                                            2, vs, mate)
            component.add_prism(adder, "TonguePrism", "2 in", "3 in", J + ".Depth",
                                direction=+1, offset=(1 * IN, 0.5 * IN))
            tdoc.recompute()
            component.apply_boolean(post, cutter, naming.COMPONENT_CUTTER)
            component.apply_boolean(girt, adder, naming.COMPONENT_ADDER)
            tdoc.recompute()
            path = Path(td) / "Joint_Lop.FCStd"
            tdoc.saveAs(str(path))
            App.closeDocument(tdoc.Name)
            spec = TemplateSpec(path)

            cut_offsets, add_offsets = {}, {}
            for face, end in itertools.product(facetable.FACES, facetable.ENDS):
                doc = App.newDocument("Parity")
                try:
                    p, pd = new_timber(doc, "T-Post-001", "8 in", "8 in", "8 ft")
                    g, gd = new_timber(doc, "T-Girt-001", "6 in", "8 in", "6 ft")
                    apply_joint(doc, spec, "001", {
                        spec.host_role: {"body": p, "face": face, "station": "48 in"},
                        spec.mate_role: {"body": g, "face": end}})
                    # removed material on the post, post-local
                    stick = Part.makeBox(8 * IN, 8 * IN, 96 * IN)
                    stick.Placement = App.Placement(App.Vector(-4 * IN, -4 * IN, 0),
                                                    App.Rotation())
                    removed = _centroid(stick.cut(p.Shape))
                    self.assertAlmostEqual(stick.cut(p.Shape).Volume / IN3, 2 * 3 * 3,
                                           places=6, msg=(face, end))
                    cut_offsets[face] = (round(removed.x / IN, 6), round(removed.y / IN, 6),
                                         round(removed.z / IN, 6))
                    # added material on the girt, girt-local
                    added = g.Shape.cut(Part.makeBox(6 * IN, 8 * IN, 72 * IN,
                                                     App.Vector(-3 * IN, -4 * IN, 0)))
                    self.assertAlmostEqual(added.Volume / IN3, 2 * 3 * 3, places=6,
                                           msg=(face, end))
                    c = _centroid(added)
                    add_offsets[end] = (round(c.x / IN, 6), round(c.y / IN, 6))
                finally:
                    App.closeDocument(doc.Name)
            # ends: same girt-local (x, y) offsets — the authored (+1, +1/2)
            self.assertEqual(add_offsets["EndA"], add_offsets["EndB"])
            self.assertEqual(add_offsets["EndB"], (1.0, 0.5))
            # opposite faces: same post-local offset along the axis the
            # datum's X runs (x for the Y faces, y for the X faces) and the
            # same z (the datum's Y runs along the post toward end A)
            self.assertEqual(cut_offsets["YPos"][0], cut_offsets["YNeg"][0])
            self.assertEqual(cut_offsets["YPos"][2], cut_offsets["YNeg"][2])
            self.assertEqual(cut_offsets["XPos"][1], cut_offsets["XNeg"][1])
            self.assertEqual(cut_offsets["XPos"][2], cut_offsets["XNeg"][2])
            # and the authored offsets read back on the +Y face: +1 in along
            # the datum's X (= post +X), +1/2 in along its Y (= post -Z)
            self.assertEqual(cut_offsets["YPos"][0], 1.0)
            self.assertEqual(cut_offsets["YPos"][2], 48 - 0.5)

    # --- remove, reuse, refusals ----------------------------------------

    def test_remove_returns_the_bare_sticks(self):
        from freecad.bentwizard import datums, joint_handle
        from freecad.bentwizard.apply import joint_datums, remove_joint
        applied = self.apply()
        vs = applied.varset
        host, mate = joint_datums(vs)
        vs_name = vs.Name
        n_before = len(self.doc.Objects)
        remove_joint(vs)
        self.assertEqual(self.volume(self.post), 8 * 8 * 96)
        self.assertEqual(self.volume(self.girt), 6 * 8 * 72)
        self.assertFalse(datums.is_paired(host))
        self.assertFalse(datums.is_paired(mate))
        self.assertIsNone(self.doc.getObject(vs_name))
        self.assertEqual([o.Label for o in self.doc.Objects
                          if "HousedMT" in o.Label or joint_handle.is_handle(o)], [])
        self.assertLess(len(self.doc.Objects), n_before)
        self.assertEqual(self.lint(), [])
        # the datums are reusable
        self.apply(serial="002")
        self.assertEqual(self.volume(self.post), round(8 * 8 * 96 - HOUSING - MORTISE, 6))

    def test_two_joints_on_one_post(self):
        from freecad.bentwizard.timber import new_timber
        girt2, _ = new_timber(self.doc, "T-Girt-002", "6 in", "8 in", "6 ft")
        self.apply(serial="001", station="30 in")
        self.apply(serial="002", station="70 in", girt=girt2)
        self.assertEqual(self.volume(self.post), round(8 * 8 * 96 - 2 * (HOUSING + MORTISE), 6))
        labels = {o.Label for o in self.doc.Objects}
        self.assertTrue({"J-HousedMT-001", "J-HousedMT-002", "Mortise.HousedMT.002",
                         "Tenon.HousedMT.002"} <= labels)
        self.assertEqual(self.lint(), [])

    def test_existing_datum_target(self):
        from freecad.bentwizard import datums
        from freecad.bentwizard.apply import apply_joint, joint_datums
        d = datums.add_datum(self.post, "XNeg", "20 in")
        vs = apply_joint(self.doc, self.spec, "001", {
            self.spec.host_role: {"body": self.post, "datum": d},
            self.spec.mate_role: {"body": self.girt, "face": "EndA"}}).varset
        self.assertIs(joint_datums(vs)[0], d)
        self.assertEqual(self.volume(self.post), round(8 * 8 * 96 - HOUSING - MORTISE, 6))

    def test_butt_pairs_without_components(self):
        from freecad.bentwizard import assemble, measure
        from freecad.bentwizard.apply import joint_components
        vs = self.apply(spec=self.butt).varset
        self.assertEqual(vs.Label, "J-Butt-001")
        self.assertEqual(joint_components(vs), [])
        self.assertEqual(self.volume(self.post), 8 * 8 * 96)
        assemble.assimilate_joint(self.doc, vs)
        self.assertLess(assemble.joint_misfit(vs)[0], 1e-6)
        self.assertLess(self.post.Shape.common(self.girt.Shape).Volume, 1e-6)
        self.assertEqual(measure.end_projection(self.girt), (0.0, 0.0))
        self.assertEqual(self.lint(), [])

    def test_refusals(self):
        from freecad.bentwizard.template import JointError
        self.apply()
        with self.assertRaises(JointError):
            self.apply(serial="001")               # serial taken
        with self.assertRaises(JointError):
            self.apply(serial="002")               # girt end B already paired
        with self.assertRaises(JointError):
            self.apply(serial="003", girt=self.post)   # same timber
        with self.assertRaises(JointError):
            self.apply(serial="004", end="EndA", values={"Nope": 1})


if __name__ == "__main__":
    unittest.main()
