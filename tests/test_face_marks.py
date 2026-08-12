"""The face/end mark placement — the convention, not the scene graph.

`view_face_marks` keeps its `pivy.coin` imports inside the drawing
functions precisely so this arithmetic is reachable without a GUI. What
is worth testing is the convention: a numeral on the wrong face is worse
than no numeral at all, because it is believed.

The authority is `apply_joint.FACES`, the same table Apply Timber Joint
places against, so these assertions tie the label to the thing it
claims to describe rather than to a second copy of the convention.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402, F401 — this repo's code must win the import

try:
    import FreeCAD  # noqa: F401
    _repo_path.graft()
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False

WIDTH, DEPTH, LENGTH = 152.4, 203.2, 2438.4      # 6 x 8 x 96 in


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class FaceMarkPlacement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.view_face_marks import mark_positions
        cls.marks = {text: position
                     for text, position, _color in
                     mark_positions(WIDTH, DEPTH, LENGTH)}

    def test_every_face_and_end_is_labelled_once(self):
        self.assertEqual(sorted(self.marks), ["1", "2", "3", "4", "A", "B"])

    def test_reference_faces_are_the_ones_at_zero(self):
        """Faces 1 and 2 are the REFERENCE faces — the XZ face at y=0 and
        the YZ face at x=0 — and 3/4 are opposite them. Inverting this
        pair is the error the whole test exists for."""
        self.assertLess(self.marks["1"][1], 0, "face 1 is not outside y = 0")
        self.assertLess(self.marks["2"][0], 0, "face 2 is not outside x = 0")
        self.assertGreater(self.marks["3"][1], DEPTH,
                           "face 3 is not outside y = Depth")
        self.assertGreater(self.marks["4"][0], WIDTH,
                           "face 4 is not outside x = Width")

    def test_faces_sit_centred_on_the_face_they_name(self):
        for face in ("1", "3"):          # perpendicular to Y, span Width
            self.assertAlmostEqual(self.marks[face][0], WIDTH / 2, places=9)
        for face in ("2", "4"):          # perpendicular to X, span Depth
            self.assertAlmostEqual(self.marks[face][1], DEPTH / 2, places=9)
        for face in "1234":
            self.assertAlmostEqual(self.marks[face][2], LENGTH / 2, places=9,
                                   msg=f"face {face} is not at mid-stick")

    def test_ends_are_beyond_the_stick_at_the_section_centre(self):
        for end in ("A", "B"):
            self.assertAlmostEqual(self.marks[end][0], WIDTH / 2, places=9)
            self.assertAlmostEqual(self.marks[end][1], DEPTH / 2, places=9)
        self.assertLess(self.marks["A"][2], 0, "end A is not beyond z = 0")
        self.assertGreater(self.marks["B"][2], LENGTH,
                           "end B is not beyond z = Length")

    def test_agrees_with_the_face_table_apply_joint_places_against(self):
        """FACES[n]['ddim'] is the landing timber's dimension along the
        joint normal. A face perpendicular to Y is normal-along-Y, so its
        ddim is Depth; perpendicular to X gives Width. If a label moved
        to a different axis than the table expects, the two have drifted.
        """
        from freecad.bentwizard.apply_joint import FACES
        normal_axis = {"1": 1, "2": 0, "3": 1, "4": 0}   # y, x, y, x
        expected_ddim = {1: "Depth", 0: "Width"}
        for face, axis in normal_axis.items():
            self.assertEqual(
                FACES[int(face)]["ddim"], expected_ddim[axis],
                f"face {face}: the mark is offset along "
                f"{'xyz'[axis]} but FACES says its ddim is "
                f"{FACES[int(face)]['ddim']}")

    def test_stand_off_tracks_the_section_not_the_length(self):
        """A 20 ft beam must keep its end labels at its ends. Scaling the
        along-axis stand-off by Length put them two feet into space."""
        from freecad.bentwizard.view_face_marks import mark_positions
        short = dict((t, p) for t, p, _ in
                     mark_positions(WIDTH, DEPTH, 1000.0))
        long = dict((t, p) for t, p, _ in
                    mark_positions(WIDTH, DEPTH, 100000.0))
        self.assertAlmostEqual(short["A"][2], long["A"][2], places=9)
        self.assertAlmostEqual(short["B"][2] - 1000.0,
                               long["B"][2] - 100000.0, places=9)


if __name__ == "__main__":
    unittest.main()
