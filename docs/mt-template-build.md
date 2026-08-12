# Building `library/Joint_HousedMT.FCStd` — step-by-step

> **Historical record — do not follow the labels.** This recipe records
> how the template was first built, under the pre-July-2026 naming
> scheme (`P0-1`/`B0-1` bodies, a `Joint_MT_0a` VarSet, body-qualified
> feature labels). The shipped template has since been migrated to the
> current scheme by `scripts/migrate-naming.py`: bodies `T.Post.001` /
> `T.AnchorBeam.001`, joint VarSet `J-HousedMT-000`, and descriptive-
> first feature labels (`Mortise.HMT.000`, `Housing.Skt.HMT.000`,
> `Mate.Lcs.HMT.000`) with `Template_Abbrev = "HMT"` and a `Frame_Role`
> on each frame. The **geometry, parameters and expressions below are
> still accurate** — only the labels changed.
>
> **Superseded in one respect (August 2026):** joint frames now sit on
> the primary timber's **face**, not at the housing's bearing plane.
> Part C.1's `Base.z` and Part F.2's mate-frame offset below are the
> pre-conversion values; see **Part G** at the end for the conversion,
> which is what the shipped file now carries.
>
> For authoring a NEW template, start from `library/Joint_Butt.FCStd`
> (see [butt-template-build.md](butt-template-build.md)) — a valid,
> jointless skeleton — rather than copying a template that already has
> joinery in it. [housed-dovetail-template-build.md](housed-dovetail-template-build.md)
> shows a full build against the current conventions.

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
- **Double-click the target body to activate it before creating any
  datum or sketch.** Objects created with no active body land at the
  document root, where body sketches cannot attach to them (a root-level
  frame produces "doesn't contain feature with role" attach errors).
  Fix by dragging the object into the body in the tree.
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
| `Tenon_Width` | 2 in | Tenon width — horizontal across the landed beam, measured from the setback off the beam's reference Face 2. |
| `Tenon_Height` | 6 in | Tenon height — vertical, along the bearing direction, measured from the setback off the beam's reference Face 1. |
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

Structure (decided when Part C began): everything on a role hangs off
**one landing frame** — a `Part::LocalCoordinateSystem` datum. The frame
carries all placement decisions (which face, station, depth, centering)
as attachment-offset expressions; the sketches are **frame-local** and
reference only the joint VarSet. Applying the joint to a different
face/station/hand means re-placing one object. This supersedes the
Phase 0 zero-offset datum guidance for template builds (finding #10's
concern was body-frame confusion; frame-local sketches don't claim to
be in body coordinates, and file inspection verifies resolved
placements at each checkpoint).

1. **Landing frame** `P0-1_JointFrame_MT_0a` (datum coordinate system):
   attach "XY on plane" to the post's `YZ_Plane` (from the tree), then set
   attachment offset expressions:
   - `Base.x = <<TimberDims_P0-1>>.Depth / 2` — center of the post face
   - `Base.y = <<Joint_MT_0a>>.Joint_Station + <<Joint_MT_0a>>.Housing_Height / 2` — center of the landing footprint
   - `Base.z = <<TimberDims_P0-1>>.Width - <<Joint_MT_0a>>.Housing_Depth` — the bearing plane
   The frame origin now sits at the center of the beam's landing
   footprint, at bearing depth. Expected axes (verify in the 3D view):
   frame X across the post face, frame Y up the post, frame Z out of
   the wood. The frame's XY plane IS the bearing plane — no separate
   bearing datum.
2. **Housing.** Sketch `P0-1_HousingSketch_MT_0a` on the frame's
   **XY plane** (select the frame's plane in the tree; if the sketch
   lands at the body origin instead of out at bearing depth, the
   attachment grabbed the wrong reference — reattach): rectangle
   centered on the sketch origin, using the sketch axes as centerlines —
   - each vertical edge `= <<Joint_MT_0a>>.Housing_Width / 2` from origin
   - each horizontal edge `= <<Joint_MT_0a>>.Housing_Height / 2` from origin
   **Pocket** `P0-1_Housing_MT_0a`, direction outward (toward the
   removed face), Length `= <<Joint_MT_0a>>.Housing_Depth`. Toggle
   Reversed if it grows into the stick — verify with a side orthographic
   view, not wireframe (§5).
