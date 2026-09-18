# BentWizard — Workflow Document (rev 2)

> **Terminology note (2026-09-18, after this document was written).** The
> coordinate system a timber carries is a **datum** in code, UI and every
> later document — never a "frame". To a framer a frame is a structure
> made of wood, and the parent assembly is already `Frame-NNN`. Where this
> document says *mate frame*, *frame accessors* or *F_Post_J1*, read
> *mate datum*, *datum accessors*, `D_T-Post-001_YPos_001`. Two facts
> found while building to this document are recorded inline below,
> marked **[built]**: the cross-timber accessors live on the joint
> VarSet, not on the datums (mutual `Mate*` accessors are an
> object-granular dependency cycle), and the parity rule covers opposite
> faces as well as ends.

Supersedes the Phase 0 workflow document. Rev 1 recorded a manual workflow built on a subtractive mandate, typed stick lengths, square-rule layout doctrine, and joints rebuilt sketch-by-sketch on the target timber. Spike rounds 1–3 and the mate-frame GUI tests replaced all of that. Everything below is proven in FreeCAD 1.1.1, headlessly and in the GUI, unless explicitly marked open.

Companions: the roadmap, the friction findings log, and the spike results (`spike-variant-link-results.md`, `spike-copyobject-results.md`, `spike-round2b-results.md`, `spike-round3-results.md`).

## 1. Governing rules

**Geometry stays native.** All solid geometry is ordinary FreeCAD: Sketches, Part Design features, Bodies, LCS datums, Assembly joints. Anything a tool produces must be hand-editable with stock FreeCAD afterward. Test: uninstall the workbench — the model must open, edit, and recompute identically.

**Data degrades gracefully.** Non-geometric data (species, grade, roles, face labels, joint metadata, schedule counts) lives in custom properties on native objects: visible and editable without the workbench, surviving round trips. Workbench-gated functionality is acceptable; gated geometry is not.

**Prefer native mechanisms over reimplementation.** The rule that supersedes rev 1's subtractive mandate. Instancing is `copyObject`, not a rebuild engine. Placement is an expression, not computed geometry. This is the general principle the earlier two failures both violated, in different ways.

**Cutter + adder.** A timber Body is the **design solid**: its length is the frame dimension, bearing face to bearing face, and it does not change when joinery is applied or swapped. A joint template half carries an optional **cutter** solid and an optional **adder** solid, applied as booleans. Order length is derived from the resulting solid, never typed.

| Joint half | Cutter | Adder |
|---|---|---|
| Housed mortise | yes | no |
| Square-shouldered tenon | no | yes |
| Angled-shoulder tenon | yes (shoulder) | yes (tenon) |
| Butt / plain end | no | no |

**Fit conventions**, from validation: a tenon gets **no lateral allowance** — cheeks must be tight. Clearance goes in *depth* only (`MortiseFit`), so the shoulder seats rather than the tenon tip bottoming out. Mortise depth is measured from the housing floor, not the timber face: `TenonLengthZ + HousingDepth + MortiseFit`, with the tenon padded `TenonLengthZ + HousingDepth` to match.

**Frames belong to timbers.** Mate frames are LCS objects owned by the timber, created before any joinery, surviving every joint swap. A joint is applied *to* a frame; it never owns one. Proven: deleting a joint's Boolean and adder and applying a different one left the Assembly joint untouched.

**No layout doctrine.** Square rule versus mill rule is shop practice. The deliverable is accurate geometry and good dimensioned drawings; the framer lays out however they choose. Housings remain a joint parameter — they are real geometry and a design decision.

## 2. Vocabulary

**Timber-local frame.** A timber is modelled along its own **Z** axis, section centred on the origin. Dimensions are `WidthX`, `WidthY`, `LengthZ` — deliberately free of orientation connotation.

**Frame-local frame.** A mate frame's accessors use **UVW**: `WidthU`, `WidthV` (the host's extents along the frame's local X and Y) and `DepthW` (the host's extent behind the frame, along −Z). XYZ is always timber-local, UVW always frame-local, so a template author reading `DepthW` cannot mistake it for a timber dimension.

**Faces** are `+X`, `−X`, `+Y`, `−Y` — the internal, unambiguous identity, used by every expression, placement and tool. **Ends** are A (Z = 0) and B (Z = Length).

