# BentWizard — Timber Framing Workbench Roadmap (rev 3)

**Name:** BentWizard (retained from the prior iteration; architecture is new)

**Target platform:** FreeCAD 1.1.1
**Layout convention:** Square rule (housed joints referenced to an idealized timber within the rough stick)
**Pilot project:** Generic test bent

## Governing Rules (amended)

**Tier 1 — Geometry stays native. Unchanged, non-negotiable.**
All solid geometry is built from ordinary FreeCAD objects: Sketches, Part Design features, datums, Assembly joints. Anything the workbench produces must be editable by hand with stock FreeCAD, as if a person had modeled it. This is the lesson of the failed prior attempt.

**Tier 2 — Non-geometric data degrades gracefully.**
Species, grade, joint metadata, check results, and similar data may be workbench-aware. Requirements: (a) with the workbench uninstalled, parts and assemblies remain fully editable — custom properties on native objects satisfy this, since FreeCAD stores them in the file and shows them in the property panel regardless; (b) custom data survives a round trip through a system without the workbench; (c) workbench-gated *functionality* (checks, reports, generators) is acceptable, since behavior — unlike geometry — is regenerable.

**Modeling convention — subtractive joinery.**
Joints are cut the way wood is cut: pockets and holes preferred over pads. Consequences:
- `Length` in a timber's VarSet = the full stick as purchased and cut, tenons and tongues included. Cut lists read it directly.
- Tenons via island pockets: one sketch with an outer removal loop and an inner tenon profile; the pocket leaves the island standing.
- Tenon shoulders land at `Z = TenonLength`, not the origin plane; assembly references use shoulder datums or expressions.