3. **Mortise.** Sketch `P0-1_MortiseSketch_MT_0a` on the frame's XY
   plane. Setbacks measure from the landing footprint's edges, so draw
   the footprint first, as construction geometry, and dimension from it —
   this keeps every dimension positive regardless of joint proportions
   (signed frame-local offsets can resolve negative and fail the
   solver):
   - **construction rectangle** = the footprint, centered like the
     housing: vertical edges `= <<Joint_MT_0a>>.Housing_Width / 2` from
     the V-axis, horizontal edges `= <<Joint_MT_0a>>.Housing_Height / 2`
     from the H-axis
   - mortise rectangle (normal geometry), drawn roughly in place, then
     dimensioned from the footprint edges:
     left edge `= <<Joint_MT_0a>>.Tenon_Setback_Face2` from the left
     footprint edge; bottom edge `= <<Joint_MT_0a>>.Tenon_Setback_Face1`
     from the bottom footprint edge; extents
     `= <<Joint_MT_0a>>.Tenon_Width` × `= <<Joint_MT_0a>>.Tenon_Height`.
   With the default values the mortise lands dead-center of the
   footprint (the tenon is symmetric in the beam) — that's the visual
   check.
   **Pocket** `P0-1_Mortise_MT_0a`, direction inward,
   Length `= <<Joint_MT_0a>>.Tenon_Length + <<Joint_MT_0a>>.Mortise_Relief`.
