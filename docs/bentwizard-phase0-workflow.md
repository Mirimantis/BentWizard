# BentWizard — Phase 0 Workflow Document

Status: Phase 0 complete. This document records the manual workflow proven across twelve modeling sessions in FreeCAD 1.1.1, the conventions that emerged, and the recipes the Phase 1 tools must reproduce. It is the specification the automation is built against. Companions: the roadmap (rev 3) and the friction findings log.

## 1. Governing Rules

**Tier 1 — geometry stays native.** All solid geometry is ordinary FreeCAD: Sketches, Part Design features, datums, Assembly joints. Anything a tool produces must be hand-editable with stock FreeCAD afterward. Test: uninstall the workbench — the model must open, edit, and recompute identically.

**Tier 2 — data degrades gracefully.** Non-geometric data (species, grade, roles, joint metadata, schedule counts) may be workbench-aware, implemented as custom properties on native objects: visible and editable without the workbench, surviving round trips. Workbench-gated functionality (checks, generators, reports) is acceptable; gated geometry is not.

**Subtractive joinery.** Joints are modeled the way wood is cut — pockets and holes, not pads. `Length` in a timber's VarSet is the full stick as purchased; shoulders land at joinery offsets from the stick ends; drawings dimension the way a tape measure reads.

**Mill Rule** *(reframed July 2026 — this rule was labeled "Square rule" through Phase 0; the geometry is unchanged)*. Every timber's two reference faces lie on its XZ and YZ origin planes (section sketch pinned corner-to-origin). Joint layout dimensions always measure from reference faces and stick ends. Drawings dimension an idealized straight, square timber — a Mill Rule drawing. Housings are optional bearing features cut to designed depths referenced from origin planes; Square Rule's reduce-to-ideal housing (cutting a rough stick down to the ideal timber inside it) depends on the individual log, never appears as a drawn dimension, and is field work outside the model.

## 2. Vocabulary

Faces numbered 1–4: Face 1 is the reference face, 2–4 clockwise viewed from end A. Ends: A (butt, at the body origin, Z=0) and B (tip, at Z=Length). Orientation terms: plumb, level, pitch, roll, skew. Relationship terms: coaxial, orthogonal (in plan / in elevation), oblique, coplanar, offset, bearing face. In this project's models: Face 1 = the XZ-plane face, Face 2 = the YZ-plane face. Soft convention (Phase 1): Width reads horizontal and Depth vertical in a member's installed orientation, wherever applicable.

## 3. Document Structure

One document per prototype scope (single doc held four timbers, three joints, assembly, drawings, cut list without strain; multi-file split is an open item for large frames). Objects at root: one VarSet per timber (Dims), one VarSet per joint instance, group VarSets (section/project), timber Bodies, the Assembly, TechDraw pages, spreadsheets.

Naming (decided at the Phase 1 shakedown, supersedes the earlier
positional MemberID scheme — which is grandfathered as advisory-clean in
existing files):
- **Two names, two jobs.** The **Label is the permanent identity**:
  chosen at creation, descriptive of what the piece IS, and never
  encodes position (a new timber has no position yet, and positions get
  reassigned). **Position is Tier-2 data**: the `Position_Tag` string
  property on the Dims / joint VarSet ("Bent 2, north post"), displayed
  on layout drawings and lists; nothing binds to it, so it can change
  freely. (FreeCAD's own immutable Internal Name, `Body003`, is file
  plumbing — never used semantically.)
- **Timber Bodies** (loosened July 2026 — since labels no longer carry
  position and are never rewritten when a bent is renumbered, the only
  constraints left are what the tooling needs): a **free-form label
  ending in a separator + digit serial**. Recommended style stays
  `T-<Role>[-<Qualifier>...]-<serial>` (`T-Post-Level1-003`); dotted or
  spaced forms (`T-Post.Balcony.001`) are equally valid. The serial is
  the trailing digit run after a separator (`-`, `.`, `_`, or space);
  tools allocate the next free serial per base, preserve the user's
  separator, and only ever touch that segment (digits glued to letters,
  like `Level1`, are never rewritten). A label without a serial gets
  one appended: ending the name with a separator picks it
  (`T.Post.solarium.` → `T.Post.solarium.101`, counting the existing
  family); otherwise the family's own separator is adopted, then the
  base's last separator (`T-Post` stays hyphenated), defaulting to a
  dot (`Solarium` → `Solarium.001`). Advisory lint nudges toward
  adding a serial.
  **Reserved characters** — strict lint, verified against the 1.1.1
  expression engine: `>`, `\`, `;`, and line breaks break `<<Label>>`
  expression references or the `Placement_Record`; everything else
  survives the round trip (dots, spaces, quotes, unicode, `<`, `#`,
  `&`, parentheses, …).