**Face labels** are per-timber display aliases (`FaceLabelXPos` etc.), defaulted from the timber's *role* (post → outside/inside/bent-left/bent-right; plate → top/bottom/outside/inside; and so on — not built yet, and "`Frame_Role`" in the first draft meant this timber role, not rev 1's landing/mate marker), user-overridable, surfaced on drawings, in the joinery schedule, and in the apply dialog's face picker. **Never a selector** — renaming a face must never affect geometry.

Rev 1's face 1–4 numbering and reference-face concept are retired with the layout doctrine.

## 3. Naming

- **Timber Bodies**: a permanent identity ending in separator + serial (`T-Post-003`, `T-Post.Balcony.001`); position is the display-only `PositionTag`. **[built]** — rev 1's positional MemberIDs (`P2-1`) were superseded at the first shakedown and are not the convention.
- **VarSet labels**: `Kind_Owner` — `TDim_T-Post-003`, `J-HousedMT-007` (a template's own joint VarSet is `J-<Kind>-000`; the "`JointParams`" of §4.3 below means this VarSet), `Project_Main`, `Order_Main`.
- **Property names**: UpperCamelCase, FreeCAD convention, no separators (`MortiseThickness`, `HousingDepth`, `TenonLength`, `PegCount`). A trailing digit does not get a display space; accept it.
- **Tooltips**: mandatory on every template-defined property.
- **Joint component bodies**: `<Role>.<Kind>.<serial>` — `Mortise.MT.001`, `Tenon.MT.001`. Document-unique by construction.

## 4. Proven recipes

### 4.1 Parametric timber
VarSet `TDim_<id>` with `WidthX`, `WidthY`, `LengthZ` (**[built]** — the names §2 gives; `XWidth`/`YWidth`/`Length` here was a slip). Body with a section sketch on XY, **centred on the origin** (half-width constraints from centrelines, not corner-pinned), padded to `Length`. Stored properties are always full dimensions; halving happens in expressions.

### 4.2 Mate frames

LCS objects owned by the timber, created before joinery. **Positioned by direct placement with `MapMode` Deactivated — never by attachment.** Attached-datum axis mapping has produced three separate bugs in this project; direct placement is predictable.

**Every frame's local Z points away from its host's material** — end or face, no exceptions. The material is behind the frame, the world in front. A cutter is therefore always modelled in −Z and an adder in +Z, and one template applies unmodified to either end of a stick (proven, Part H1: the same tenon body fused at both ends of the girt with only its frame reference changed). The Z→−Z flip at end A is **180° about local Y**, declared rather than derived.

**The flip axis carries no handedness.** Any rigid Z→−Z flip preserves exactly one in-plane axis and swaps the other: under the Y-flip an adder offset toward +X at end B sits toward −X at end A, while a +Y offset stays +Y (Part H2, both flips measured). What a framer expects is that a component keeps its **timber-local x,y offsets at both ends**, and that is a *mirror*: applying at the flipped end always mirrors the component across the frame's local X before placing it (§4.4 step 3). Decided 2026-09-18; never by choosing a frame rotation.

A frame's orientation is a property of the timber it belongs to, never of what it is mated to. Seated frames are consequently antiparallel, and the Assembly joint carries the 180°. This is not negotiable: a single frame may host both a cutter and an adder (a brace's angled shoulder plus its tenon), which only works if ±Z is defined against its own host's material.

**Frames are generated by the tool, never placed by hand.** A user picks a face and a station; the tool writes position, rotation and accessors from one row of the face table below. Two separate failures during validation came from a human setting placement fields manually — the rotations are non-obvious (two of the four are 120° about a diagonal axis), and a rotation/position pair taken from different faces produces a frame that looks correct on both counts and cuts into open air.

**The face table** — verified on all four faces. One rule governs every row: *local Z outward, local Y along the timber toward end A, local X = Y × Z.*