4. **Peg bore.** Sketch `P0-1_PegBoreSketch_MT_0a` on the frame's
   **YZ plane** (the plane containing "up the post" and "into the
   wood"). The peg ties to the **mortise center**, not the frame center —
   frame-centered only coincides while the setbacks are symmetric, and
   an asymmetric application (barefaced/offset tenon) would silently
   misplace it. Draw the surrounding joinery edge-on as **construction
   rectangles** — the housing profile (Housing_Height ×
   Housing_Depth, against the bearing plane) and the tenon profile
   (Tenon_Height × Tenon_Length, into the wood, Tenon_Setback_Face1
   above the footprint bottom). This scaffold makes peg layout visual —
   one or several pegs placed against visible geometry instead of
   guessed coordinates — and every dimension stays positive.
   - one circle per peg, on the into-the-wood side: centered on the
     tenon profile's vertical centerline; depth from the bearing plane
     `= <<Joint_MT_0a>>.Peg_Setback`; diameter
     `= <<Joint_MT_0a>>.Peg_Diameter`
   **Pocket** `P0-1_PegBore_MT_0a` (a Pocket, not a Hole — the Hole
   dialog does not expose the symmetric option): Type **Through all**,
   Mode **Symmetric** — the sketch plane is mid-post, so the bore must
   cut both directions to cross the full post. (In the file this is the
   `SideType` property; the old `Midplane` boolean is deprecated in 1.1
   and ignored — scripts and file checks must read/write `SideType`.)

**Checkpoint C:** lint — expect zero findings. (The Tenon_Width/Height
naming puts the across-grain dimension — 2 in, 25% — under the severing
scan and the along-grain height correctly outside it, so no caution
fires.) I verify resolved frame/sketch placements from the file.

---

## Part D — tenon side, on `B0-1` (§4.4 + §4.7)

Same architecture: one landing frame per role. The beam's frame sits at
end A with zero offsets (frame axes = body axes there), so retargeting
the tenon to end B is one frame re-placement plus the drawbore sign
flip — both computed by the tool at apply time.

1. **Landing frame** `B0-1_JointFrame_MT_0a` (datum coordinate system):
   attach "XY on plane" to the beam's `XY_Plane` (end A), all offsets zero.
2. **Tenon (island pocket).** Sketch `B0-1_TenonSketch_MT_0a` on the
   frame's XY plane: two loops —
   - outer rectangle = the full section, corner at origin,
     `= <<TimberDims_B0-1>>.Width` × `= <<TimberDims_B0-1>>.Depth`
     (the one body-dimension exception: the outer loop is the timber's
     own section, which is the same at either end)
   - inner rectangle: from `= <<Joint_MT_0a>>.Tenon_Setback_Face2` (X) and
     `= <<Joint_MT_0a>>.Tenon_Setback_Face1` (Y), extents
     `= <<Joint_MT_0a>>.Tenon_Width` × `= <<Joint_MT_0a>>.Tenon_Height`.
   Both setbacks are > 0, so the island stays strictly interior
   (finding #14) — the linter checks this.
   **Pocket** `B0-1_Tenon_MT_0a`, Length `= <<Joint_MT_0a>>.Tenon_Length`.
3. **Shoulder datum** `B0-1_ShoulderA_MT_0a`: "XY on plane" on the frame's
   XY plane, offset `Base.z = <<Joint_MT_0a>>.Tenon_Length`. (Assembly
   references land here, §4.8.)
4. **Drawbore peg bore.** Sketch `B0-1_PegBoreSketch_MT_0a` on the
   frame's **YZ plane**: **one circle** (one sketch per instance —
   debt 2) —
   - center along the beam `= <<Joint_MT_0a>>.Tenon_Length - <<Joint_MT_0a>>.Peg_Setback + <<Joint_MT_0a>>.Peg_Drawbore_Offset`
   - center across `= <<Joint_MT_0a>>.Tenon_Setback_Face1 + <<Joint_MT_0a>>.Tenon_Height / 2`
   - diameter `= <<Joint_MT_0a>>.Peg_Diameter`
   **Hole** `B0-1_PegBore_MT_0a`: Through all, diameter
   `= <<Joint_MT_0a>>.Peg_Diameter`. (A Hole works here — this sketch
   plane lies on the beam's reference face, not mid-timber, so a
   one-directional through-all crosses the whole stick. Draw the tenon
   edge-on as a construction rectangle for the same visual-layout
   benefit as C.4.)

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
   timbers must travel together; change `Tenon_Width` — mortise and
   tenon must move in lockstep; make the setbacks asymmetric — the peg
   must follow the mortise center. Undo all (or close without saving
   and re-verify defaults).
4. Final lint + run the test suite. Then commit the template.

Shakedown expectations (from the live run):
- `Joint_Station` moves the cuts only. The beam's pose is Body
  Placement — an assembly-phase binding (shoulder datum to bearing
  frame), not template geometry. Keep the as-assembled pose in the
  saved template (finding #7a).
- Parameter combinations that describe an impossible joint (setback +
  tenon extent past the housing opening) flip unsigned sketch
  dimensions to the wrong solver branch, where they stick even after
  the values are restored — recover by deleting and re-creating the
  affected dimension. No constraint chain survives impossible values;
  the guards are the linter's `joint-exceeds-footprint` strict rule on
  saved files and the apply-dialog's parameter bounds (roadmap).

Built: `library/Joint_HousedMT.FCStd`, mirrored as a test fixture —
the template must stay completely clean (strict and advisory) for the
suite to pass.

---

## Part F — the mate frame (added for Preview Mated Joint)

Convention: a role that enters its mate carries one **mate frame** — a
datum LCS declaring "when engaged, this frame coincides with the
mating role's landing frame, axis for axis." Preview (and later,
assembly) aligns two frames and needs no joint-specific knowledge; a
future scarf or lap defines its own engagement the same way.

1. Activate `B0-1`. **Create coordinate system**
   `B0-1_MateFrame_MT_0a`: attach "XY on plane" to
   `B0-1_JointFrame_MT_0a`'s **XY plane** child (tree-select).
2. Offset expressions:
   - `Base.x = <<TimberDims_B0-1>>.Width / 2`
   - `Base.y = <<TimberDims_B0-1>>.Depth / 2`
   - `Base.z = <<Joint_MT_0a>>.Tenon_Length`
3. Verify: origin at the beam's section center on the shoulder plane
   (3, 4, 4) in; axes parallel to the beam's own (X across Width, Y
   across Depth, Z along the stick, away from the tenon).
