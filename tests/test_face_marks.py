"""The face/end mark placement — the convention, not the scene graph.

`view_face_marks` keeps its `pivy.coin` imports inside the drawing
functions so this arithmetic is reachable without a GUI. A numeral on
the wrong face is worse than no numeral at all, because it is believed,
so the marks are tied to the face table the datums are placed against.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402, F401

try:
    import FreeCAD  # noqa: F401
    _repo_path.graft()
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False

WX, WY, LZ = 152.4, 203.2, 2438.4      # 6 x 8 x 96 in


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class FaceMarkPlacement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.view_face_marks import mark_positions
        cls.marks = {text: position
                     for text, position, _color in mark_positions(WX, WY, LZ)}

    def test_every_face_and_end_is_labelled_once(self):
        self.assertEqual(sorted(self.marks), ["+X", "+Y", "-X", "-Y", "A", "B"])

    def test_faces_stand_off_their_own_face(self):
        self.assertGreater(self.marks["+X"][0], WX / 2)
        self.assertLess(self.marks["-X"][0], -WX / 2)
        self.assertGreater(self.marks["+Y"][1], WY / 2)
        self.assertLess(self.marks["-Y"][1], -WY / 2)
        for face in ("+X", "-X"):
            self.assertAlmostEqual(self.marks[face][1], 0, places=9)
        for face in ("+Y", "-Y"):
            self.assertAlmostEqual(self.marks[face][0], 0, places=9)
        for face in ("+X", "-X", "+Y", "-Y"):
            self.assertAlmostEqual(self.marks[face][2], LZ / 2, places=9)

    def test_ends_are_beyond_the_stick_on_the_axis(self):
        for end in ("A", "B"):
            self.assertAlmostEqual(self.marks[end][0], 0, places=9)
            self.assertAlmostEqual(self.marks[end][1], 0, places=9)
        self.assertLess(self.marks["A"][2], 0)
        self.assertGreater(self.marks["B"][2], LZ)

    def test_agrees_with_the_face_table(self):
        from freecad.bentwizard import facetable
        for face in facetable.FACES:
            row = facetable.FACE_TABLE[face]
            pos = self.marks[row.display]
            direction = tuple(0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
                              for v in pos[:2]) + (0,)
            self.assertEqual(direction, row.outward, face)

    def test_stand_off_tracks_the_section_not_the_length(self):
        from freecad.bentwizard.view_face_marks import mark_positions
        short = {t: p for t, p, _ in mark_positions(WX, WY, 1000.0)}
        long = {t: p for t, p, _ in mark_positions(WX, WY, 100000.0)}
        self.assertAlmostEqual(short["A"][2], long["A"][2], places=9)
        self.assertAlmostEqual(short["B"][2] - 1000.0, long["B"][2] - 100000.0, places=9)


if __name__ == "__main__":
    unittest.main()
