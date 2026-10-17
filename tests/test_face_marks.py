"""The face/end marks' layout and reading a face off a click — the
conventions, not the scene graph.

`view_face_marks` keeps its `pivy.coin` imports inside the drawing
functions so its arithmetic is reachable without a GUI. A name on the
wrong face is worse than no name at all, because it is believed, so the
lettering is tied to the face table the datums are placed against — and
so is `facetable.place_at`, which turns a click on the model into the
face a datum goes on.
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

from freecad.bentwizard import facetable  # noqa: E402

WX, WY, LZ = 152.4, 203.2, 2438.4      # 6 x 8 x 96 in


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class FaceMarkLettering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.view_face_marks import lettering
        cls.marks = lettering(WX, WY, LZ)
        cls.names = {m.place: m for m in cls.marks
                     if m.text == facetable.display(m.place)}

    def test_every_face_named_once_and_ends_lettered(self):
        self.assertEqual(sorted(m.text for m in self.names.values()),
                         ["+X", "+Y", "-X", "-Y"])
        ends = sorted((m.place, m.text) for m in self.marks if m.text in "AB")
        # A and B on the end grain, and near each end of every side face
        self.assertIn(("EndA", "A"), ends)
        self.assertIn(("EndB", "B"), ends)
        for face in facetable.FACES:
            self.assertIn((face, "A"), ends)
            self.assertIn((face, "B"), ends)

    def test_each_lies_on_its_own_face_facing_out(self):
        half = {"XPos": WX / 2, "XNeg": WX / 2, "YPos": WY / 2, "YNeg": WY / 2}
        for mark in self.marks:
            row = facetable.FACE_TABLE[mark.place]
            self.assertEqual(tuple(mark.normal), row.outward, mark)
            depth = _dot(mark.origin, row.outward)
            if facetable.is_end(mark.place):
                plane = 0.0 if mark.place == "EndA" else LZ
                depth = mark.origin[2] - plane
                self.assertGreater(depth * row.outward[2], 0, mark)   # proud
                self.assertLess(abs(depth), 2.0, mark)                # not floating
            else:
                proud = depth - half[mark.place]
                self.assertGreater(proud, 0, mark)
                self.assertLess(proud, 2.0, mark)
                self.assertGreater(mark.origin[2], 0, mark)
                self.assertLess(mark.origin[2], LZ, mark)

    def test_lettering_runs_in_the_face(self):
        for mark in self.marks:
            self.assertAlmostEqual(_dot(mark.baseline, mark.normal), 0, places=12)
            self.assertAlmostEqual(_dot(mark.baseline, mark.baseline), 1, places=12)
            if not facetable.is_end(mark.place):
                self.assertEqual(tuple(mark.baseline), (0.0, 0.0, 1.0), mark)

    def test_letters_fit_their_face(self):
        for place, mark in self.names.items():
            width = WY if place.startswith("X") else WX
            # "+X" is about 1.3 letter heights wide: it must fit across
            # the face too, where `view_text.level` turns it on a post
            self.assertLess(mark.height * 1.4, width, place)
            self.assertAlmostEqual(_dot(mark.origin, (0, 0, 1)), LZ / 2, places=9)

    def test_size_tracks_the_section_not_the_length(self):
        from freecad.bentwizard.view_face_marks import lettering
        short = {(m.place, m.text): m for m in lettering(WX, WY, 1000.0)}
        long = {(m.place, m.text): m for m in lettering(WX, WY, 100000.0)}
        for key, mark in short.items():
            self.assertAlmostEqual(mark.height, long[key].height, places=9)
        # end B's letter sits on end B however long the timber
        self.assertAlmostEqual(short[("EndB", "B")].origin[2] - 1000.0,
                               long[("EndB", "B")].origin[2] - 100000.0, places=9)


class PlaceAtPoint(unittest.TestCase):
    """A point on the timber, in its own coordinates, gives the face and
    station a click there means — pure, from the face table's section."""

    def at(self, x, y, z):
        return facetable.place_at(WX, WY, LZ, (x, y, z))

    def test_each_side_face_with_its_station(self):
        self.assertEqual(self.at(WX / 2, 10.0, 900.0), ("XPos", 900.0))
        self.assertEqual(self.at(-WX / 2, -30.0, 300.0), ("XNeg", 300.0))
        self.assertEqual(self.at(20.0, WY / 2, 1200.0), ("YPos", 1200.0))
        self.assertEqual(self.at(-50.0, -WY / 2, 5.0), ("YNeg", 5.0))

    def test_agrees_with_the_face_table(self):
        for face in facetable.FACES:
            ox, oy, _ = facetable.FACE_TABLE[face].outward
            point = (ox * WX / 2, oy * WY / 2, 1000.0)
            self.assertEqual(self.at(*point), (face, 1000.0), face)

    def test_ends_have_no_station(self):
        self.assertEqual(self.at(10.0, 10.0, 0.0), ("EndA", None))
        self.assertEqual(self.at(-10.0, 40.0, LZ), ("EndB", None))

    def test_past_an_end_is_that_end(self):
        # a tenon growing out of end B, an adder at end A
        self.assertEqual(self.at(WX / 4, 0.0, LZ + 80.0), ("EndB", None))
        self.assertEqual(self.at(0.0, WY / 4, -50.0), ("EndA", None))

    def test_joinery_is_no_face(self):
        # a housing floor parallel to +Y but set into the section, and a
        # mortise cheek inside it
        self.assertIsNone(self.at(0.0, WY / 2 - 12.7, 1200.0))
        self.assertIsNone(self.at(19.05, WY / 2 - 40.0, 1200.0))

    def test_float_noise_still_on_the_face(self):
        self.assertEqual(self.at(WX / 2 + 0.0003, 0.0, 900.0), ("XPos", 900.0))
        self.assertEqual(self.at(WX / 2 - 0.0003, 0.0, 900.0), ("XPos", 900.0))

    def test_an_arris_takes_the_nearer_face(self):
        self.assertEqual(self.at(WX / 2 - 0.1, WY / 2, 900.0)[0], "YPos")
        self.assertEqual(self.at(WX / 2, WY / 2 - 0.1, 900.0)[0], "XPos")

    def test_off_the_section_is_not_this_timber(self):
        self.assertIsNone(self.at(WX, 0.0, 900.0))


if __name__ == "__main__":
    unittest.main()