4. Lint, save, and refresh the test fixture copy.

---

## Part G — conversion to frames-at-face (August 2026)

> **Performed August 2026.** The file is converted; this section is now
> the record of what was done. Two deviations from the recipe as
> originally written, both noted in place: **G.4** uses an
> expression-driven attachment offset instead of re-anchoring the peg
> sketch's construction scaffold (same behaviour, no constraint
> surgery — the pattern the dovetail conversion proved), and **G.5's
> tenon-loop oversize was not done** — see the note there.
>
> Verified: both solids unchanged (post `dVol` 1.5e-08 on 122M mm³,
> beam 6.0e-08, face counts and bounding boxes identical); the face
> 1–4 × end A/B matrix bit-identical to before (post 81.283/79.712 in³
> by `ddim`, beam 145.571 in³ throughout); all eight seating with
> misfit ~1e-13 and zero overlap.

Edits to the **built** file, not a rebuild. Two things change and the
rest follows: the landing frame moves out to the post's face, and the
mate frame is driven by the companion's allowance instead of the tenon
length.

**Why.** With the landing frame inset to the bearing plane, the
clear-span allowance was arithmetic each template had to reproduce
(`Tenon_Length + Housing_Depth`) — and nobody could say what it should
be for a dovetail. On the face, **the mate frame's offset from the stick
end IS the allowance**, whatever the joinery, so a template publishes it
by placing a datum. Housings also become independently adjustable: the
frame no longer moves when `Housing_Depth` changes.

Nothing about assembly or preview changes. Both frames shift by the same
amount along the same axis, so the engaged pose is identical, and
`_face_transform` is algebraic on whatever the template authors (face
2's `complement` of `Width` resolves to 0 — the near reference face —
exactly as it previously resolved to `Housing_Depth`).

### G.1 — the companion and the joint VarSet

`Layout_J-HousedMT-000` is unchanged: it keeps authoring
`Stick_Allowance_FTF = Tenon_Length + Housing_Depth`.

On `J-HousedMT-000`, **add** one property:

| Property | Type | Group | Value | Tooltip |
|---|---|---|---|---|
| `Stick_Allowance_FTF` | `App::PropertyDistance` | `Joint` | *expr* `= <<Layout_J-HousedMT-000>>.Stick_Allowance_FTF` | Stick consumed beyond the post's face, along the beam's axis; positions the mate frame. Authored on the companion layout VarSet — edit it there. |

This consumed copy is **not optional bookkeeping**. `joint_members`
finds a joint's parts by closing over the literal token
`<<J-HousedMT-000>>` in expressions, and `<<Layout_J-HousedMT-000>>`
does not contain it — binding the mate frame straight to the companion
would silently drop it out of the joint, taking Preview, the assembly
seat, the handle and `rule_frame_role` with it.

### G.2 — the landing frame, `Mortise.Lcs.HMT.000`

One expression:

| Offset | Was | Becomes |
|---|---|---|
| `Base.z` | `= <<TDim_T.Post.001>>.Width - <<J-HousedMT-000>>.Housing_Depth` | `= <<TDim_T.Post.001>>.Width` |

`Base.x` and `Base.y` are unchanged. The frame origin now sits on the
post's face at the center of the landing footprint; its XY plane is the
**face plane**, no longer the bearing plane.

### G.3 — the two pockets on the post

