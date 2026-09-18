# Spike: Variant Links + Booleans as the joint application mechanism

**Purpose.** Decide whether joints can be applied with FreeCAD's native instancing (App::Link with LinkCopyOnChange) plus a boolean cut, replacing the hand-rolled rebuild engine in `apply_joint.py`. No workbench code is written during this spike — it is a Phase 0-style manual session, and its output is a go/no-go with evidence.

**Ground rule.** Everything here is done by hand in the GUI, in a scratch document, with a macro recording. If a step cannot be done manually, it cannot be automated either, and that is a finding.

**Time.** Plan for one session. Stop early and report if Part A fails — the rest depends on it.

---

## Part A — Build a cutter template (the negative)

The template is the wood that gets *removed*, not the joint that remains.

1. New document `Spike_Cutter.FCStd`. Start a macro recording.
2. Create a Body, label it **Cutter_MT_Mortise**.
3. Add the parameters as **custom properties on the Body itself** (right-click the Body in the tree → Add property; or the property view's context menu). Group `Joint`, type Length, with tooltips:
   - `MortiseThickness` = 2 in
   - `MortiseWidth` = 6 in
   - `MortiseDepth` = 4.25 in
   - `HousingDepth` = 0.5 in
   - `HousingWidth` = 8 in
   - `HousingHeight` = 8 in
   - `SetbackFace1` = 2 in
   - `SetbackFace2` = 1 in

   (UpperCamelCase per FreeCAD convention — the Property View inserts display spaces. Note at Checkpoint A how a trailing digit renders: "Setback Face 1" or "Setback Face1".)
4. Model the removal solid: a pad for the housing block (Housing_Width × Housing_Height × Housing_Depth) and a second pad for the mortise prism, positioned from the body origin by the setbacks. Sketches on origin planes, all dimensions bound to the body's own properties by expression (`MortiseThickness`, unqualified — properties on the same object are referenced by bare name).
   - The body origin is the **landing frame**: the point that will be positioned on the target timber. Keep every dimension measured from it.
5. Verify parametric behavior: change `MortiseThickness` on the Body → the prism resizes.
6. **Checkpoint A.** Do body-level custom properties drive sketches cleanly? Any oddity in the expression editor referencing them? Record the answer.

---

## Part B — Variant Links into a target timber

7. New document `Spike_Target.FCStd`, in the same FreeCAD session. Build a plain 8×8×96 timber Body per workflow §4.1 (`TimberDims_Spike` VarSet, corner on origin).
8. With both documents open: select the Cutter body in `Spike_Cutter`, then in `Spike_Target` use **Link → Make link** with **LinkCopyOnChange = Enabled** (property on the created Link; set it before overriding anything). Some builds expose this as "Make variant link" in the Link dropdown.
9. On the Link object, locate the exposed `Joint` group properties. Change `MortiseThickness` to 1.5 in on the link.
10. **Checkpoint B1.** Did the link's geometry update, and did the original template stay at 2 in? If the template changed, LinkCopyOnChange is not engaged — stop and report.
11. Make a **second** link from the same template into the same document, leave it at defaults, place it elsewhere.
12. **Checkpoint B2.** Two links, different parameter values, one template. Confirm independence in both directions (edit each; edit the template and see what propagates).
13. Position link 1 by its Placement to sit at the joint location on the timber (mortise face against the reference face, at a chosen height). Position by expression where possible.

---

## Part C — The boolean bridge (the decisive part)

Try all three, in this order, and record behavior for each. Undo between attempts.

14. **C1 — PartDesign Boolean.** Activate the timber Body → PartDesign → Boolean → Subtractive, selecting the Link. Does it accept a Link as an operand at all?
15. **C2 — SubShapeBinder.** Activate the timber Body → Part Design → create a **SubShapeBinder** referencing the Link (check its `Relative`/`BindMode` settings), then PartDesign Boolean subtractive against the binder.
16. **C3 — Part::Cut.** Outside PartDesign: Part workbench → Boolean → Cut, timber Body minus Link. Note that the result is a new `Cut` object and the Body becomes its child — the "timber" is now the Cut, which affects everything downstream.

For each that works, record:
- Does editing the link's parameters update the cut timber on recompute?
- Does moving the link's Placement update the cut?
- Does the timber's own Body remain independently editable (open a sketch, change a dimension)?
- What is the resulting top-level object type, and what would a cut list / TechDraw / Assembly reference?

17. **Checkpoint C.** Pick the winner and say why. If none work acceptably, that is the spike's answer and the rebuild engine stays.

---

## Part D — Downstream compatibility

Using the winning bridge:

18. **TechDraw.** New page, projection group of the cut timber, hidden lines on. Dimension the mortise position from the reference face and the stick end. Change a link parameter → do the view and dimensions update, or do dimensions detach?
19. **Assembly.** Create an assembly, insert the cut timber and a second timber, one Fixed joint between tree-selected datums. Does the cut timber behave as a normal component?
20. **Graceful degradation.** Save, close, reopen. Then test the Tier 1 promise: does the document open and recompute with no workbench installed (it should — everything here is stock FreeCAD)? Confirm the link's exposed properties are visible and editable in the property panel.
21. **Round trip.** Copy the saved files to another folder, reopen, confirm links resolve (note whether they depend on relative paths or the template document being open — a real deployment question for the library).

---

## Part E — Scale

22. Duplicate the cut timber (with its link) ten times. Time a full document recompute (`Std_Refresh`, or note the delay after a parameter change).
23. Extrapolate: LinkCopyOnChange materializes an internal copy per variant. Estimate document size and recompute time for ~150 joints (a small frame). Record the file size on disk with 10 links.
24. **Checkpoint E.** Is recompute time acceptable at frame scale, or does it degrade non-linearly?

---

## Report format

For each checkpoint: what happened, whether it passed, and any friction worth a findings entry. Then a one-paragraph recommendation. Upload `Spike_Cutter.FCStd`, `Spike_Target.FCStd`, and the macro; the files will be inspected against the same placement-chain-resolution method used throughout Phase 0.

## Decision criteria

**Go** if: a boolean bridge works, parameters propagate on recompute, the timber stays natively editable, TechDraw and Assembly behave, and recompute at 150 joints is tolerable.

**Partial go** (worth a hybrid) if: the mechanism works but one downstream consumer misbehaves — e.g. links are fine for modeling but the cut object type breaks the cut-list walker. Note which layer needs adapting.

**No go** if: no bridge preserves both the cut and native editability, or scale degrades badly. In that case the rebuild engine stays, and the spike still pays for itself by ruling out a rewrite.