**Datum strategy (manual workflow):** sketch on native origin planes or faces with zero offset where possible; set depth by pocket/pad length, not datum offset; set position along the timber by sketch constraint. Reserve offset datums for genuinely floating planes and verify their resolved placement. (See findings log #10.)

## Phase 0 — Manual Workflow Definition (in progress)

Done: parametric timber template · housed mortise & tenon (MT1, shared VarSet driving both halves) · housed dovetail (DT1).
Remaining:
1. Cleanup + subtractive rework of Tenon_MT1 and Tongue_DT1 (session 5)
2. Pegs + drawbore on the M&T
3. Assemble the test bent (Assembly workbench, datum-to-datum)
4. TechDraw: one sheet per timber + bent elevation
5. Manual cut list in Spreadsheet
6. Final workflow document

## Phase 1 — Joint Library & Application Tool
- Joint templates as ordinary FreeCAD files.
- Apply-Joint tool: reproduces the manual steps — cloning native sketches/features, binding a shared VarSet — with parameters entered as plain numbers, expressions written programmatically.
- Mated-pair logic: one VarSet per joint instance drives both timbers.
- Square-rule aware: housings referenced to named reference faces.
- **Landing-face-relative joint definitions** (from findings #9): one joint instance = one VarSet + one landing-frame datum per timber role. Implementation verified in 1.1.1 (Phase 1 start): the frame is a `Part::LocalCoordinateSystem` datum; sketches and datums attach to the frame's own planes and follow it rigidly, so retargeting face/station/end/hand = re-placing one object. Caveat: followers must reference the LCS sub-element, not its child plane object (the latter resolves to identity placement). Template sketches are position-agnostic — constrained only to the joint VarSet and their own timber's Dims — and attach to the landing frame, which the tool places and orients (end, station, hand). Strict linter rules: one VarSet per instance; no multi-instance sketches; no cross-timber dims references; no solid-face references. Joint templates carry non-geometric schedule data as VarSet properties (e.g. PegCount).
- **New timber from template**: atomic duplicate of pristine template + VarSet with verified remap (findings #2, #12). **Duplicate bent**: instance-layer VarSets (Dims, joints) duplicate; group bindings preserved.
- **Preview Mated Joint** (findings #7, #11): display both halves engaged for at-a-glance fit verification, independent of body placement.
- Generated sketches use centerline + half-width constraints, not Symmetry (findings #13).
- **Parameter sanity bounds** (inherited from prior iteration): apply-dialog computes min/max from the timbers involved — mortise width ≤ 75% of receiving extent, housing ≤ 50% of through-dimension, dovetail flare clamped to member extent. Linter: strict at severing limits, advisory warning at 35%.
- **User-authored joint templates**: a joint template is an ordinary FreeCAD file — one VarSet (the parameter schema) plus per-role feature stacks. Users author new joints by modeling them manually per project conventions; a "Save as joint template" tool validates (a linter built from the findings-log conventions: origin-plane sketches, single shared VarSet, no solid-face references, half-width constraints, naming, interior islands or removal regions) and registers the file into the library. The apply-joint dialog is generated from the template's VarSet properties — no per-joint code, so adding joints requires no programming. Clone architecture gives free versioning: template edits never affect already-applied joints.
- **Parameter provenance UI**: from any timber or joint, view where its numbers come from — group memberships, binding chains, and overrides; advisory linter reports group deviations.
- **Layered parameter groups**: instance VarSet properties may pass through by expression to group VarSets (type → section → project). Sharing = binding; overriding = replacing one property's expression with a literal; group membership = the binding itself (no hidden state, Tier 2 clean). Tools: "assign selected to group" (bulk expression rewrite), apply-dialog fields accept literal or group binding, advisory linter reports instances deviating from their group.
- Subtractive convention assessed after Phase 0 assembly: runtime cost neutral (templates are cloned, not computed), template-design cost slightly higher (removal-region decomposition), bookkeeping decisively better (stick-length parameter, tape-measure-true drawing dimensions). Retained.

## Phase 2 — Cut Lists & Drawing Automation
- Cut list is a **procurement document** (per session-10 redesign): timber ID, species, grade, moisture, finish, cut type (boxed heart / FOHC / quartersawn), section, designed length, order length (= designed + trim-allowance parameter), board feet per stick, and order totals. Joinery callouts live on shop drawings / a joinery schedule, not the cut list.
- Specification fields (species, grade, moisture, finish, cut type) are Tier 2 properties on each timber; the generator reads them — the spreadsheet is output, never the source of truth.
- Hardware/peg schedule: generator sums per-joint counts (VarSet properties like PegCount) grouped by diameter; peg length derivable from bore depth + proud allowance.
- Batch TechDraw: projection-group-based dimensioned shop sheets per FabricationSignature (quantity + MemberID list on each; per-timber sheets as an option); frame/bent elevations. Generated sheets set dimension/font styles explicitly, never inheriting user preferences.
- **MemberID convention** (adopted from prior iteration): `[RolePrefix][BentNumber]-[Position]` (P2-1, BR2-1), bay references for longitudinal members (PU-B2-3). Driven by a `Role` enumeration property (Tier 2) on each timber. IDs are display labels; internal object names stay stable; warn on renumbering. Round-trips between model, drawings, and list.
- **FabricationSignature** (adopted): normalized hash of species, grade, section, stick length, end cut angles, and joint layout in timber-local coordinates. Identical signatures form fabrication groups in the cut list (`GROUP 7 — Qty: 4`). Handed mirrors hash differently (consistent with findings on handed pairs).
- Shop drawings carry reference-face marks and A/B end labels per the adopted face vocabulary (faces 1–4 clockwise from the reference face, viewed from end A).
- Evaluation item: per-bent driving **skeleton sketch** (native Sketcher) as the layout layer — the prior iteration's datum-line concept in native form.

## Phase 3 — Species & Grade Material Library
- Custom properties / Materials cards with NDS design values (Fb, Ft, Fv, Fc, Fc⊥, E, Emin), green vs. dry.
- Tier 2 compliant: data visible and round-trip-safe without the workbench.
- **Reference data system** (adopted): bundled read-only CSVs (species_properties from NDS, section_properties) with a user-override directory checked first at lookup; user rows visually distinct, base rows never edited in place.

## Phase 4 — Structural Checks (start simple, grow later)
1. **Load-path continuity** — every timber has a complete path to a bearing point; disconnected members flagged. Cheapest, most valuable early check.
2. Span-table checks (AWC tables via reference data system) and rule-of-thumb checks, advisory only.
3. Member stress checks: bending M ≤ Fb·S, shear V ≤ Fv·A·(2/3), deflection Δ ≤ L/360, driven by tributary-area load accumulation from **BuildingParameters** (roof material / snow / occupancy / wind presets, ASCE-derived, as a project-level parameter group).
4. FEM studies of individual joints (orthotropic properties via CalculiX) seeding a joint_capacities table (TFEC 1-2007 + FEA-derived).
5. Lightweight frame analysis with beam elements and semi-rigid joints from the capacities table; racking checks with per-bent brace contributions; bearing-point reaction schedule.
6. Load/capacity color overlay via native body ShapeColor (blue <30% → red >100%, grey unchecked); structural report with clickable findings.
Always labeled design guidance, not stamped engineering.

## Phase 5 — Building Composition (future, preserved from prior iteration)
Ground planes and bearing-point projection; auto-generated sill beams; split-level ground planes; frame openings (stairwells, dormers) generating headers/trimmers with load redistribution; wall-opening placeholders; chimney clearance zones; cantilever load paths; bent layout templates (King Post, Queen Post, Hammer Beam) as saved native layouts.

## Layout rules — Mill Rule / Line Rule support (assessed Phase 1)

Square Rule is **not** a foundation; it is a template-authoring convention riding on rule-neutral machinery. The rule is a *contract* between two templates — the timber template says where the reference planes are (section corner at the body origin → reference faces on the XZ/YZ origin planes), the joint template measures joinery from those planes — and the tools mostly clone whatever the author built rather than knowing geometry.

Genuinely square-rule-baked pieces, exhaustively:
1. `new_timber`'s section (reference corner at origin).
2. The `FACES` table + `_face_transform` in `apply_joint` — the only square-rule-baked *tool code* (corner-referenced face complements `ddim - T`); ~20 isolated lines.
3. Two linter checks reference housing concepts (`joint-exceeds-footprint`, housing≤50% severing) — already no-op when a template has no `Housing_*` properties.
4. The `_Face1`/`_Face2` naming vocabulary.

Rule-agnostic (the bulk): the clone/rebuild machinery, `remove_joint`, junction-point coupling, end/hand placement transforms (frame-relative), the schema-driven dialog, and the **MateFrame** (a pure "these two frames coincide when engaged" declaration — zero knowledge of how either frame was derived; the reason engagement and future assembly are rule-blind by construction).

Cost:
- **Mill Rule ≈ free.** Essentially Square Rule with housings → 0 (accurate stock needs no reduce-to-ideal step). Same corner-referenced section, so `new_timber` and `FACES` are unchanged. It is new joint templates (fewer/no housings) in `library/` plus a label — no core code; the footprint check simply does not fire without housing properties.
- **Line Rule = moderate but contained.** Reference datum moves corner→center: a centered timber-template variant (centerline construction + half-widths; origin planes become centerplanes), a second `FACES` table (reflections about center, not corner complements, ~15 lines), and rule-aware linter vocabulary. Landing-frame expressions differ but are authored in the template, not tool code. No changes to clone/rebuild/mate/remove.

Structure when built: a single Tier 2 `Rule` property (`SquareRule`/`MillRule`/`LineRule`) on timber Dims and joint templates; templates filter/label by it; New Timber offers the choice; `FACES` becomes rule-keyed; Apply Joint validates rule-compatibility; the linter branches face-vocabulary and housing checks on it. Caveat: a real Line Rule port wants an audit pass over every linter rule and the placement transforms to catch any corner-assumption under-counted above.

## Open Items
- New Timber dialog: Role/Bent/Position selectors with auto-generated MemberIDs once bents exist (ties to the Phase 2 Role property); custom labels stay allowed for non-standard roles, nudged by the advisory naming rule.
- Apply-Joint parameter bounds, phase 2 of: live min/max clamps on the dialog fields computed from the chosen timbers (the pre-flight refusal on resolved values exists); longer term, constraint relationships declared in the joint template itself (Tier 2 metadata) instead of name-keyed heuristics.
- Visual indication of the reference faces (Face 1/Face 2) on a timber in the 3D view.
- Joint parameter presets ("TieBeam01"): note this is the **type layer of the parameter groups design** (§4.9 instance → type → …) — a preset = a Group VarSet the instance binds to, giving persistent, editable-once presets rather than dialog memory. Near-term convenience: a "copy parameters from existing joint" picker in the Apply Joint dialog.
- **Primary/secondary timber roles per joint** (load-path based — the primary carries the weight of the secondary). Currently inferred structurally: the mate-frame carrier is the secondary (the piece that enters and is previewed as a ghost), the other role the primary. Formalize as explicit joint-template metadata (Tier 2) with a load direction — feeds Preview (which half ghosts into which), Assembly (which is grounded), and the Phase 4 load-path continuity check. The mate-frame heuristic is correct for M&T but should not stay the definition.
- **Preview Mated Joint UI**: the run-again-to-clear toggle works but is unintuitive. Wants a clearer affordance (a visible preview state / dedicated clear). Live parameter tracking is done (the ghost attaches to the landing frame via its body-local placement, following station/section/tenon-shape edits and seating wherever the primary body sits). Two edits need a refresh: `Tenon_Length` (relocates the mate frame within the secondary) and moving a body with the transform tool while the preview is up — a future refinement could recompute the ghost placement on every recompute (e.g. a small FeaturePython) to cover both.
- Joint browsing at scale: the Remove Joint picker (and future joint dialogs) needs filtering by Bent/Bay/Timber once projects carry hundreds of joints. 3D selection: joint members (the landing frame is a clickable datum) already preselect the Remove Joint picker; the fuller idea is a per-joint proxy with a ViewProvider context menu (VarSet access, remove, re-place operations such as rotating a mortise to a different face without re-creating) — workbench-gated behavior on a native object, Tier 2 clean.
- Tree/panel ergonomics: a dock panel showing a timber's Dims VarSet when the timber is selected. Moving the Dims VarSet inside its Body is NOT planned: PartDesign bodies restrict member types and out-of-body expression references into body internals trip FreeCAD's link-scope rules — the flat root layout is deliberate. (Also answers the setback-naming concern in docs/User Notes.txt: `_Face1`/`_Face2` qualifiers are the stable square-rule references, but which physical direction they mean per timber needs to be visible.)
- Full-depth tenon variant (tenon height = beam depth, fewer shoulder cuts): the island pocket breaks on coincident edges at exactly that limit (finding #14), so it is a separate library template built on removal-region sketches — per the finding #14 rule, boundary-touching kept profiles use removal regions, not islands.
- Units: decided (Phase 1) — the workbench defers to the user's FreeCAD unit schema (e.g. "Building US" for fractional inches), never forcing imperial or metric. TechDraw dimension style details remain open.
- Feature label scheme within bodies: `FeatureType_JointID` collides across bodies sharing a joint (labels are document-unique) — needs body-qualified convention.
- Joint library location (folder vs. addon structure) — decide at Phase 1 start.
- Single document vs. multi-file for large frames — revisit after the test bent.

## Division of Labor
Adam: FreeCAD driving, joinery domain decisions, testing against real workflow. Claude: all Python development, FreeCAD API research, step-by-step instructions, file-inspection verification (against resolved global placements — findings #10).