- **Joint instances**: `J-<Kind>-<serial>` — `J-HousedMT-001`. The kind
  token comes from the library template's file stem.
- **VarSet labels**: `Kind_Owner` with a descriptive kind prefix —
  `TimberDims_T-Post-003`, `Group_LoftDovetail`, `Project_Main`,
  `Order_Main`; joint VarSets carry the joint's own `J-<Kind>-<serial>`
  label (one VarSet per joint instance, the VarSet IS the joint).
- **Tree organization** (pure organization, zero geometric effect): each
  Dims VarSet nests inside its timber's Body; joint VarSets live in a
  `TimberJointVars` Std Group (renamed from `Joints`, which collides
  with the `Joints` group inside every FreeCAD Assembly; legacy
  documents are migrated); bents/bays are user-arranged (optionally nested)
  Std Groups of Bodies — Duplicate Timbers can create one for the copies.
- **Property names**: `Part_Attribute[_Qualifier]`, most-significant first: `Tenon_Thickness`, `Tenon_Setback_Face2`, `Housing_Depth`, `Peg_Drawbore_Offset`, `Peg_Count`. Reference-face qualifiers use `_Face1`/`_Face2` (stable regardless of timber orientation; Face 1 = XZ-plane face, Face 2 = YZ-plane face). Alphabetical property sorting then clusters each part's parameters automatically.
- **Tooltips**: mandatory on every template-defined property, written by the template author, cloned on apply. As brief as possible while still informative; always states which face/end it measures from; timber framing terminology. Missing tooltip = advisory linter failure.
- **Joint features within bodies**: body-qualified to avoid document-unique label collisions — convention `<TimberLabel>_<Feature>_<JointLabel>` (e.g. `T-Post-003_Mortise_J-HousedMT-001`; legacy `P2-1_Mortise_MT_B2a`).

## 4. Proven Recipes

### 4.1 Parametric timber
One Body. Section sketch on XY plane, rectangle in the first quadrant, corner coincident with origin, width/depth bound to the timber's Dims VarSet. Pad to `Dims.Length`. The origin planes are now the reference faces and are indestructible by later features.

### 4.2 Duplication — the ritual
What duplicates vs. stays shared follows intent and the group-layer boundary. New blank timber: duplicate the Body + its Dims only — never source from a jointed timber (phantom features travel silently). Copying a jointed timber or whole bent is legitimate and intended: Dims AND joint-instance VarSets duplicate (each copy owns its joints), while group bindings are preserved to the same shared group VarSets. In the dialog: the dependency list auto-includes everything — check what should become independent, UNCHECK what must stay shared. After duplication: relocate the copied VarSet in the tree, rename both, and verify independence by changing a dimension. Audit every expression in the copy — sketches, spreadsheet rows, hole features have all been caught still pointing at the source's VarSet.

### 4.3 Joint instance VarSet
One VarSet per joint instance, holding all parameters for both halves (the mated-pair mechanism). Properties may pass through by expression to group VarSets (see 4.9). Prototype shortcut to avoid in production: MT1 drove both beam ends; real frames use one instance per joint.

