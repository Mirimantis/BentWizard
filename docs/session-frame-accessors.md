# Session recipe — frame accessors, mate resolution, face move

**Status: Parts A–H complete and verified.** A–G by hand in the GUI. H run headlessly on the Part G file by `devBuildMacros/PartH_FrameAccessors.FCMacro` (27 checks, 0 failed; output in `scratch/PartH_results.md`, files `scratch/Frame Accessors Part H1.FCStd`, `Part H.FCStd`, `Part H (Xflip).FCStd`), H1 replayed by Adam in the GUI, and the H2 convention decided on 2026-09-18: **a component keeps its timber-local x,y offsets at both ends — the end-A form is the mirror (H3 route c), not a rotation.**

**Purpose.** Prove the last mechanism unknown before templates get built: that a joinery template can reference *only* its own VarSet and frame accessors, and that moving a joint to a different face requires nothing but re-placing one LCS.

**Method.** Manual GUI, macro recording on, asymmetric sections throughout so every category of error produces a distinct wrong number.

**File.** `Test_FrameAccessors.FCStd`, new document.

---

## Part A — Two timbers, deliberately asymmetric

Sections are chosen so host/mate and U/V confusions cannot cancel.

**Naming convention adopted during this session:** timber dimensions are `WidthX`, `WidthY`, `LengthZ` (always timber-local); frame accessors are `WidthU`, `WidthV`, `DepthW` (always frame-local). XYZ vs UVW makes the frame of reference unambiguous at a glance, and a template author reading `DepthW` cannot mistake it for a timber dimension.

1. `ProjectVars` VarSet at document root, group `Layout`: `GirtLine` **48**. This is the shared layout driver — the height a whole line of joints sits at, independent of any one timber or joint.
2. `TDim_Post`: `WidthX` **6**, `WidthY` **10**, `LengthZ` 96. **Section and length only** — no station, no joint data.
3. `TDim_Girt`: `WidthX` **4**, `WidthY` **8**, `LengthZ` 72.
4. Bodies `T-Post` and `T-Girt` per workflow §4.1 — section sketch on XY, centred on the origin with half-width constraints, padded to `Length`. Park the girt clear (Placement X = 40).

Every candidate value is distinct: 6, 10, 4, 8. A wrong binding is unambiguous on sight.

## Part B — Frames with accessors