| Face | Position | Axis | Angle | Quaternion | `WidthU` | `WidthV` | `DepthW` |
|---|---|---|---|---|---|---|---|
| **+X** | (`WidthX/2`, 0, `Station`) | (−1, 1, −1) | 120° | (−0.5, 0.5, −0.5, 0.5) | `WidthY` | `LengthZ` | `WidthX` |
| **−X** | (`−WidthX/2`, 0, `Station`) | (−1, −1, 1) | 120° | (−0.5, −0.5, 0.5, 0.5) | `WidthY` | `LengthZ` | `WidthX` |
| **+Y** | (0, `WidthY/2`, `Station`) | (1, 0, 0) | −90° | (−0.707, 0, 0, 0.707) | `WidthX` | `LengthZ` | `WidthY` |
| **−Y** | (0, `−WidthY/2`, `Station`) | (0, 1, −1) | 180° | (0, 0.707, −0.707, 0) | `WidthX` | `LengthZ` | `WidthY` |

Because every face satisfies the same rule, a cutter modelled in −Z cuts into the timber on every face with **no parity correction anywhere** — `WidthU` always means across the face, `WidthV` along the timber, `DepthW` into the material, so templates are portable between faces.

**Accessors** — custom properties, written by the tool, that templates read:

| Property | Meaning |
|---|---|
| `WidthU`, `WidthV` | host extents along the frame's local X, Y |
| `DepthW` | host extent behind the frame, along −Z |
| `Station` | position along the host |
| `MateWidthU`, `MateWidthV`, `MateDepthW` | the same, resolved through the mated frame — **[built]: on the joint VarSet** (as `HostWidthU … MateDepthW`, reading both datums), never on the datums themselves, because two datums reading each other is a dependency cycle |

`Station` is an **authored property**, bound to a group variable (`<<ProjectVars>>.GirtLine`) or a literal, and the frame's own `Placement` is driven from it. No `href()` is needed: an LCS has no shape derived from its properties, so this is a leaf dependency rather than the cycle that forces `href()` on a Body. `Station` cannot go stale, since the expression owns the placement.

End frames are not a separate concept — they are frames with `Station` pinned to 0 or `LengthZ` and Z along the timber axis.

**Pairing is recorded as a `MateFrame` string** (**[built]** `MateDatum`, plus `Joint` naming the joint VarSet) holding the mate's *internal Name*. `App::PropertyLink` and `App::PropertyXLink` both fail across Body boundaries (scope violation on recompute, not on assignment); expressions cross freely. The tool creates frames with explicit internal names so the string is human-readable. Mate accessors are direct named references — expressions cannot dereference a link property, and binding a mate accessor to the mate's VarSet directly would silently survive a re-pair.

