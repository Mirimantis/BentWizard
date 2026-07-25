# Building `library/Joint_BraceMT.FCStd` — step-by-step

Mortise & tenon for a vertical diagonal — knee braces and struts. The
brace's end is cut at `Brace_Angle` (default 45°) so its oblique
shoulder lands flush on the receiving timber's face; the tenon runs
along the brace's axis into an angled mortise slot. **The angle is a
joint parameter**, not a baked-in 45: every angled line is an Angle
constraint bound to the VarSet, so one template serves 40/45/50°
braces. This is the roadmap's key distinction in action — an *angled
cut on a perpendicular authoring frame* is pure template geometry
(sketch lines at an angle, prismatic pockets); no part of it needs the
future parametrically-angled-intersection tooling. What that future
stage buys is *placement* support (see Tooling notes).

Unhoused: brace mortises bear on the face itself — a live demonstration
that housings are optional Mill Rule features. A housed or diminished
variant is a separate template.

**Acceptance:** zero strict findings and no advisories other than
`caution-threshold`.

## How to lint

**Save in FreeCAD first** — the linter reads the saved `.FCStd`, not
the open document. Then, from the repo root (or this worktree):

```bash
python -m freecad.bentwizard.linter library/Joint_BraceMT.FCStd
```

If `python` isn't on your PATH, FreeCAD's bundled interpreter works —
the linter is pure Python and never imports FreeCAD:

```bash
"C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe" -m freecad.bentwizard.linter library/Joint_BraceMT.FCStd
```

Findings print as `[rule] Label (InternalName): message`, strict
first; exit code 1 means strict findings remain. Lint after each part
— it is much easier to place a finding when only one part is new.

Conventions as in the housed-dovetail recipe: production-scheme
placeholder names, descriptive-first feature labels (abbrev `BMT`),
tree-picked
references only, activate the body first, lines/circles only, no
shoulder datums.

---

## Part A — the two timbers

**New Timber**, twice, in an empty document saved as
`library/Joint_BraceMT.FCStd`:

| Timber | Label | Width | Depth | Length |
|---|---|---|---|---|
| Post (mortise role) | `T-Post-001` | 8 in | 8 in | 96 in |
| Brace (tenon role) | `T-Brace-001` | 4 in | 5 in | 60 in |

Brace orientation: **Width (4) lies out of the joint plane**, Depth (5)
in the plane of the diagonal. `Length` is the full diagonal stick,
tip to tip — subtractive convention, tenons included.

**Checkpoint A:** lint — zero findings.

---

## Part B — the joint VarSet

A `TimberJointVars` Std Group; inside it one **VarSet** labeled
`J-BraceMT-000`. Group `Joint` except where noted;
`App::PropertyLength` unless stated.

