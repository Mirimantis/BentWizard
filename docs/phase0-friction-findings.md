# Phase 0 — Friction Findings & Phase 1 Automation Spec

Captured after Sessions 1–3 (timber template, beam tenon, post mortise+housing).
Each finding notes the friction, its *type*, and the automation response it implies.
Friction types: **TYPO** (exact string required), **RITUAL** (non-obvious required sequence),
**GUESS** (direction/result checked by eye), **HUNT** (locating UI), **VERIFY** (hard to confirm correctness).

---

## High-friction items (caused hunting and/or undos)

### 1. Expression / f(x) entry — TYPO
Every parametric dimension required opening the expression editor and typing
`<<VarSet>>.Property` exactly, for 12+ constraints across the sessions. Slow and typo-prone;
a single wrong token silently breaks the binding.
**Automation response:** the Apply-Joint tool writes all expressions programmatically. The user
never types an expression string. Parameters are entered as plain numbers in one dialog; the
tool binds them to the shared VarSet.

### 2. Duplicate-with-VarSet trick — RITUAL
Duplicating a body *and* its VarSet together (Ctrl-select both) so expressions remap to the
copy rather than pointing back at the original. Easy to forget the second selection; forgetting
it produces a body that secretly still depends on the original's VarSet.
**Automation response:** "New timber from template" command duplicates body + VarSet as an atomic
unit and verifies the remap. The ritual becomes one button with no way to do the half-version.

### 3. Datum plane attachment — GUESS + HUNT
Creating BearingPlane_MT1, choosing the reference plane, and getting the offset *direction*
(sign) correct. Offset direction is checked by eye and sometimes wrong on first try.
**Automation response:** tool creates reference/bearing datums itself with the correct offset
expression and sign baked in, derived from the named reference faces. No manual datum creation
for standard joints.

### 4. Pocket/Pad direction (Reversed checkbox) — GUESS
Whether a pad/pocket grows the intended way is guessed, cut, and visually checked; sometimes
the checkbox has to be toggled and re-cut. Affected the tenon pad, housing pocket, mortise pocket.
**Automation response:** tool sets Reversed correctly from joint definition + reference-face
orientation. Direction is computed, never guessed.

---

## Secondary friction (tripped up but lower cost)

### 5. Finding workbench buttons / icons — HUNT
Locating the right icon (Create datum plane, Create variable set, Duplicate) across toolbars and
menus, especially when new to FreeCAD 1.1.
**Automation response:** all timber-framing actions live on one dedicated toolbar/menu, named in
domain terms ("Apply Tenon", "New Timber"), not CAD-primitive terms.

### 6. Renaming labels in the tree — HUNT / tedious
Manually renaming Body→Post, VarSet→PostDims, Pad→Tenon_MT1, etc. after each creation step.
**Automation response:** tool names every object it creates using the established convention
(`FeatureType_JointID`, timber names from a numbering scheme) at creation time.

### 7. Mated parts not aligned intuitively in 3D view — VERIFY  ⚠ key finding
Both timbers padded +Z from their own XY plane, so both stand vertical, with the beam's tenon
pointing down at its origin end. In reality the beam is horizontal, framing into the post side.
Verifying the joint by eye meant mentally rotating one part 90° and bridging a 24" gap between
them. Geometry is correct, but **a wrong joint would be hard to see** — verification risk, not a
modeling error.
**Automation responses (two):**
  (a) *Phase 0 convention* — when modeling a mated pair for inspection, position the parts in their
      as-assembled relationship so tenon visibly enters mortise, even though final placement is an
      Assembly-phase concern.
  (b) *Phase 1 feature (NEW)* — a "Preview Mated Joint" capability: temporarily display both halves
      engaged, independent of how the underlying bodies are oriented in their own documents, so the
      user can confirm fit at a glance. Added to roadmap.

### 8. Coincident origins make 3D-view plane selection ambiguous — HUNT / VERIFY  ⚠ Session 4
When creating SeatPlane_DT1 (a datum inside the Girt), selecting the Girt's XY plane in the 3D view
instead grabbed the Joist's `XY-plane001`, because the Joist was not yet placed and both bodies'
origins sat coincident at global zero. FreeCAD correctly refused: a datum in one body may not attach
to another body's origin geometry (would break body independence). The refusal is desirable — it
enforces our governing rule for us.
**Workarounds used:** select reference geometry from the model tree (labels unambiguous; `001` suffix
distinguishes the duplicate's features) rather than the 3D view; optionally hide the other body
(spacebar) while working.
**Automation response:** the tool always references a body's own reference planes *internally* (by
object reference), never by 3D pick — so this ambiguity cannot occur once automated. Also a general
user-guidance note: pick origin/reference features from the tree, not the viewport.

---

## Cross-cutting principle confirmed
The four high-friction items are all TYPO / RITUAL / GUESS — exactly the categories a tool removes
best, because they are error-prone rather than merely slow. This validates the build order:
Phase 1's first job is the Apply-Joint tool that eliminates manual expression entry, the duplicate
ritual, datum creation, and direction guessing — replacing them with computed, correct-by-construction
native objects.