**Frame placements are computed by the tool from a face identity, station and height — never typed as offset components by a human.** An attached datum's local offset axes do not map to the parent's axes as their names suggest; this has produced three separate bugs in this project (the stray 8-inch offset, findings #10, and the XWidth/YWidth error in the mate-frame test).

### 4.3 Joint template
Container-free, at document root:
- a `JointParams` VarSet — parameters in group `Joint`, UpperCamelCase, tooltips, driving everything by plain expression;
- a `PartDesign::Body` per component (cutter, adder), geometry centred on its own origin so it is symmetric about the timber axis when placed.

**Growth direction is fixed by the frame convention.** A mate frame's +Z points outward, away from the timber's material. Therefore:

| Component | Models from the body origin toward |
|---|---|
| **Adder** (tenon, tongue) | **+Z** — extends away from the timber |
| **Cutter** (mortise, housing, shoulder) | **−Z** — eats into the timber |

This holds for end frames and face frames alike, so an author can derive it rather than memorise it: model in the direction the material goes. A component modelled the wrong way lands entirely outside the timber — a cutter that removes nothing, or an adder buried inside the solid. Both produce a valid single solid and a plausible volume, so §5's assertions will not catch it; only looking at the result will. Linter: advisory warning when a component's bounding box lies wholly on the wrong side of its own origin.

No `App::Part` container: it was needed only for variant links, and a container operand makes `PartDesign::Boolean` fail in the GUI with `Tool shape is null` while passing every headless volume check.

No `href()`: parameters sit on a sibling VarSet, so expression autocomplete works and template authoring requires no Python.

**A joinery body references only the frame it is placed on** — host data through that frame's own accessors, mate data through its `Mate*` accessors, never another frame by name. Referencing the mate's frame directly gives the right numbers today and the wrong ones after a re-pair, and makes the template non-portable.

**`Mate*` accessors bind straight through** (`MateWidthU = <<mate>>.WidthU`). Never swap them to compensate for an axis flip — that masks a wrong frame rotation instead of fixing it.

### 4.4 Applying a joint
1. Copy the component. From a template file with its own VarSet, `doc.copyObject(template_body, True)` — dependencies follow, expressions remap to the copy's own VarSet. From a component already bound to a frame in the working document (re-using one end's joinery at the other, Part H1), copy **the body with its own children only**: `doc.copyObject([body] + body.Group + [body.Origin] + body.Origin.OriginFeatures, False)` — the dependency-following form drags the frame and both VarSets out of their Bodies. FreeCAD bumps the trailing serial of every copied label (`Tenon.MT.001` → `Tenon.MT.002`); match copies by type and order and relabel explicitly.
2. Re-point the component's frame references: its `Placement` (`setExpression('Placement', '<<F_Target_Frame>>.Placement')`) and every `<<F_Old>>.WidthU`-style accessor reference — one token substitution. The property editor's task panel has no whole-Placement field; use the Python console or the tool.
3. **At a Z-flipped frame (end A), mirror.** Insert a `Part::Mirroring` of the unplaced copy across its **local X** (`Base` origin, `Normal` (1, 0, 0)) and bind the *mirroring's* `Placement` to the frame instead. Under the 180°-about-Y flip this equals a mirror about the end plane, so the component keeps its timber-local x,y offsets — the decided rule (Part H2/H3 route c: one solid, exact volume, same faces at both ends). `PartDesign::Boolean` accepts the mirroring directly as an operand. For a symmetric component the mirror is a geometric no-op, so the step is unconditional rather than a user choice. In the GUI, Edit → Copy's dependency picker cannot exclude the frame and VarSets (it toggles dependencies with the selection); select the Body with its children by hand and use *Use Original Selection*.
4. Activate the timber Body → `PartDesign::Boolean`, **Cut** for a cutter, **Fuse** for an adder, operand = the copied Body (or its mirroring). The Boolean claims the operand and its dependency chain into its `Group`, so they now live inside the timber's scope: link to them from outside and FreeCAD logs an out-of-scope warning; reference them by expression and nothing happens.

The Boolean seats its operand in the **target Body's local frame**; the target's own Placement is not applied. This is why the binding uses the frame's local placement and why the joint follows the timber through arbitrary transforms. A *loose* copied body — before the Boolean — resolves globally instead, so it will appear detached whenever the timber is off the origin. That is expected, not a bug.

### 4.5 Swapping a joint
Delete the Boolean, delete the component Body, apply a different one bound to the same frame. The timber's placement, design length, section sketch, and every Assembly joint referencing its frames are untouched. Setting the Boolean's `Suppressed` instead switches the half off without deleting it — the timber returns to its bare stick volume exactly (Part H).

### 4.6 Assembly

Assembly workbench, one grounded timber, Fixed joints between tree-selected **LCS frames**. Never solid faces. The Assembly must be the *active* object or Toggle Grounded greys out.

Adders are invisible to Assembly: a fused tenon projecting past the design length seats on the frame at the design length, not on the solid's outer face. Joints hold through parameter changes and through joinery swaps.

**Joint creation is order-dependent and there is no flip control.** A Fixed joint stores `Angle` 0, `Distance` 0 and identity placements whether it seated correctly or backwards — nothing records which of the two solutions it chose. The solver converges to the solution nearest the current pose, so a 90° face move re-solves correctly while a 180° reversal lands parallel instead of antiparallel, and the only remedy is to delete the joint, park the timber near its target and re-create it.

**Therefore apply-joint pre-positions the timber before creating the joint.** The placement is exactly computable — host frame's global placement ∘ 180° flip ∘ inverse of the mate frame's local placement — after which the solver has nothing to decide.

### 4.7 Parameter groups
Instance VarSet properties bound by expression to group VarSets; groups to higher groups (instance → type → section → project, ≤3 layers). Override = replace one property's expression with a literal. Group membership *is* the binding — no hidden state.