| Property | Value | Tooltip |
|---|---|---|
| `Joint_Station` | 60 in | Distance from the post's end A (Z=0) to the point where the brace's centerline crosses the post's face. |
| `Brace_Angle` | 45° (`App::PropertyAngle`) | Angle between the brace's axis and the receiving timber's length axis, in the joint plane. Drives every angled cut in both halves. |
| `Tenon_Thickness` | 1 1/2 in | Tenon thickness — across the brace's Width, centered on it. |
| `Tenon_Height` | 3 1/2 in | Tenon height — across the brace's Depth, centered on it; measured perpendicular to the brace's axis. |
| `Tenon_Length` | 4 in | Tenon length along the brace's axis, from the stick's end A (the tip) to where the shoulder plane crosses the brace's centerline. |
| `Mortise_Relief` | 1/4 in | Extra mortise depth beyond Tenon_Length along the entry axis, so the tenon never bottoms out. |
| `Template_Angle_Min` | 30° (`App::PropertyAngle`) | Template metadata: smallest Brace_Angle this template's cut profiles stay valid for. The apply dialog clamps angle fields to it and Apply-Joint refuses values below it. |
| `Template_Angle_Max` | 60° (`App::PropertyAngle`) | Template metadata: largest Brace_Angle this template's cut profiles stay valid for. The apply dialog clamps angle fields to it and Apply-Joint refuses values above it. |
| `Template_Handed` | `false` (`App::PropertyBool`) | Template metadata: false = symmetrical about the joint plane (the tenon is centered on the brace's width), so hand selection does not apply. |

Template metadata is recognized by the `Template_` **name prefix**, not
by its property group — put it in whichever group reads best.

Sanity relations (unenforced today; they are why the angle range
metadata exists):

- shoulder clears the stick end:
  `Tenon_Length > (Depth/2) · tan(90° − Brace_Angle)` — at defaults
  2.5 < 4 ✓; below ~32° with these sticks the shoulder runs off the
  tip and the sketches degenerate.
- mortise mouth along the post = `Tenon_Height / sin(Brace_Angle)` ≈
  4.95 in at defaults — keep it clear of other joinery at the station.
- a *descending* strut is not this template mirrored by hand (hand
  mirrors out-of-plane); until the angle work lands, author a mirrored
  variant or place it from the other end of the receiving timber.

**Checkpoint B:** lint — zero findings.

---

## Part C — mortise side, on `T-Post-001`

1. **Landing frame** `Mortise.Lcs.BMT.000`: FlatFace on
   the post's `YZ_Plane` (canonical Face 4), offsets:
   - `Base.x = <<TDim_T-Post-001>>.Depth / 2`
   - `Base.y = <<J-BraceMT-000>>.Joint_Station`
   - `Base.z = <<TDim_T-Post-001>>.Width`
   No housing, so the frame origin sits **on the post's face**, at the
   brace-centerline crossing. Axes: X across the face, Y up the post,
   Z out of the wood. (Face selection still works: the z-mode
   complement turns `Width` into `Width − Width = 0` on face 2, i.e.
   the near face — correct for an unhoused joint.)
2. **Mortise.** Sketch `Mortise.Skt.BMT.000` on the
   frame's **YZ plane** — the elevation containing the post's axis and
   the entry direction; the joint plane. Draw:
   - **entry centerline** (construction): from the origin, running
     **into the wood and toward the post's end A** (the seated brace
     rises up-station away from the face, so its tenon descends into
     the post), with an **Angle constraint**
     `= <<J-BraceMT-000>>.Brace_Angle` to the sketch axis that
     represents the post's length
   - two **flank lines** parallel to the centerline (Parallel
     constraints), each at Distance
     `= <<J-BraceMT-000>>.Tenon_Height / 2` from it — centerline +
     half-widths, never Symmetric (finding #13)
   - **mouth**: both flank lines start on the face trace — the sketch
     axis through the origin representing the post's length —
     (PointOnObject); the mouth edge lies in the face, connecting them
   - **floor line**: Perpendicular to the centerline, at Distance
     `= <<J-BraceMT-000>>.Tenon_Length + <<J-BraceMT-000>>.Mortise_Relief`
     from the origin, closing the slot
   The profile is a trapezoid: two angled flanks, the mouth in the
   face, the floor square to the entry axis.
   **Pocket** `Mortise.BMT.000`: Mode **Symmetric**
   (file property `SideType`, enum index 2; the `Midplane` boolean is
   deprecated in 1.1), Length `= <<J-BraceMT-000>>.Tenon_Thickness`.
   The sketch plane runs mid-face, so the slot centers on the brace's
   width. Verify the slot descends into the wood in a side
   orthographic view — if it climbs, the Angle constraint took the
   wrong branch; re-dimension.

**Checkpoint C:** lint — zero strict findings.

---

## Part D — tenon side, on `T-Brace-001`

The oblique shoulder means one frame is not enough: axis-aligned
prismatic cuts cannot end a tenon's cheeks *on* an angled plane. So the
brace carries a tilted **shoulder frame** as well, and the cheek cut is
sketched on the shoulder plane itself, cutting toward the tip. Three
frames in all: landing, mate, and shoulder.

**Build both frames before any sketch.** Every sketch below lands on
one of them, and a sketch created first has nothing to attach to.

1. **Landing frame** `Tenon.Lcs.BMT.000`: FlatFace
   on the brace's `XY_Plane` (end A), zero offsets. This one sits at
   the section corner and is *not* the frame that aligns with the post
   — leave the offsets at zero, since end-B placement rewrites
   `Base.z` to `Dims.Length`.
2. **Mate frame** `Mate.Lcs.BMT.000`: attach "XY on
   plane" to the landing frame's **XY plane** child. Offsets:
   - `Base.x = <<TDim_T-Brace-001>>.Width / 2`
   - `Base.y = <<TDim_T-Brace-001>>.Depth / 2`
   - `Base.z = <<J-BraceMT-000>>.Tenon_Length`
   - **Rotation**: Axis (1, 0, 0); on `AttachmentOffset.Rotation.Angle`
     set the expression `= 90 ° - <<J-BraceMT-000>>.Brace_Angle`
     (mind the degree unit on the literal)
   Its XY plane is the shoulder plane: through the centerline point at
   Tenon_Length, tilted so its **Face-1 side (y = 0) leans toward the
   stick end**. Verify in a side view; if it leans the other way,
   negate the expression. **This is the frame that aligns** — when
   engaged it coincides axis-for-axis with the post's landing frame
   (X out of the joint plane, Y up the post, Z out of the post face),
   and it is what makes Preview and auto-assembly work.
3. **Shoulder frame** `Shoulder.Lcs.BMT.000`:
   attached and placed **identically to the mate frame** — same
   support, same three Base expressions, same Rotation axis and Angle
   expression. A separate LCS on purpose: the mate frame is an
   engagement declaration that placement tooling transforms (the end-B
   flip rewrites its rotation), and cut geometry must never ride on
   it. The cheek sketch in step 5 lands here.
4. **Shoulder + tenon-band cut (elevation).** Sketch
   `Shoulder.Skt.BMT.000` on the **landing**
   frame's **YZ plane** (the Face-2 reference plane — the joint
   plane):
   - construction **centerline** along the stick at
     `= <<TDim_T-Brace-001>>.Depth / 2`
   - construction **shoulder line** through the centerline at Distance
     `= <<J-BraceMT-000>>.Tenon_Length` from the stick end (measured
     along the centerline), with an Angle constraint
     `= <<J-BraceMT-000>>.Brace_Angle` to the centerline, its Face-1
     end nearer the stick end (matching the shoulder frame)
   - **upper removal quadrilateral**: from the band top —
     `= <<J-BraceMT-000>>.Tenon_Height / 2` above the centerline — up
     to the top face, from the stick end back to the shoulder line
     (corners on the construction line via PointOnObject)
   - **lower removal quadrilateral**: mirror of the upper — band
     bottom at `Tenon_Height / 2` below the centerline, down to the
     underside, stick end back to the shoulder line
   **Pocket** `Shoulder.BMT.000`: Through all, one
   direction across the full width (the sketch lies on the reference
   face). This leaves a full-width band, its end faces on the oblique
   shoulder plane.