The housing and mortise **sketches need no edits at all** — they lie in
the frame's XY plane, and moving the frame along its own Z leaves every
in-plane coordinate untouched. Only the cuts change:

| Feature | Change |
|---|---|
| `Housing.HMT.000` | ~~**Toggle `Reversed` to false** so it cuts *into* the post from the face. `Length` stays `= <<J-HousedMT-000>>.Housing_Depth`.~~ **Superseded — see below.** |
| `Mortise.HMT.000` | `Length` becomes `= <<J-HousedMT-000>>.Housing_Depth + <<J-HousedMT-000>>.Tenon_Length + <<J-HousedMT-000>>.Mortise_Relief`. `Reversed` stays false. |

The mortise's new `Housing_Depth` term is honest, not a workaround: the
cut now starts at the face and has to cross the housing before it
reaches wood the tenon occupies. Change `Housing_Depth` and the mortise
bottom still follows automatically.

> **The housing cut is padded and runs outward** (revised August 2026,
> after GUI testing). Cutting inward from the face with
> `Length = Housing_Depth` dies at `Housing_Depth = 0` — *"cannot
> create a pocket with a total length of 0"* — and zero is a legitimate
> value: a Mill Rule housing is optional. Worse than a stopped
> recompute, the housing then froze at its last good depth while a
> driven `Length` kept resizing the beam, so an H-bent went quietly
> inconsistent. As built:
>
> | | |
> |---|---|
> | `Housing.Skt.HMT.000` | attachment offset `Base.z = -<<J-HousedMT-000>>.Housing_Depth` — back on the bearing plane |
> | `Housing.HMT.000` | `Reversed` **true** (outward), `Length = <<J-HousedMT-000>>.Housing_Depth + 0.25 in` |
>
> The pad only ever crosses the face into air, so the removed volume is
> exactly `Housing_Depth` at any depth — verified identical to the
> unpadded cut at the shipped default, and clean at zero both in the
> template and across all eight applied placements. The mortise needs
> no such treatment: its length is a sum that cannot reach zero.

Verify with a **side orthographic view and a clipping plane**, never
wireframe (§5): the housing must be a shallow recess in the face and the
mortise must bottom out `Mortise_Relief` past the tenon's reach.

### G.4 — the mortise peg bore, `MortisePegBore.Skt.HMT.000`

This sketch is on the frame's **YZ plane**, which the frame move *does*
shift: sketch X runs up the post, sketch Y runs out of the wood, and
negative sketch Y is into the post. Everything in it now sits
`Housing_Depth` further in.

Re-anchor the construction scaffold as a **chain from the face** rather
than adding a term to the peg dimension:

1. Housing rectangle: from the sketch origin **into** the wood, depth
   `= <<J-HousedMT-000>>.Housing_Depth`, height
   `= <<J-HousedMT-000>>.Housing_Height` centered on the X axis. (It
   previously ran *out* of the wood from the origin.)
2. Tenon rectangle: starts at the housing rectangle's **inner edge**,
   reaching `= <<J-HousedMT-000>>.Tenon_Length` further in, height
   `= <<J-HousedMT-000>>.Tenon_Height`, positioned
   `= <<J-HousedMT-000>>.Tenon_Setback_Face1` above the housing
   rectangle's lower edge.
3. Peg circle: depth `= <<J-HousedMT-000>>.Peg_Setback` measured from
   the **housing rectangle's inner edge** — i.e. from the bearing plane,
   exactly as before. Centered on the tenon rectangle's vertical
   centerline (the peg ties to the mortise, not the frame — an
   asymmetric application would otherwise misplace it).

Chaining off the scaffold is what keeps `Peg_Setback` meaning "from the
bearing plane" with no arithmetic in the dimension, and keeps every
dimension positive. `Housing_Depth` appears exactly once in this sketch.