### 9. Three-axis joints need a face-relative sketch frame, not the body's end plane — ⚠ Session 4 (dovetail)
Because every timber is padded along local Z, a body's local XY plane is parallel to its END. This is
correct for end-grain joints (mortise/tenon: reach is the only axis that matters) but WRONG for side-
landing joints like a joist dovetail, which are inherently three-axis: flare (one direction), reach-into-
timber (a second), drop-in (a third). The dovetail housing footprint must be sketched on a plane parallel
to the relevant LONG face (here the top), not the end plane. The user correctly flagged this before cutting.
**Automation responses:**
  (a) The Apply-Joint tool must select the sketch/datum plane from the *target face* the joint lands on
      (and the timber's reference faces), never assume the body's local XY/end plane. Joint definitions
      should be expressed relative to a named landing face + reference faces, so the tool derives the
      correct sketch plane and the correct cut directions per joint type.
  (b) Joint definitions carry an intended drop-in / assembly direction; the tool orients the mating
      placement with a single clean rotation where possible and keeps vertical members vertical.
  (c) Confirms finding #7a: model mated pairs in as-assembled orientation so sketch frames stay intuitive.

### 10. Offset datum plane shifts the sketch coordinate origin — GUESS/VERIFY ⚠ Session 4
Sketching on an offset datum plane meant a positioning parameter (JointSeatZ) did not map 1:1 to the
girt's length axis as expected; the housing initially landed ~6" off, floating past the timber end.
Resolved empirically by adjusting the value until it seated. The position parameter must be interpreted
in the datum's shifted frame, not the body frame.
**Concrete mechanism (confirmed):** the datum's resolved global placement carried an +8" (GirtDims.Depth)
translation along global Z plus a 90° frame rotation, so the housing's sketch-local Z (~24) corresponds
to global Z (~32). Local sketch coordinates are NOT global coordinates once an offset/rotated datum is in
play. This is severe enough that it also misled Claude's own file analysis (see verification lesson).
**Automation response:** the tool computes feature positions directly in the body's own coordinate
system and sets datum offsets accordingly, so a position parameter always means the same thing
regardless of intermediate datums.
**Verification-method lesson (Claude):** always evaluate fit against *resolved global placements*
(DatumPlane.Placement, Sketch.Placement quaternions), never sketch-local coordinates; and when the
user's viewport contradicts the analysis, the viewport wins until the analysis is re-derived from
resolved frames. Reading rotation requires parsing the placement quaternion (Q0–Q3), not axis/angle
attributes, which may be absent.

### 11. Hand-editing did NOT break parametric bindings — ✅ positive finding, Session 4
When the user adjusted dimensions to make the housing fit, they edited the *expressions / VarSet*, not
hardcoded numbers. All DT1 bindings survived; the user even added a correct centering expression
(JointSeatZ - Neck/2) that improved on the original instructions. Confirms the manual workflow is
robust and that native expression-driven joints tolerate hand-editing — the core property the previous
custom-coded attempt lacked. The Phase 1 tool must preserve this: its output stays as editable as a
hand-built model, including surviving user-added expressions.
Note: with no rotation applied to the joist placement, dimensional match ("looks lined up") can occur
without true 3D seating. Reinforces the value of the Preview Mated Joint feature for unambiguous fit
verification.

## Established principle — Datum strategy (manual workflow)
Adopted after the Session 4 datum-offset confusion. Offsetting a datum attached to a rotated reference
plane (the XZ/YZ origin planes have rotated local frames) sends the offset along an unexpected global
axis. Minimize this by:
1. **Sketch on a native face with zero offset** whenever the sketch belongs on an actual timber face.
2. **Set depth via the pocket/pad length**, not a datum offset (housing depth, mortise depth, etc. are
   extrude distances).
3. **Position along the timber with a sketch constraint**, not the datum offset (keeps the position
   parameter in the body frame so it maps predictably).
Reserve offset datums for genuinely floating planes (e.g. mid-depth reference); when used, offset along
the body's known axis and verify the resolved placement. Fully superseded in Phase 1, where the tool
computes references in the body's own coordinate frame.

## New roadmap additions
- **Preview Mated Joint** (Phase 1/2): visualize the two halves of a joint engaged regardless of
  body orientation, for at-a-glance fit verification.
- **Landing-face-relative joint definitions**: joints defined by (landing face, reference faces,
  assembly direction) rather than raw body-local planes, so the tool picks correct sketch planes and
  cut directions automatically.

### 12. Duplicating a jointed body carries phantom features — RITUAL ⚠ Session 4 (this thread)
The Joist was duplicated from the Post after the Post had joint features. The copy carried
Housing_MT001, Mortise_MT001, their sketches, a datum, and duplicate VarSets (MT001, BeamDims001).
With JointHeight beyond the shorter joist's length, the phantom pockets cut nothing and were
invisible on screen — detected only by file inspection.
**Rule:** duplicate only clean template bodies; keep a pristine template Body in the document
(or re-import from TimberTemplate.FCStd) for all new timbers.
**Automation response:** "New timber from template" always instantiates from the pristine
template, never from an existing jointed timber.

### 13. Symmetry constraint is order- and target-sensitive — RITUAL → adopted workaround
The Sketcher Symmetry constraint failed to apply during the dovetail trapezoid (selection order:
two points first, then the symmetry line; rejects edges where it wants vertices). User workaround:
half-width distance constraints from a centerline construction line (e.g. TipWidth/2, NeckWidth/2).
**Adopted as the standard method** — equally parametric, fewer failure modes.
**Automation response:** generated sketches use centerline + half-width constraints, not Symmetry.

### 14. Island pockets require a strictly interior island — GUESS/VERIFY ⚠ Session 5
The island-pocket technique (outer removal loop + inner kept profile) fails when the island
touches the outer loop: the dovetail trapezoid's tip edge lay on the outer rectangle's edge,
and the coincident edges broke face generation for the whole sketch. The tenon island worked
because its profile is fully interior. User workaround, adopted as standard: when a kept
feature touches a boundary face, sketch the removal regions directly (two flanking
quadrilaterals sharing the dovetail's angled sides).
**Automation response:** the tool chooses island-pocket vs. direct-removal-region sketches
based on whether the kept profile touches the section boundary — computed, not discovered.