5. **Cheek cuts (on the shoulder plane).** Sketch
   `Cheeks.Skt.BMT.000` on the **shoulder frame's
   XY plane** (tree-select its plane child):
   - centerline construction line through the origin along the
     frame's in-plane (Y) axis
   - two removal rectangles flanking the tenon: inner edges at
     `= <<J-BraceMT-000>>.Tenon_Thickness / 2` each side of the
     centerline, outer edges at
     `= <<TDim_T-Brace-001>>.Width / 2` (the section flanks);
     in the other direction span generously —
     `= <<TDim_T-Brace-001>>.Depth` past the origin both ways
     covers the oblique section at any angle in the template's range
     (removal regions may hang into air)
   **Pocket** `Cheeks.BMT.000`: Through all,
   direction **toward the stick end** (away from the brace's body).
   Everything forward of the shoulder plane beside the tenon goes; the
   shoulder plane itself and the body behind it must remain — verify
   in an orthographic view that the cut did not bite past the
   shoulder. The tenon's tip is the stick's own end face (subtractive
   `Length`), square to the axis, matching the mortise floor.

**Checkpoint D:** lint — zero strict findings. (Nothing here trips the
severing scans by name; the numbers are far under the limits anyway.)

---

## Part E — inspection pose and verification

1. Pose `T-Brace-001` seated: rising at 45°, shoulder flush on the
   post's face, tip in the slot (or run Preview Mated Joint — the
   engagement machinery is angle-blind by construction, so the ghost
   must seat correctly at any Brace_Angle).
2. Clipping plane through the joint plane. Measure: shoulder to face 0;
   tenon flanks to mortise flanks 0; tip to floor = `Mortise_Relief`.
3. Parametric shakedown — the point of this template: set
   `Brace_Angle` to 40°, recompute — the mortise slot re-slopes, the
   shoulder and both brace frames re-tilt, and Preview must re-seat
   the ghost flush. Then 50°. Then check the range edges (30°/60°)
   for degenerate sketches — that observed range is what
   `Template_Angle_Min/Max` should record. Change `Tenon_Length` and
   `Tenon_Height`; both halves track. Undo all.
4. Final lint, then commit.

## Tooling notes (read before applying this template)

- **Apply at the authored placement only — post role face 4, brace
  role end A, template hand** — until the parametrically-angled stage
  lands. The placement transforms (`FACES`, end-B, hand) assume
  perpendicular intersections and axis-aligned frames; concretely,
  end B on the brace fails today because sketches on the shoulder
  frame are not transformed (only landing-frame sketches are).
  Apply-Joint now *refuses* an end-B request outright — the seat flip
  cannot compose with the mate frame's expression-driven rotation, and
  it raises rather than mis-seat silently.
- A brace needs a joint at **both** ends. Until end B works, the
  second end is a manual build (this recipe, mirrored along the
  stick), or wait for the angled-placement work.
- `Template_Angle_Min/Max` are live: the dialog clamps angle fields to
  the range and the apply pre-flight refuses resolved values outside
  it. The dialog also skips the hand option (`Template_Handed` false).
- The severing/footprint pre-flight has no `Housing_*` pair to check
  here; the other Part B sanity relations are the working bounds, to
  become template-declared constraints (roadmap).
