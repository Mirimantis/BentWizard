"""The toolbar icons: one for every registered command and for the
workbench, each a well-formed 64x64 SVG, and the committed files exactly
what scripts/build_icons.py draws. Pure Python: runs under any
interpreter."""

import importlib.util
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ICONS = REPO_ROOT / "freecad" / "bentwizard" / "resources" / "icons"
COMMANDS = REPO_ROOT / "freecad" / "bentwizard" / "commands.py"


def _build_icons():
    spec = importlib.util.spec_from_file_location(
        "build_icons", REPO_ROOT / "scripts" / "build_icons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _registered_commands():
    """The command IDs `register()` adds, read from its source."""
    src = COMMANDS.read_text(encoding="utf-8")
    body = src[src.index("def register():"):]
    return sorted(set(re.findall(r'\("(BentWizard_\w+)", \w+Command\(\)\)', body)))


class IconsTest(unittest.TestCase):
    def test_every_command_has_an_icon(self):
        commands = _registered_commands()
        self.assertGreaterEqual(len(commands), 11)
        for name in commands + ["BentWizard"]:
            with self.subTest(name):
                self.assertTrue((ICONS / f"{name}.svg").is_file(), f"{name}.svg missing")

    def test_icons_are_64_square_svg(self):
        files = sorted(ICONS.glob("*.svg"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(path.name):
                root = ET.parse(path).getroot()
                self.assertTrue(root.tag.endswith("svg"))
                self.assertEqual(root.get("viewBox"), "0 0 64 64")

    def test_committed_icons_match_the_generator(self):
        build = _build_icons()
        with tempfile.TemporaryDirectory() as td:
            build.OUT = Path(td)
            build.main()
            for made in sorted(Path(td).glob("*.svg")):
                with self.subTest(made.name):
                    committed = ICONS / made.name
                    self.assertTrue(committed.is_file(), f"{made.name} not committed")
                    self.assertEqual(committed.read_text(encoding="utf-8"),
                                     made.read_text(encoding="utf-8"),
                                     f"{made.name}: rerun scripts/build_icons.py")


if __name__ == "__main__":
    sys.exit(unittest.main())