**Junction point for cross-timber coupling (decided at Phase 1 start).** A joint parameter that must track a mating timber's dimension is a property on the joint VarSet, bound by expression to that timber's Dims — e.g. `J-HousedMT-001.Housing_Width = <<TimberDims_T-TieBeam-001>>.Depth`. Features inside a body reference only their own timber's Dims and joint VarSets, never another timber's Dims directly (the prototype's housing sketches did, and `PegHole_MT1_sketch2 → PostDims` shows how it fails silently after duplication). Propagation stays fully native — resizing a timber flows through the joint VarSet into both halves with no workbench involvement — while all cross-timber coupling for a joint is enumerated in one visible, auditable, remappable place. Overriding a tracked dimension is the standard group-override move: replace the expression with a literal on the joint VarSet.

### 4.4 End tenon — island pocket
Sketch on the end's plane (XY origin plane at end A; offset datum from XY at `Length` for end B). Two loops: outer rectangle = full section (corner at origin, Dims-bound), inner = tenon profile (Setbacks and dimensions bound to the joint VarSet). One Pocket, depth = TenonLength, cutting into the stick. The inner loop survives as the tenon. Requires the island strictly interior to the outer loop.

### 4.5 Boundary-touching profiles — removal regions
When the kept profile touches the section boundary (dovetail tongue at the top face), the island method fails on coincident edges. Sketch the removal regions directly instead — e.g., two flanking quadrilaterals sharing the dovetail's angled sides, then a second through-all cut for the underside. Symmetry via centerline construction line + half-width constraints (never the Symmetry constraint).

### 4.6 Housed cuts on the receiving timber
Bearing plane as a datum attached to the receiving timber's origin plane, offset by expression (`Width - HousingDepth`). Housing profile and mortise profile sketched on that datum; housing pocket outward (depth HousingDepth), mortise pocket inward (depth TenonLength + MortiseRelief). Handed mates: the mirrored timber's lateral setback = `Depth - SetbackX - TenonThickness`.

### 4.7 Pegs and drawbore
Hole features (through-all) on sketches on origin planes. Post bores at true position (`PegSetback` from the bearing plane, centered on tenon width). Tenon bores displaced `DrawboreOffset` toward the shoulder — sign flips between ends A and B. Peg solids are not modeled; `PegCount` lives in the joint VarSet for the hardware schedule.

### 4.8 Assembly
Assembly workbench, one grounded timber, Fixed joints between tree-selected datums only (never 3D-picked solid faces). Shoulder datums on stick ends offset by expression. Expect orientation iteration: a plane mate leaves two orientations (rotate 180° about the connector normal to flip), and rotation pivots at the connector origin, requiring a compensating in-plane offset (often a full timber width). Handedness surfaces here — posts in a bent are often mirror pairs, but bents can be asymmetrical: hand is a per-joint-application property, never assumed from bent symmetry.

*(Automated in Phase 1: Apply Timber Joint seats each joint on creation via the JointFrame/MateFrame records — the orientation iteration above is eliminated by the mate-parity rule and pre-seating; see the roadmap's two-level structure assembly design. This section stays as the manual ground truth the tools reproduce.)*

### 4.9 Parameter groups
Instance VarSet properties bound by expression to group VarSets; groups to higher groups (instance → type → section → project, keep it ≤3 layers). Override = replace one property's expression with a literal. Group membership IS the binding — no hidden state. Validated end-to-end: ProjectVars.FloorHeight moved the entire bent.

### 4.10 TechDraw
Sheets are generated per FabricationSignature by default — one sheet per fabrication group, listing quantity and all MemberIDs in the group — with a per-timber option for shops that travel a sheet with each stick. Projection group per sheet (front + plan minimum), hidden lines on, scale to sheet. Dimensions from stick ends and reference faces per the reference-face convention (Mill Rule). Dimension/font styles set explicitly per document, never inherited from preferences. Parametric round trip verified: model changes flow to views and dimensions.

### 4.11 Cut list
Spreadsheet as procurement document: ID, species, grade, moisture, finish, cut type, section, designed length, cut length (= designed + `OrderVars.TrimAllowance`), board feet, order total (`=sum(range)`). Dimension cells bound by expression to the correct timber's own Dims VarSet — cross-referencing a sibling's VarSet is the recurring silent bug. Joinery callouts belong on drawings, not here.

## 5. Verification Methodology

In-model: top/side orthographic views (never trust wireframe when profiles align in two axes), clipping planes through joints, the Measure tool between mating faces. In-file: unzip the FCStd, read Document.xml, and always resolve the full placement chain (Body placement × sketch/datum placement) before interpreting sketch coordinates — assumed axis mappings produced this project's one false diagnosis. Attachment offsets must be read in full; stray values hide in unexamined components.

## 6. Findings → Linter

Strict (breaks the clone mechanism or the model): one VarSet per joint instance; no multi-instance sketches; no cross-timber Dims references; no solid-face references (sketch supports, assembly joints, dimensions); islands strictly interior or removal regions used; expression audit on duplicated objects; parameter values within severing limits (mortise ≤75%, housing ≤50%); Body/VarSet labels free of the reserved characters (`>`, `\`, `;`, line breaks) that break `<<Label>>` expressions and the `Placement_Record`.

Advisory (style and drift): naming conventions (Kind_Owner VarSets, trailing serial on body labels — otherwise free-form per §3); centerline + half-width in place of Symmetry; parameter values past the 35% caution threshold; instances deviating from their group bindings; stale attachment-offset components; unrenamed auto-labeled features.

## 7. Known Prototype Debts (fix before reuse as templates)

- MT1 drives both beam ends and both posts — split into per-instance VarSets when templatizing.
- Combined two-circle peg sketch on the beam — one sketch per instance.
- PegHole_MT1_sketch2 (Post2) references PostDims — should be Post2Dims.
- Post2's hole feature unnamed (Hole001); tongue-sides pocket renamed?
- ProjectVars.FloorHeight left at test value 54 in.
- All prototype VarSets and properties predate the decided naming convention; rename when templatizing.

## 8. Open Items

Units/dimensioning display (fractional inches) for TechDraw; body-qualified feature label convention; joint library location and manifest format; single- vs multi-document frames; skeleton-sketch layout evaluation; provenance/group visualization UI.
