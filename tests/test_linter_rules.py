"""Rule-level regression tests against synthetic Document.xml.

Covers behavior no phase-0 fixture exercises — currently the junction-
point pattern decided at Phase 1 start: a joint VarSet property like
Housing_Width is bound to the mating timber's Dims and legitimately
spans ~100% of the receiving face. That must NOT trip the 75% profile
severing rule (housing severing exposure is depth, which has its own
50% rule).
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from freecad.bentwizard.fcstd import FcstdDocument   # noqa: E402
from freecad.bentwizard.linter import lint_document  # noqa: E402


def _esc(expression):
    return expression.replace("<", "&lt;").replace(">", "&gt;")


def synthetic_doc(joint_props, sketch_exprs, pocket_length_expr):
    """A minimal one-body document: section sketch + pad + one pocket
    whose profile sketch carries `sketch_exprs` (constraint expressions),
    with `joint_props` on the joint VarSet (name -> value in mm)."""
    sketch_exprs = [_esc(e) for e in sketch_exprs]
    pocket_length_expr = _esc(pocket_length_expr)
    props = "\n".join(
        f'<Property name="{n}" type="App::PropertyLength" group="Joint" doc="d">'
        f'<Float value="{v}" /></Property>'
        for n, v in joint_props.items())
    constraints = "\n".join(
        '<Constrain Name="" Type="7" Value="0" IsDriving="1" First="0" '
        'FirstPos="1" Second="-1" SecondPos="1" Third="-2000" ThirdPos="0" />'
        for _ in sketch_exprs)
    exprs = "\n".join(
        f'<Expression path="Constraints[{i}]" expression="{e}" />'
        for i, e in enumerate(sketch_exprs))
    xml = f"""<?xml version="1.0"?>
<Document SchemaVersion="4">
 <Objects Count="6">
  <Object type="App::VarSet" name="Dims" />
  <Object type="App::VarSet" name="Joint" />
  <Object type="PartDesign::Body" name="Body" />
  <Object type="Sketcher::SketchObject" name="Section" />
  <Object type="PartDesign::Pad" name="Pad" />
  <Object type="Sketcher::SketchObject" name="CutSketch" />
  <Object type="PartDesign::Pocket" name="Pocket" />
 </Objects>
 <ObjectData Count="6">
  <Object name="Dims"><Properties Count="4">
   <Property name="Label" type="App::PropertyString"><String value="TimberDims_P0-1" /></Property>
   <Property name="Width" type="App::PropertyLength" group="Dims" doc="d"><Float value="203.2" /></Property>
   <Property name="Depth" type="App::PropertyLength" group="Dims" doc="d"><Float value="203.2" /></Property>
   <Property name="Length" type="App::PropertyLength" group="Dims" doc="d"><Float value="2438.4" /></Property>
  </Properties></Object>
  <Object name="Joint"><Properties Count="2">
   <Property name="Label" type="App::PropertyString"><String value="Joint_MT_0a" /></Property>
   {props}
  </Properties></Object>
  <Object name="Body"><Properties Count="2">
   <Property name="Label" type="App::PropertyString"><String value="P0-1" /></Property>
   <Property name="Group" type="App::PropertyLinkList"><LinkList count="4">
    <Link value="Section" /><Link value="Pad" />
    <Link value="CutSketch" /><Link value="Pocket" />
   </LinkList></Property>
  </Properties></Object>
  <Object name="Section"><Properties Count="1">
   <Property name="Label" type="App::PropertyString"><String value="P0-1_SectionSketch" /></Property>
  </Properties></Object>
  <Object name="Pad"><Properties Count="2">
   <Property name="Label" type="App::PropertyString"><String value="P0-1_Stick" /></Property>
   <Property name="ExpressionEngine" type="App::PropertyExpressionEngine">
    <ExpressionEngine count="1">
     <Expression path="Length" expression="&lt;&lt;TimberDims_P0-1&gt;&gt;.Length" />
    </ExpressionEngine></Property>
  </Properties></Object>
  <Object name="CutSketch"><Properties Count="3">
   <Property name="Label" type="App::PropertyString"><String value="P0-1_HousingSketch_MT_0a" /></Property>
   <Property name="Constraints" type="Sketcher::PropertyConstraintList">
    <ConstraintList count="{len(sketch_exprs)}">{constraints}</ConstraintList></Property>
   <Property name="ExpressionEngine" type="App::PropertyExpressionEngine">
    <ExpressionEngine count="{len(sketch_exprs)}">{exprs}</ExpressionEngine></Property>
  </Properties></Object>
  <Object name="Pocket"><Properties Count="3">
   <Property name="Label" type="App::PropertyString"><String value="P0-1_Housing_MT_0a" /></Property>
   <Property name="Profile" type="App::PropertyLinkSub"><LinkSub value="CutSketch" count="0" /></Property>
   <Property name="ExpressionEngine" type="App::PropertyExpressionEngine">
    <ExpressionEngine count="1">
     <Expression path="Length" expression="{pocket_length_expr}" />
    </ExpressionEngine></Property>
  </Properties></Object>
 </ObjectData>
</Document>"""
    return FcstdDocument.from_xml(xml.encode("utf-8"))


class HousingJunctionPattern(unittest.TestCase):
    """Housing_Width bound to the mating timber's Dims spans ~100% of the
    receiving face by design — depth is the severing dimension."""

    def lint(self, joint_props, sketch_exprs, pocket_length):
        doc = synthetic_doc(joint_props, sketch_exprs, pocket_length)
        return lint_document(doc)

    def test_full_width_housing_is_not_a_severing_violation(self):
        findings = self.lint(
            {"Housing_Width": 203.2, "Housing_Depth": 12.7},
            ["<<Joint_MT_0a>>.Housing_Width"],
            "<<Joint_MT_0a>>.Housing_Depth")
        severing = [f for f in findings if f.rule == "severing-limit"]
        caution = [f for f in findings if f.rule == "caution-threshold"]
        self.assertEqual(severing, [])
        self.assertEqual(caution, [])

    def test_housing_depth_still_checked(self):
        findings = self.lint(
            {"Housing_Width": 203.2, "Housing_Depth": 152.4},  # 75% deep
            ["<<Joint_MT_0a>>.Housing_Width"],
            "<<Joint_MT_0a>>.Housing_Depth")
        severing = [f for f in findings if f.rule == "severing-limit"]
        self.assertEqual(len(severing), 1)
        self.assertIn("Housing_Depth", severing[0].message)

    def test_mortise_width_still_checked(self):
        findings = self.lint(
            {"Tenon_Width": 177.8, "Mortise_Depth": 101.6},  # 87.5% wide
            ["<<Joint_MT_0a>>.Tenon_Width"],
            "<<Joint_MT_0a>>.Mortise_Depth")
        severing = [f for f in findings if f.rule == "severing-limit"]
        self.assertEqual(len(severing), 1)
        self.assertIn("Tenon_Width", severing[0].message)


if __name__ == "__main__":
    unittest.main()