### 4.8 Derived quantities
- **Order length** — measured from the resulting solid's extent in the timber's local frame. For angled ends, report **long point** (what a sawyer must order) and short point separately.
- **End projection** — per end, how far joinery reaches past the design solid. Replaces rev 1's typed `Stick_Allowance_FTF`, which existed to reconcile a typed length with joinery and has nothing left to reconcile.

## 5. Verification

**Mandatory assertion wherever geometry changes:** the value matches its analytic expectation; **`len(shape.Solids) == 1`**; no object outside `Up-to-date`; console silent.

The solid count is not optional. Round 3 found three distinct failure modes — a 1 mm gap in a fusion, a cutter spanning the whole section, an operand seated in the wrong frame — that each produced *exactly correct volume*, passed `isValid()` and `isClosed()`, and left every object Up-to-date. A severed timber is indistinguishable from a good joint by every other check. Solid count catches all three.

**Placement assertions must park the cutter** clear of the stick and confirm the timber returns whole. Bridges that ignore instance placement otherwise report correct volumes with the cut in the wrong place.

**Headless is a filter, not an oracle.** Round 2 passed every headless assertion and was wrong; the failure was GUI-side recompute ordering, invisible to any script. Anything touching recompute order needs a GUI check.

**Cross-Body references: expressions yes, links no.** Any tool-recorded relationship between objects in different timbers uses an internal-Name string, not a link property.

**File inspection** resolves the full placement chain (Body × datum × sketch) before interpreting coordinates. Attachment offsets are read in full; stale values hide in unexamined components.

## 6. Linter rules

**Strict** — refuse: multi-instance sketches; cross-timber dimension references; joinery referencing any timber VarSet directly (host or mate) instead of frame accessors; joinery referencing a frame other than the one it is placed on; mate accessors bound to the mate's VarSet rather than through the mate frame; link properties crossing Body boundaries; frames positioned by attachment rather than direct placement; solid-face references in sketch supports, assembly joints or dimensions; `App::Part` containers as Boolean operands; any operation yielding more than one solid; template solids invalid at default parameters.

**Advisory** — warn: naming and tooltip conventions; parameter values past caution thresholds (mortise > 35% of receiving extent); instances deviating from their group bindings; template parameter ranges containing invalid regions (see §7); unrenamed auto-labelled features; stale attachment-offset components.

## 7. Template registration

A template is validated and registered, not compiled. Registration:
1. asserts the structural rules (container-free, no `href`, one VarSet, tooltips present, single solid at defaults);
2. **sweeps every parameter across its declared range**, recording any value at which the template solid becomes invalid or splits;
3. **warns without blocking** — authors need to test in a frame to find fixes;
4. **persists the sweep result on the template** so the apply dialog can warn again when entered parameters fall in a known-bad region. Warn twice, block never.

Templates therefore declare per-property valid ranges. The roadmap's sanity bounds become the sweep domain rather than advisory guidance.

## 8. Open items

- Handedness: **closed** by Part H (2026-09-18). Applying at a Z-flipped frame mirrors the component across its local X so it keeps its timber-local offsets (§4.4 step 3); no mirrored templates, no `Template_Handed` flag, no dialog option. Would reopen only for a chiral joint that must *not* mirror. **[built]** The opposite-faces case is the same rule: each face and end carries a parity (`EndB`, `XPos`, `YPos` +; `EndA`, `XNeg`, `YNeg` −) and a component is mirrored when the target datum's parity differs from the authoring datum's — the −X face datum equals the +X one reflected through the timber's YZ plane composed with that local-X mirror. Verified by `tests/test_apply.py::test_parity_keeps_timber_local_offsets` on all four faces and both ends.
- Boolean order within a half that has both cutter and adder: order does not commute; the template must declare it. **[built]** `ComponentOrder` on each component body; Apply applies in that order, the template bar warns when a cutter follows an adder.
- Crown: a physical-stick property decided at layout, better as a per-timber drawing note than a face label.
- TechDraw units/dimensioning display (fractional inches).
- Single- vs multi-document frames at scale.
- Tree organisation at frame scale — grouping by bent/subassembly.
- `copyObject` carries a ~2.1× recompute cost against variant links (~13 objects per joint half vs 2). Accepted for authoring ergonomics; revisit only if frame-scale performance disappoints.
