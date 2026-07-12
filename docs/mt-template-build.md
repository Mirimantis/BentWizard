# Building `library/Joint_HousedMT.FCStd` — step-by-step

The first clean joint template: a housed, pegged, drawbored mortise &
tenon between a post (mortise role) and a beam (tenon role). This is the
Phase 0 recipes (§4.4, §4.6, §4.7) rebuilt from scratch with the decided
conventions and the §4.3 junction-point rule. Values below are imperial;
enter them per your FreeCAD unit schema (e.g. "Building US" handles
fractional inches natively). The workbench defers to the user's unit
schema — imperial here is example data, not a requirement.

**Acceptance:** `python -m freecad.bentwizard.linter library/Joint_HousedMT.FCStd`
reports **zero strict findings** and no advisories other than
`caution-threshold` (parameter-value cautions are apply-time concerns,
not template defects). Lint after each part — checkpoints below.

Template-wide conventions:

- Bent number `0` marks template placeholders: bodies `P0-1` / `B0-1`,
  joint ID `MT_0a`. The Apply-Joint tool rewrites these on apply.
- Base (non-joint) features: `MemberID_SectionSketch`, `MemberID_Stick`.
- Pick every attachment reference **from the model tree, never the 3D
  view** (finding #8), and never a solid face.
- One hand only. The mirrored-hand setback (§4.6) and the end-B drawbore
  sign flip (§4.7) are computed by the tool at apply time — do not model
  them here.

---

## Part A — the two timbers (§4.1)

For each timber, in an empty document saved as `library/Joint_HousedMT.FCStd`:

1. **VarSet** labeled `TimberDims_P0-1`, properties in group `Dims`, all
   `App::PropertyLength`. The post is 10×8, the beam 6×8 — differing
   sections make the two timbers and their orientations readable in the
   3D view and surface edge cases that identical sections hide.

   | Property | Post | Beam | Tooltip |
   |---|---|---|---|
   | `Width`  | 10 in | 6 in | Section extent along local X, measured from reference Face 2 (the YZ origin plane). |
   | `Depth`  | 8 in  | 8 in | Section extent along local Y, measured from reference Face 1 (the XZ origin plane). |
   | `Length` | 96 in | 96 in | Stick length from end A (Z=0) to end B, including tenons, etc. |

2. **Body** labeled `P0-1`.
3. **Sketch** on the body's `XY_Plane` (tree-selected), labeled
   `P0-1_SectionSketch`: rectangle in the first quadrant, one corner
   coincident with the origin, horizontal dimension `= <<TimberDims_P0-1>>.Width`,
   vertical `= <<TimberDims_P0-1>>.Depth`.
4. **Pad** labeled `P0-1_Stick`, Length `= <<TimberDims_P0-1>>.Length`.

Repeat for the beam: `TimberDims_B0-1` (beam column above, same
tooltips), body `B0-1`, `B0-1_SectionSketch`, `B0-1_Stick`.

Tooltip style: as brief as possible while still informative — always
state the face/end the value measures from; use timber framing
terminology.

**Checkpoint A:** lint — expect only `missing-tooltip`/naming silence,
i.e. no findings at all yet.

---

## Part B — the joint VarSet (§4.3)

One **VarSet** labeled `Joint_MT_0a`, properties in group `Joint`.
`Peg_Count` is `App::PropertyInteger`; all others `App::PropertyLength`.

| Property | Value | Tooltip |
|---|---|---|
| `Joint_Station` | 48 in | Distance from the post's end A (Z=0) to the underside of the housing, along the post's length. |
| `Housing_Width` | *expression* `= <<TimberDims_B0-1>>.Width` | Horizontal opening of the housing across the post face; tracks the beam's Width. Override with a literal to hold the housing off the beam size. |
| `Housing_Height` | *expression* `= <<TimberDims_B0-1>>.Depth` | Vertical opening of the housing along the post; tracks the beam's Depth. Override with a literal to hold the housing off the beam size. |
| `Housing_Depth` | 1/2 in | Depth of the housing into the post, measured from the post face opposite reference Face 2. |
| `Tenon_Thickness` | 2 in | Tenon thickness, measured from the tenon's setback plane off the beam's reference Face 2. |
| `Tenon_Width` | 6 in | Tenon width, measured from the tenon's setback plane off the beam's reference Face 1. |
| `Tenon_Length` | 4 in | Tenon length from the beam's end A to the shoulder plane. |
| `Tenon_Setback_Face1` | 1 in | Tenon setback from the beam's reference Face 1 (XZ origin plane). |
| `Tenon_Setback_Face2` | 2 in | Tenon setback from the beam's reference Face 2 (YZ origin plane). |
| `Mortise_Relief` | 1/4 in | Extra mortise depth beyond Tenon_Length, so the tenon never bottoms out. |
| `Peg_Diameter` | 1 in | Diameter of the peg bore, both halves. |
| `Peg_Setback` | 2 in | Peg centerline distance from the bearing plane, into the post (true position on the post bore). |
| `Peg_Drawbore_Offset` | 3/32 in | Drawbore: the tenon bore is displaced this much toward the shoulder relative to true position. |
| `Peg_Count` | 1 | Number of pegs in this joint, for the hardware schedule. Not geometry. |

Soft convention (decided during this build): **Width reads horizontal
and Depth vertical in a member's installed orientation** where
applicable — so the 6×8 beam lands on edge, Width 6 across, Depth 8
tall. Not a hard rule (timbers meet in many orientations), but hold to
it wherever it applies.

Rename the VarSet immediately after creating it — a missed rename is
exactly what the linter's naming/auto-label advisories catch.

**Checkpoint B:** lint — still zero findings (the VarSet-to-Dims
bindings are the sanctioned junction pattern; the linter exempts them).

---

## Part C — mortise side, on `P0-1` (§4.6 + §4.7)

1. **Datum plane** labeled `P0-1_BearingPlane_MT_0a`: attach FlatFace to
   the post's `YZ_Plane` (from the tree), attachment offset in Z
   `= <<TimberDims_P0-1>>.Width - <<Joint_MT_0a>>.Housing_Depth`.
   Leave every other offset component zero.
2. **Housing.** Sketch `P0-1_HousingSketch_MT_0a` on that datum:
   rectangle —
   - vertical position of the bottom edge `= <<Joint_MT_0a>>.Joint_Station`
   - vertical extent `= <<Joint_MT_0a>>.Housing_Height`
   - horizontal extent `= <<Joint_MT_0a>>.Housing_Width`
   - horizontal position: centered on the post — constrain the rectangle's
     left edge `= (<<TimberDims_P0-1>>.Depth - <<Joint_MT_0a>>.Housing_Width) / 2`
     from the sketch origin (own Dims + joint VarSet only — legal).
   **Pocket** `P0-1_Housing_MT_0a`, direction outward (toward the removed
   face), Length `= <<Joint_MT_0a>>.Housing_Depth`. Toggle Reversed if it
   grows into the stick — verify with a side orthographic view, not
   wireframe (§5).
3. **Mortise.** Sketch `P0-1_MortiseSketch_MT_0a` on the same datum:
   rectangle —
   - horizontal position from the housing's left edge
     `+ <<Joint_MT_0a>>.Tenon_Setback_Face2`, extent `= <<Joint_MT_0a>>.Tenon_Thickness`
   - vertical position `= <<Joint_MT_0a>>.Joint_Station + <<Joint_MT_0a>>.Tenon_Setback_Face1`,
     extent `= <<Joint_MT_0a>>.Tenon_Width`
   **Pocket** `P0-1_Mortise_MT_0a`, direction inward,
   Length `= <<Joint_MT_0a>>.Tenon_Length + <<Joint_MT_0a>>.Mortise_Relief`.
4. **Peg bore.** Sketch `P0-1_PegBoreSketch_MT_0a` on the post's
   `XZ_Plane` (tree-selected, zero offset — datum strategy): one circle —
   - center along the post `= <<Joint_MT_0a>>.Joint_Station + <<Joint_MT_0a>>.Tenon_Setback_Face1 + <<Joint_MT_0a>>.Tenon_Width / 2`
   - center across the post `= <<TimberDims_P0-1>>.Width - <<Joint_MT_0a>>.Housing_Depth - <<Joint_MT_0a>>.Peg_Setback`
   - diameter `= <<Joint_MT_0a>>.Peg_Diameter`
   **Hole** `P0-1_PegBore_MT_0a`: Through all, diameter
   `= <<Joint_MT_0a>>.Peg_Diameter`.

**Checkpoint C:** lint — expect zero strict; `caution-threshold` on the
mortise (`Tenon_Width` = 75% of an 8×8) is expected and acceptable.

---

## Part D — tenon side, on `B0-1` (§4.4 + §4.7)

1. **Tenon (island pocket).** Sketch `B0-1_TenonSketch_MT_0a` on the
   beam's `XY_Plane` (end A): two loops —
   - outer rectangle = the full section, corner at origin,
     `= <<TimberDims_B0-1>>.Width` × `= <<TimberDims_B0-1>>.Depth`
   - inner rectangle: from `= <<Joint_MT_0a>>.Tenon_Setback_Face2` (X) and
     `= <<Joint_MT_0a>>.Tenon_Setback_Face1` (Y), extents
     `= <<Joint_MT_0a>>.Tenon_Thickness` × `= <<Joint_MT_0a>>.Tenon_Width`.
   Both setbacks are > 0, so the island stays strictly interior
   (finding #14) — the linter checks this.
   **Pocket** `B0-1_Tenon_MT_0a`, Length `= <<Joint_MT_0a>>.Tenon_Length`.
2. **Shoulder datum** `B0-1_ShoulderA_MT_0a`: FlatFace on the beam's
   `XY_Plane`, offset Z `= <<Joint_MT_0a>>.Tenon_Length`. (Assembly
   references land here, §4.8.)
3. **Drawbore peg bore.** Sketch `B0-1_PegBoreSketch_MT_0a` on the beam's
   `YZ_Plane` (zero offset): **one circle** (one sketch per instance —
   debt 2) —
   - center along the beam `= <<Joint_MT_0a>>.Tenon_Length - <<Joint_MT_0a>>.Peg_Setback + <<Joint_MT_0a>>.Peg_Drawbore_Offset`
   - center across `= <<Joint_MT_0a>>.Tenon_Setback_Face1 + <<Joint_MT_0a>>.Tenon_Width / 2`
   - diameter `= <<Joint_MT_0a>>.Peg_Diameter`
   **Hole** `B0-1_PegBore_MT_0a`: Through all, diameter
   `= <<Joint_MT_0a>>.Peg_Diameter`.

**Checkpoint D:** lint — same as C plus nothing new strict.

---

## Part E — inspection pose and verification

1. Set `B0-1`'s Body Placement so the beam sits as-assembled — tenon
   entering the mortise (finding #7a). Body Placement is display-only
   here; it does not affect the feature tree or the linter.
2. Verify per §5: top/side orthographic views, a clipping plane through
   the joint, Measure between the tenon cheek and mortise wall (expect
   0 engaged, `Mortise_Relief` at the bottom).
3. Parametric shakedown: change `TimberDims_B0-1.Depth` to 10 in — the
   housing must widen; change `Joint_Station` — everything on both
   timbers must travel together; change `Tenon_Thickness` — mortise and
   tenon must move in lockstep. Undo all (or close without saving and
   re-verify defaults).
4. Final lint + run the test suite. Then commit the template.

When this file is in `library/` and green, I'll add it as a third test
fixture (template-must-stay-clean regression) and we move to the
"New Timber from template" command.