5. End frames on both timbers, **Z outward at both ends**. Set `MapMode` to Deactivated and drive the Placement directly — attachment is the mechanism behind three axis bugs in this project, so it is avoided throughout this session.

   | Frame | Position | Axis | Angle | Local Z points |
   |---|---|---|---|---|
   | `F_Post_A` | (0, 0, 0) | (0, 1, 0) | 180 | global −Z, out past end A |
   | `F_Post_B` | (0, 0, `<<TDim_Post>>.LengthZ`) | — | 0 | global +Z, out past end B |
   | `F_Girt_A` | (0, 0, 0) | (0, 1, 0) | 180 | out past end A |
   | `F_Girt_B` | (0, 0, `<<TDim_Girt>>.LengthZ`) | — | 0 | out past end B |

   Drive each end frame's `Placement.z` from its own `Station` property (0 for end A, `<<TDim_Host>>.LengthZ` for end B), per the standard set out in step 6.

   **Convention: every frame's local Z points away from its host's material** — end or face, no exceptions. The material is behind the frame; the world is in front of it. A cutter is therefore always modelled in −Z and an adder always in +Z, and one template applies unmodified to either end of a stick. This retires the sign-flip that produced the Phase 0 drawbore bug.

   **The flip is 180° about local Y**, declared rather than derived. A rotation cannot send Z→−Z alone; it must flip a second axis, and Y-flip preserves local Y (a timber's "up" is more often meaningful than its "left"). Part G tests whether this is the right choice for asymmetric joinery.
6. Face frame on the post's **+Y** face: LCS `F_Post_J1`, attached to the post's XZ plane, positioned at the face and driven along the timber by `<<ProjectVars>>.GirtLine`, **Z pointing outward (+Y)**.

   **Station is an authored property on the frame — this is the standard.** Add a `Station` property to the frame, bind it to `<<ProjectVars>>.GirtLine`, and drive the frame's own `Placement.z` from `Station`. Confirmed working with autocomplete and **no `href()` required**: an LCS has no shape derived from its properties, so a placement referencing a sibling property on the same object is a leaf dependency rather than the cycle that forces `href()` on a Body.

   `Station` therefore means the same thing on every frame — where it sits along its host — and is simultaneously the input, the accessor templates read, and the anchor a group binding attaches to. It cannot go stale: the expression owns `Placement.z`, so a manual edit is overwritten.

   | Frame | `Station` bound to |
   |---|---|
   | End A | `0` |
   | End B | `<<TDim_Host>>.LengthZ` |
   | Face frame | a group variable (`<<ProjectVars>>.GirtLine`), or a literal for a one-off |

   End frames are consequently not a separate concept — they are face frames with `Station` pinned to 0 or `Length` and Z along the timber axis rather than normal to a side.

7. Add the remaining custom properties to `F_Post_J1`, group `Frame`, and bind each by expression:

   | Property | Binds to | Expected |
   |---|---|---|
   | `WidthU` | local X — across the face | `<<TDim_Post>>.WidthX` → **6** |
   | `WidthV` | local Y — along the timber | `<<TDim_Post>>.LengthZ` → **96** |
   | `DepthW` | local −Z — into the material | `<<TDim_Post>>.WidthY` → **10** |
   | `Station` | `<<ProjectVars>>.GirtLine` | **48** |
   | `HostLength` | `<<TDim_Post>>.LengthZ` | **96** |

   The definition that holds for every frame: **`WidthU`/`WidthV` are the host's extents along the frame's own local X and Y; `DepthW` is the host's extent behind the frame along −Z.** On an end frame both in-plane axes are section directions and `DepthW` is the stick length; on a face frame one in-plane axis runs along the timber and `DepthW` is the through-section dimension. The asymmetry is real, not a defect — a mortise needs the host's `DepthW` and the mate's `WidthU`/`WidthV`.

   For a +Y face the through-dimension is `YWidth`; `WidthU`/`WidthV` are `XWidth` and `Length`-direction respectively. **Record the actual mapping you find rather than assuming mine** — this is the axis trap that has bitten three times, and the point of the test is to find out what the frame's local axes really are, not to confirm a guess.

8. Same accessors on `F_Girt_B` (host = girt). Note that an end frame's `DepthW` is the **whole stick** — the material behind it runs the full length — not a section dimension:

   | Property | Binds to | Expected |
   |---|---|---|
   | `WidthU` | `<<TDim_Girt>>.WidthX` | **4** |
   | `WidthV` | `<<TDim_Girt>>.WidthY` | **8** |
   | `DepthW` | `<<TDim_Girt>>.LengthZ` | **72** |
   | `Station` | `<<TDim_Girt>>.LengthZ` | **72** |
   | `HostLength` | `<<TDim_Girt>>.LengthZ` | **72** |

   Three properties reading 72 for three different reasons is a hint of redundancy in the accessor set: `DepthW` and `HostLength` diverge only on a face frame. Record whether any template in Part C actually needs `HostLength`; if none does, drop it and keep `DepthW`.

9. **Pairing reference — use a string, not a link.** Add a property `MateFrame` of type **`App::PropertyString`** to each of `F_Post_J1` and `F_Girt_B`, holding the *internal Name* of the other frame (e.g. `"LCS004"`, `"LCS001"`).

   **Confirmed the hard way:** neither `App::PropertyLink` nor `App::PropertyXLink` works here. Each frame lives inside its own timber Body, and a link cannot cross a GeoFeatureGroup boundary — assigning one appears to succeed, then throws on the next recompute (`Link(s) to object(s) … go out of the allowed scope`) and corrupts the frame's own origin references. Expressions, by contrast, cross Body boundaries freely. **Cross-Body references: expressions yes, links no.**

   Internal Names, not Labels — Names are immutable, Labels are user-editable. In production the tool creates frames with an explicit name via `addObject`, so the stored value reads `"F_Post_J1"` rather than `"LCS004"`: stable *and* human-readable, which the graceful-degradation requirement wants.

   Mate accessors are direct named references — expressions cannot dereference a link property in any case (the expression editor exposes a linked object's geometric children, not its custom properties):

   | Property on `F_Post_J1` | Expression | Expected |
   |---|---|---|
   | `MateWidthU` | `<<F_Girt_B>>.WidthU` | 4 |
   | `MateWidthV` | `<<F_Girt_B>>.WidthV` | 8 |
   | `MateDepthW` | `<<F_Girt_B>>.DepthW` | 72 |
   | `MateLength` | `<<F_Girt_B>>.HostLength` | 72 |

   **Never bind a mate accessor to the mate's VarSet directly** (`<<TDim_Girt>>.LengthZ`). It resolves to the same number today and silently keeps reporting the old timber after a re-pair. Route everything through the mate frame.

   `MateDepthW` on a mortise frame resolves to the tenon-bearing stick's length, which is unlikely to be useful. Record whether any template needs it — `MateDepthW` and `MateLength` may be as redundant as their host-side counterparts.

**Checkpoint B — PASSED.** All accessors resolved exactly as predicted: face frame 6 / 96 / 10 / 48 / 96, end frame 4 / 8 / 72 / 72 / 72, mate set 4 / 8 / 72 / 72. `F_Post_J1` placement (0, 5, 48) with q = (0.707, 0, 0, −0.707); end-A frames carry the 180°-about-Y flip as declared.

Outstanding from Part B, deferred deliberately: `F_Post_A`, `F_Post_B` and `F_Girt_A` carry no accessors. Acceptable for this test; in production every frame carries the full set so any frame can host joinery. Any that don't: record what they *did* resolve to, since a wrong value here identifies the real axis mapping.

## Part C — Joinery bound only to accessors

9. VarSet `J-MT-001`, group `Joint`: `HousingDepth` 0.5, `TenonLength` 4, `MortiseThickness` 2, `Fit` 0.0625.
10. Body `Mortise.MT.001`, modelled from its own origin in **−Z** (cutter):
    - housing block: `<<F_Post_J1>>.MateWidthU` × `<<F_Post_J1>>.MateWidthV` × `<<J-MT-001>>.HousingDepth`
    - mortise prism: `MortiseThickness` × (`MateWidthV` − 2 in) × (`TenonLength` + 0.25 in)
    - **No reference to any timber VarSet, either side.**
11. Body `Tenon.MT.001`, modelled in **+Z** (adder): section (`MortiseThickness` − `Fit`) × (`MateWidthV` − 2 in − `Fit`) referencing `F_Girt_B`'s accessors, length `TenonLength`.
12. Bind placements via the Python console:
    ```python
    App.ActiveDocument.getObjectsByLabel('Mortise.MT.001')[0].setExpression('Placement', '<<F_Post_J1>>.Placement')
    App.ActiveDocument.getObjectsByLabel('Tenon.MT.001')[0].setExpression('Placement', '<<F_Girt_B>>.Placement')
    App.ActiveDocument.recompute()
    ```
13. Booleans: activate `T-Post` → Cut with `Mortise.MT.001`; activate `T-Girt` → Fuse with `Tenon.MT.001`.

**Checkpoint C.** The housing is 4 × 8 (the girt's section), not 6 × 10. Verify by measurement, not by eye. Assert a single solid on both timbers.

## Part D — Assembly and the durable joint

14. Create assembly, add both timbers, ground `T-Post`, Fixed joint `F_Girt_B` ↔ `F_Post_J1`.
15. Seat it, clipping-plane check.

**Checkpoint D.** Tenon seated in mortise, shoulder on the housing floor.

## Part E — Section change propagation

16. Change `TDim_Girt.XWidth` from 4 to 5. Expect: girt section changes, **housing width follows to 5**, tenon adjusts, assembly holds.
17. Change `TDim_Post.YWidth` from 10 to 12. Expect: post gets deeper, **housing is unchanged** (it belongs to the girt), frame re-places to the new face, joinery follows, assembly holds.

18. Change `ProjectVars.GirtLine` from 48 to 60. Expect: the frame rides up the post, the mortise and housing follow, the girt follows in the assembly, and **no joint or timber parameter is touched**. This is the layered-groups payoff on a single joint; at frame scale it is what moves a whole loft line at once.

**Checkpoint E.** Host and mate dimensions are genuinely independent, and layout drives station without touching either. This is what the asymmetric sections were for — if the housing tracked the post, it would be visible immediately.

## Part F — The face move

19. Re-place `F_Post_J1` from the post's **+Y** face to its **+X** face: change the attachment support to the YZ plane and update the offset expressions, keeping Z outward.
20. Recompute. Change **nothing** on the joinery bodies or `J-MT-001`.

**Checkpoint F — the decisive one.** Expected: the mortise and housing move to the +X face; the housing stays 5 × 8 (still the girt's section, unchanged by the move); `Depth` now resolves to `XWidth` (6) instead of `YWidth` (12); the Assembly joint holds and the girt swings to the new face.

Record exactly what had to be edited. If only the frame's attachment and offsets changed, the frame-relative design is proven. If any joinery expression needed rewriting, note which and why — that is the finding.

## Part G — Frame Z on all four faces

21. Build three more face frames on the post, one per remaining face (`−Y`, `−X`, and one more at a different station), each with Z outward.
22. For each, record the resolved rotation and whether a cutter modelled in −Z cuts *into* the timber without any parity correction.

**Checkpoint G1.** If all four faces behave identically with no 180° correction, the `FACES` flip_z parity machinery in the current workbench becomes unnecessary rather than needing porting. That is a significant deletion — verify carefully rather than optimistically.

## Part H — End-agnostic templates and the handedness convention

23. Copy `Tenon.MT.001` and bind the copy's Placement to `F_Girt_A`. Fuse it into `T-Girt`. **Change nothing else.** A tenon should appear at end A, mirroring the one at end B.

**Checkpoint H1.** One template, both ends, no edits. If this holds, tie beams and any double-ended member need a single joinery authoring rather than two.

24. Now the handedness test. Build a deliberately **asymmetric** adder — a tenon offset toward one face, e.g. its centre displaced 1 in in local +X — and apply it at both ends of the girt from the same template.
25. Observe which face each tenon favours at each end.

**Checkpoint H2.** With the declared 180°-about-local-Y convention, the two tenons will favour *opposite* faces of the girt. Decide whether that is what a framer wants:

- If yes, the convention stands as declared.
- If no, test 180° about local X instead and record which produces the wanted result.
- If the answer is "it depends on the joint," then handedness cannot be a global convention and must be a per-template declaration — which is the open handedness item resolving itself, and worth knowing now rather than after a library encodes the wrong default.

Record the finding either way; this decides a rule that every future template inherits.

---


---

## Verified results, Parts C–G

### Checkpoint C — PASSED
Joinery built referencing only frame accessors and `J-MT-001`. The housing sized itself from the **girt's** section via `MateWidthU`/`MateWidthV`, not the post's — the frame is genuinely the sole interface between timber and joinery.

Parameter refinements made during the build, adopted:
- **No lateral fit allowance on a tenon.** Cheeks must be tight; `Fit` was repurposed as `MortiseFit`, extra *depth* so the shoulder seats rather than the tenon tip bottoming out.
- **Mortise depth includes the housing depth** (`TenonLengthZ + HousingDepth + MortiseFit`), so the mortise is measured from the housing floor rather than the timber face. Tenon pad is `TenonLengthZ + HousingDepth` to match.

Bug found and fixed: the shoulder sketch on the *girt's* body was bound to `<<F_Post_J1>>.MateWidthU` — right numbers, wrong path. Corrected to `<<F_Girt_B>>.WidthU`.

**Strict rule adopted: joinery references only the frame it is placed on.** Host data via that frame's own accessors, mate data via that frame's `Mate*` accessors, never another frame by name.

### Checkpoint D — PASSED
Frames coincident and antiparallel, tenon seated, ¼" relief at the tip and none at the cheeks. Grounding requires the Assembly to be the **active** object — the command greys out otherwise.

### Checkpoint E — PASSED
Host and mate dimensions independent: changing the girt's section moved the housing, changing the post's did not. `ProjectVars.GirtLine` moved the entire joint up the post with no joint or timber parameter touched.

### Checkpoint F — PASSED after correction
The intuitive 90°-about-Y rotation is **wrong**. Keeping `WidthU` meaning "across the face" and `WidthV` "along the timber" on every face requires a 120° rotation about a diagonal axis — not something derived by hand. Three host accessors also had to be rebound; `Mate*` bindings must stay direct (`MateWidthU = <<mate>>.WidthU`), never swapped to compensate for an axis flip.

### Checkpoint G — PASSED, all four faces

**The face table, verified empirically. This is the tool's complete specification for frame generation.**

| Face | Position | Axis | Angle | Quaternion | `WidthU` | `WidthV` | `DepthW` |
|---|---|---|---|---|---|---|---|
| **+X** | (`WidthX/2`, 0, `Station`) | (−1, 1, −1) | 120° | (−0.5, 0.5, −0.5, 0.5) | `WidthY` | `LengthZ` | `WidthX` |
| **−X** | (`−WidthX/2`, 0, `Station`) | (−1, −1, 1) | 120° | (−0.5, −0.5, 0.5, 0.5) | `WidthY` | `LengthZ` | `WidthX` |
| **+Y** | (0, `WidthY/2`, `Station`) | (1, 0, 0) | −90° | (−0.707, 0, 0, 0.707) | `WidthX` | `LengthZ` | `WidthY` |
| **−Y** | (0, `−WidthY/2`, `Station`) | (0, 1, −1) | 180° | (0, 0.707, −0.707, 0) | `WidthX` | `LengthZ` | `WidthY` |

All four satisfy one rule: **local Z outward, local Y along the timber toward end A, local X = Y × Z.**

**Parity machinery is deleted, not ported.** A cutter modelled in −Z cut correctly into the timber on every face, with no flip correction anywhere.

**Rotation and position must come from the same table row.** A frame carrying the −X rotation at the +X position looks plausible — correct-looking face, correct-looking orientation — and cuts into open air. Only the pair identifies the face.

**Assembly joints have no flip control, and creation is order-dependent.** The Fixed joint stores `Angle` 0, `Distance` 0 and identity placements in *both* the correct and incorrect states; nothing records which solution was chosen. The solver converges to the solution nearest the current pose, so a 90° face move re-solves correctly while a 180° reversal lands parallel instead of antiparallel — and the only remedy found was deleting the joint, parking the timber near its target, and re-creating it.

**Consequence for the tool: apply-joint must pre-position the timber before creating the Fixed joint.** The exact placement is computable — host frame's global placement ∘ 180° flip ∘ inverse of the mate frame's local placement — after which the solver has nothing to decide. This replaces the parity tables with a small deterministic step.

## Verified results, Part H

Method differs from A–G: a script performs the steps on a copy of the Part G file, measures the solids, and prints the tables below (`devBuildMacros/PartH_FrameAccessors.FCMacro`, runnable under `freecadcmd.exe` or from the Macro menu). All measurements are girt-local, read from `T-Girt`'s tip shape; "tenon centre" is the centroid of the fused solid sliced between the shoulder and the tenon tip. Every step checked one solid, the analytic volume (stick 47,194,744.320 mm³, adder 64.0000 in³ = 1,048,772.096 mm³), nothing left Touched/Invalid, and a silent console. The assembly solver ran on every recompute (MbD convergence lines, headless) and the Fixed joint's references and `T-Girt`'s seated pose never changed.

### H0 — accessors on `F_Girt_A` (Part B's deferred item)

| Frame | `WidthU` | `WidthV` | `DepthW` | `Station` | `HostLength` | Position | Rotation |
|---|---|---|---|---|---|---|---|
| `F_Girt_A` | 5 | 8 | 72 | 0 | 72 | (0, 0, 0) | (0, 1, 0), 180° |
| `F_Girt_B` | 5 | 8 | 72 | 72 | 72 | (0, 0, 1828.8) | identity |

Same mapping as `F_Girt_B` (`WidthU = WidthX`, `WidthV = WidthY`): the Y-flip negates local X, and an extent has no sign. `Station` 0 as a literal, driving `Placement.z`.

### Checkpoint H1 — PASSED

`Tenon.MT.001` copied, the copy's `Placement` re-bound to `<<F_Girt_A>>.Placement`, fused into `T-Girt`. Nothing else edited.

| Measure | Expected | Observed |
|---|---|---|
| loose copy bbox z | [−127, 0] | [−127.000, 0.000], centre (0, 0, −63.5) |
| loose copy volume | = end-B adder | 1,048,772.096 = 1,048,772.096 |
| `T-Girt` after fuse | 1 solid, stick + 2 adders, z [−127, 1955.8] | 1 solid, 49,292,288.512 mm³, z [−127.000, 1955.800] |
| tenon slice centre / volume, end A | (0, 0) | (0.000, −0.000), 354,579.936 mm³ |
| tenon slice centre / volume, end B | (0, 0) | (0.000, −0.000), 354,579.936 mm³ |

**One authoring, both ends, no edits.** The copy still read `<<F_Girt_B>>.WidthU/WidthV` for its shoulder (right numbers, wrong path — the Part C bug in reverse). **H1b**, the strict form: those two constraint expressions re-pointed to `<<F_Girt_A>>`; volume and bbox bit-identical afterwards. So the complete edit list for moving a component to another frame is **its `Placement` expression plus its accessor references** — three expressions here, all the same token substitution.

**The copy recipe.** `copyObject(body, True)` is unusable: it dragged `F_Girt_B` out of `T-Girt` (as `F_Girt_B001`), the joint VarSet (as `J-MT-002`) and `TDim_Girt` (as `TDim_Girt001`). What works is the body with its own children and nothing else:

```python
doc.copyObject([body] + body.Group + [body.Origin] + body.Origin.OriginFeatures, False)
```

13 objects; FreeCAD remaps `Tip`, `Origin` and the sketches' attachment supports into the copy, and every expression naming the frame or the joint VarSet keeps naming the original. FreeCAD keeps labels unique by **bumping the trailing digit run** (`Tenon.MT.001` → `Tenon.MT.002`, `J-MT-001` → `J-MT-002`), so a tool must match copies by type and order, never by label prefix, and must relabel explicitly.

**GUI replay (Adam, 2026-09-18) — H1 confirmed.** Edit → Copy on the Body opens FreeCAD's dependency picker, but it checks and unchecks dependencies *together with* the selected items, so the frame and VarSets cannot be excluded there. What works: expand the Body in the tree, select the Body with its sketches, pads and Origin by hand, Copy, and choose **Use Original Selection**. The pasted body re-bound to `F_Girt_A` in the console seated correctly with **no manual recompute**; the Fuse picked it up at once. So a framer *can* do this from stock FreeCAD, but only knowing the trick — the tool should own the copy.

### Checkpoint H2 — DECIDED: same timber-local offsets at both ends; the end-A form is a mirror

Asymmetric adder: the tenon centre displaced (+1 in, +½ in) in the component's own X, Y (distinct magnitudes, so the two axes cannot be confused). Applied at both ends from the same body, `F_Girt_A` under the declared flip and then under the alternative.

| `F_Girt_A` flip | end B tenon centre | end A tenon centre | end B favours | end A favours |
|---|---|---|---|---|
| 180° about local **Y** (declared) | (+1, +½) | (**−1**, +½) | +X / +Y | **−X** / +Y |
| 180° about local **X** (alternative) | (+1, +½) | (+1, **−½**) | +X / +Y | +X / **−Y** |

One solid and the full volume in both cases; `F_Girt_A`'s accessors read the same under either flip. The file is saved in the Y-flip state; `Part H (Xflip).FCStd` holds the alternative.

**Reading.** A rigid rotation that sends Z to −Z must flip exactly one in-plane axis. The Y-flip preserves the Y face and swaps the X faces; the X-flip does the opposite. **No choice of flip axis gives "same faces at both ends"** — that is a mirror, which no rotation is. So the H2 question splits: the flip axis is a *frame* convention that decides which in-plane axis a plain rotation preserves, and handedness is a separate mechanism (H3).

**Decision (Adam, GUI, 2026-09-18).** Looking at the Y-flip file: *"The tenons should have the same offset in the timber's local x and y. In this file, that should result in the same position in world X and Z, but pointing in opposite directions in world Y."* That is the mirror, and it is the rule: **a component applied at end A keeps its timber-local x,y offsets**, produced by mirroring across the frame's local X before placing on the frame (H3 route c). It is not an option a user picks; it is what applying at the flipped end means. The frame convention stays 180° about local Y as declared — with the mirror rule it no longer affects end joinery at all, and it still fixes what `WidthU`/`WidthV` mean on face frames and how the Assembly mates. The saved `Part H.FCStd` now carries this state (route c active at end A, the rotated end-A adder kept but suppressed); measured world-frame tenon centres are A (−25.4, −1123.95, 1536.7) and B (−25.4, 857.25, 1536.7): same X and Z, apart only along the girt.

Untested and left open: the analogous rule for a template moved between *opposite faces* of a post (Part G proved the cutter direction, not the fate of an offset). The previously imagined per-template hand flag has no case left unless a chiral joint turns up that must *not* mirror.

### H3 — native mirror probe (added at Adam's request)

| Route | What | Accepted by `PartDesign::Boolean`? | Result at end A |
|---|---|---|---|
| — | `Part::Mirroring` of an unplaced copy about its XY plane | — | grows −Z, tenon still at (+1, +½): a mirror keeps the faces |
| (a) | that mirroring **directly** as the Boolean operand | **yes** — Up-to-date, one solid, exact volume | (+1, +½) |
| (b) | a Body with `BaseFeature` = the mirroring, as operand | yes — one solid, exact volume | (+1, +½) |
| (c) | mirroring across the copy's **local X** (YZ plane), its `Placement` bound to `<<F_Girt_A>>.Placement` like any component | **yes** — one solid, exact volume | **(+1, +½) — same faces as end B** |

Route (c) is the form a tool would use: under the Y-flip, `F_A ∘ mirror_X` equals a mirror about the end plane, so a handed component is *placed on the frame exactly like an unhanded one* with one extra native object in front of it. Nothing about ends is special-cased, and the Fixed joint is untouched.

Two scope observations from (a)/(b): **`PartDesign::Boolean` claims its operand and the operand's dependency chain into its `Group`** (route (a)'s Boolean holds both the mirroring and its source body), which puts them inside the timber Body and therefore inside the Assembly's scope; a root-level `Part::Mirroring` or Body that then *linked* to one of them logged `Link(s) … go out of the allowed scope … reside within 'Assembly'` — it still computed, but it is the same boundary as finding 3. Each route was given its own template copy to keep the runs clean. Expressions, as always, crossed freely.

Also confirmed in passing: **`Suppressed = True` on a fuse Boolean returns the girt to the bare stick** (volume exact) — a joint half can be switched off without deleting anything.

## Findings so far (Parts A–H)

1. **Station works as an authored property on a frame, no `href()` needed.** An LCS has no shape derived from its properties, so a placement referencing a sibling property on the same object is a leaf dependency, not the cycle that forces `href()` on a Body. Autocomplete works. Adopted as standard.
2. **Frames should never be positioned by attachment.** Direct placement with `MapMode` Deactivated is predictable; attached-datum axis mapping has caused three separate bugs in this project.
3. **Cross-Body references: expressions yes, links no.** `App::PropertyLink` and `App::PropertyXLink` both fail across Body boundaries. Scope violations surface on recompute, not on assignment, so the first assignment looks successful.
4. **Expressions cannot dereference through a link property.** The editor exposes a linked object's geometric children, not its custom properties.
5. **Naming: XYZ for timber-local, UVW for frame-local.** `WidthX`/`WidthY`/`LengthZ` vs `WidthU`/`WidthV`/`DepthW`.
6. **Accessor redundancy confirmed.** No template built in Part C used `HostLength` or `MateLength`; on an end frame `DepthW`, `Station` and `HostLength` all resolve to the stick length. Candidates for removal once more templates exist.
7. **Frames must be tool-generated, never hand-placed.** Two separate failures in Parts F and G came from a human setting five placement fields: the non-obvious 120° diagonal rotations, and a rotation/position pair taken from different faces. The tool holds the four-row face table and the user picks a face from a list.
8. **Assembly joint creation is order-dependent** and has no flip control; the tool pre-positions the timber, then creates the joint.
9. **One template applies unmodified to both ends** (H1). Re-targeting a component to another frame is a token substitution over three expressions: its `Placement` and its two accessor references. Nothing about the geometry knows which end it is on.
10. **Copy a component as `[body, *Group, Origin, *OriginFeatures]` with `with_dependencies=False`.** The dependency-following form drags the frame and both VarSets out of their homes. FreeCAD bumps the trailing serial of every copied label for uniqueness, so copies are matched by type and order and relabelled explicitly.
11. **The flip axis is not a handedness mechanism.** Any rigid Z→−Z flip preserves exactly one in-plane axis and swaps the other (Y-flip: same Y face, opposite X faces; X-flip: the reverse). "Same faces at both ends" is a mirror and no rotation produces it. The frame convention stays 180° about local Y as declared.
12. **Applying at end A means mirroring (decided).** A component keeps its timber-local x,y offsets at both ends. Mechanism: `Part::Mirroring` of the unplaced copy across its local X, the mirroring's `Placement` bound to the frame like any component; `PartDesign::Boolean` accepts the mirroring directly as an operand. This is the rule, not a user option, and it retires rev 2 §8's three handedness options and the old `Template_Handed` flag; only a chiral joint that must *not* mirror would reopen it.
12a. **The GUI dependency picker cannot exclude dependencies** — it toggles them with the selection. Hand-select the Body with its children and use *Use Original Selection*. The tool should own the copy.
13. **`PartDesign::Boolean` claims its operand, and the operand's dependency chain, into its `Group`**, moving them inside the timber Body's (and Assembly's) scope. A root-level *link* into that scope logs an out-of-scope warning; expressions are unaffected.
14. **The Assembly solver runs headless** (MbD convergence on every `recompute()`), so headless checks can assert a seat is undisturbed — as they did here.
15. **Suppressing a Boolean switches a joint half off cleanly**; the timber returns to its bare stick volume.

## Report

Per checkpoint: pass/fail, observed values, and anything that needed manual correction. In particular:

- the real axis mapping for the face frame (Part B);
- whether station works as an authored property or must be a derived accessor (Part B step 6);
- what had to be edited for the face move (Part F);
- whether parity correction is needed on any face (Part G);
- whether one template applies unmodified to both ends (Part H1) — **yes**; the re-target is a token substitution over `Placement` and the accessor references (finding 9);
- what the 180°-about-local-Y convention does to asymmetric joinery, and whether handedness can be global or must be per-template (Part H2) — **opposite X faces, same Y face**; no flip axis can do better. Decided: applying at end A *means* the mirror (same timber-local offsets at both ends), a native per-component `Part::Mirroring`, proven in H3 and now the saved state of `Part H.FCStd` (findings 11–12). Neither a global rotation convention nor a per-template flag is needed.

Part H is closed. The `.FCStd` files and the driving macro are in `scratch/` and `devBuildMacros/`. Rev 4 of the roadmap can be written against proven behaviour rather than intended behaviour.