> **What was actually done, and why it differs.** No constraint was
> touched. The sketch keeps its scaffold and gains one attachment
> offset, `Base.y = -<<J-HousedMT-000>>.Housing_Depth`, which holds it
> on the bearing plane where it already sat — the frame's Z maps to
> this sketch's local **y**, because it hangs off the frame's YZ plane
> (`_FRAME_PLANE_OFFSET_AXIS`). That satisfies both of the paragraph
> above's requirements — `Peg_Setback` still measures from the bearing
> plane with no arithmetic in the dimension, and `Housing_Depth` still
> appears exactly once — while avoiding the risk that made the rewrite
> unattractive: this sketch's section bindings are **index-based**
> (`Constraints[17]`, `Constraints[18]`), so deleting or inserting a
> constraint renumbers them and silently redirects the expressions.
> Confirmed equivalent: deepening the housing 1/2 in → 1 1/2 in moves
> the peg sketch from x=241.3 to x=215.9, identical before and after
> the conversion.

`MortisePegBore.HMT.000` itself is unchanged: Through all, `SideType`
Symmetric (the sketch plane is mid-post, so the bore must cut both ways).

### G.5 — the beam side

| Object | Change |
|---|---|
| `Mate.Lcs.HMT.000` | `Base.z`: `= <<J-HousedMT-000>>.Tenon_Length` → `= <<J-HousedMT-000>>.Stick_Allowance_FTF` |
| `Tenon.Skt.HMT.000` | Oversize the **outer removal loop** by 1 in on all four sides (a plain literal margin is fine — sketch dimensions are not subject to the stale-offset rule). The inner tenon island is unchanged. |
| `Tenon.HMT.000`, `ShoulderA.Dtm.HMT.000`, `TenonPegBore.*` | Unchanged. |

`Mate.Lcs` resolves to the same place it always did for the shipped
defaults (`Tenon_Length + Housing_Depth` from end A, matching the post
face) — the difference is that it now says *what it means* rather than
happening to land there.

**Why oversize the tenon loop.** With the shipped setbacks the island is
already strictly interior, so this changes no geometry today. It is
insurance against a user zeroing `Tenon_Setback_Face1` for a full-height
tenon, which is a legitimate joint the apply dialog allows. Verified
headless (August 2026): with an oversized loop the result is exact, and
with a section-sized loop the island's edges land on the removal loop
and **PartDesign silently removes the whole section for the pocket's
length** — reporting `Up-to-date` and `isValid()` while the tenon simply
is not there. That is the failure `rule_island_interior` exists to
catch, and the oversized loop is the sanctioned way to model past it.
The excess cuts air.

> **Not done — still owed.** This is the one item of Part G left
> outstanding, and it is deliberately separate: it changes no geometry
> at the shipped setbacks and is about island interiority, not
> frames-at-face. It was skipped because it cannot be done safely
> outside the GUI. The outer loop's corner is pinned to the sketch
> origin by a **Coincident** constraint, so oversizing means deleting
> that constraint and adding two dimensional ones — and this sketch's
> section bindings are index-based (`Constraints[17]` = Width,
> `[18]` = Depth), so the renumbering would silently redirect them to
> the wrong constraints. In the GUI FreeCAD maintains those paths.
> Do it there, or name the constraints first and bind by name.

### G.6 — verification

1. Lint: zero strict, and no advisories other than `caution-threshold`.
2. Parametric shakedown, additionally checking what this change is for:
   **change `Housing_Depth` alone** — the housing must deepen while the
   mortise bottom and peg follow, and nothing else in the template moves.
3. Refresh the `tests/fixtures/` copy and run the suite.
4. In a model: an H-bent, two posts and a girt, housed M&T both ends.
   With `Length` typed as a literal, changing `Tenon_Length` moves a
   post — expected, and unchanged by this work. Then drive the girt's
   `Length` from a clear-span distance: the driven `Length` must equal
   the distance plus the two allowances exactly, and from then on
   changing `Tenon_Length` or `Housing_Depth` re-cuts the stick and
   leaves both posts where they are. That invariance is the point; the
   frames were only ever bookkeeping.
