# `library/Joint_WedgedHalfDovetail.FCStd` — as built

The Dutch anchor-beam joint: a through tenon whose **underside is a
half dovetail**, flaring so the tenon is tallest at its protruding tip;
the post's through mortise carries the matching slope on its floor. The
mortise is cut taller than the tenon, and that surplus sits **above**
the seated beam, where a wedge is driven down to lock the beam and
force the sloped faces into bearing. Housed (Mill Rule optional bearing
feature).

## The socket role is a post — this is not the Phase 0 dovetail

The mortise timber must be a **post or other vertical member**; the
tenon timber is a horizontal beam or tie entering its face. Do not read
this template as a variant of the housed dovetail — that one drops a
joist into a *horizontal* girt's top face, tops flush. Two dovetails,
two purposes, two templates.

The constraint is gravity, and it is baked into the geometry rather
than into any check. The landing frame's Y axis runs **up the socket
member's stick**, so every "above" in this recipe — the mortise
surplus, the wedge seat, the direction the beam is lowered from — is
along that timber's length, and `Joint_Station` reads as a height up
the post. Lay the socket member down and the wedge pocket opens
sideways: the wedge has nothing to bear against and drops out.

Section rules it out too. The mortise is taller than the incoming
beam's *full depth* (`Tenon_Height + Wedge_Depth`), so a girt of
comparable depth would be cut through top to bottom with nothing left
to carry load. Posts have the section to give up; horizontal members in
the same frame do not.

*Rewritten July 2026 from Adam's finished model, which corrected the
first draft.* The original recipe had the dovetail inverted — slope on
top, wedge below — which resists nothing: a half dovetail only holds if
the flare is on the face that the withdrawal load pulls against. Where
this document and the file disagree, **the file wins**; it is the
reference for sketch topology.

Values are imperial example data; enter them per your FreeCAD unit
schema.

**Acceptance:** zero strict findings, and no advisories other than
`caution-threshold`.

## How to lint

**Save in FreeCAD first** — the linter reads the saved `.FCStd`, not
the open document. Then, from the repo root (or this worktree):

```bash
python -m freecad.bentwizard.linter library/Joint_WedgedHalfDovetail.FCStd
```

If `python` isn't on your PATH, FreeCAD's bundled interpreter works —
the linter is pure Python and never imports FreeCAD:

```bash
"C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe" -m freecad.bentwizard.linter library/Joint_WedgedHalfDovetail.FCStd
```

Findings print as `[rule] Label (InternalName): message`, strict
first; exit code 1 means strict findings remain. Several files can be
passed at once. Lint after each part — it is much easier to place a
finding when only one part is new.

## The three geometric facts that define this joint

Everything below follows from these; get them wrong and the joint is
decorative.

1. **The slope is on the tenon's underside, and the tenon is tallest at
   the tip.** Withdrawal pulls the tall tip against the narrower
   mortise mouth. (Verified on the built model: tenon height 7.96 in at
   the tip, 7.08 in at the shoulder.)
2. **The tenon is the full depth of the beam** — its top face *is* the
   beam's top face. No top or bottom shoulder is cut: the angled
   underside creates the only shoulder, at the bottom. Fewer cuts, and
   a flush top surface for driving the wedge.
3. **The mortise is taller than the beam, and the surplus is above it**
   — above meaning *up the post*, which is why the socket member must
   be plumb. Mortise opening = `Tenon_Height + Wedge_Depth`; the beam's
   landing footprint = `Housing_Height`. The difference is deliberately
   exposed above the seated beam so the wedge is reachable — a wedge
   you cannot get at is a joint you cannot assemble.

The insertion clearance follows from (1): the tenon enters tip-first
past a mouth sized for the *root*, so the beam is carried in high and
lowered — again, along the post's length.
**`Wedge_Depth` ≥ `Tenon_Length` × tan(`Dovetail_Angle`)** — as built,
11 × tan 5° = 0.96 in ≤ 1.25 in.

## Conventions

- Placeholder names use the production scheme: bodies `T.Post.001` /
  `T.AnchorBeam.001`, joint VarSet `J-WedgedHalfDovetail-000`. Labels
  are permissive — dotted, hyphenated, or spaced all lint clean.
- **Joint feature labels read `<Descriptive>[.<TypeTag>].WHD.000`** — the
  cut bare (`Housing.WHD.000`), its sketch and datums tagged
  (`Housing.Skt.WHD.000`, `Mate.Lcs.WHD.000`). `WHD` is this template's
  `Template_Abbrev`; `000` is the placeholder serial. Apply-Joint
  substitutes precisely that suffix, so a label missing it survives into
  every applied model under its template name. **Strict** lint rule
  `joint-feature-label` catches it.
- **Feature labels must be unique across BOTH halves** — the timber name
  no longer separates them. Name shared features for their role
  (`Socket.Lcs` on the post, `Tail.Lcs` on the beam). Advisory rule
  `duplicate-label` catches collisions.
- **Every frame needs a `Frame_Role` string property** — `Landing` on
  each half's landing frame, `Mate` on the frame declaring the seated
  pose. Preview, Assemble, Duplicate and end-B seating all read it, and
  nothing works without it. Strict rule `frame-role`.
- Tree-picked references only, never a 3D pick and never a solid face.
- Activate the body before creating any datum or sketch.
- The rebuilder clones lines and circles only.
- **Attach frame-local sketches to the frame, with the plane as a
  sub-element** — support reads `(<frame LCS>, "YZ_Plane.")`, not the
  bare child-plane object. If you *move* a sketch onto a new frame
  rather than redrawing it, FreeCAD often re-records the support as the
  raw child plane, which resolves to identity placement (fine only
  while the frame sits at the origin) and makes Apply-Joint fail with
  "no origin plane matching …". The strict `lcs-child-plane-reference`
  lint rule catches it. To fix: open the sketch's Attachment editor,
  clear the reference, and re-pick the frame's plane so the dialog
  shows the **frame's** name as the reference, not the plane's.

---

## Part A — the two timbers

**New Timber**, twice, in an empty document saved as
`library/Joint_WedgedHalfDovetail.FCStd`:

| Timber | Label | Width | Depth | Length | Stands |
|---|---|---|---|---|---|
| Post (mortise role) | `T.Post.001` | 10 in | 8 in | 96 in | **plumb** — its length is the joint's "up" |
| Anchor beam (tenon role) | `T.AnchorBeam.001` | 6 in | 8 in | 96 in | level, entering the post's face |

New Timber nests each `TDim_…` VarSet inside its Body — the
current §3 tree convention, and what Apply-Joint now expects.

---

## Part B — the joint VarSet

A `TimberJointVars` Std Group holding one **VarSet**
`J-WedgedHalfDovetail-000`, properties in group `Joint`;
`App::PropertyLength` unless noted.

| Property | Value | Tooltip |
|---|---|---|
| `Joint_Station` | 48 in | Distance from the post's end A (Z=0) to the underside of the housing, along the post's length. |
| `Housing_Width` | *expr* `= <<TDim_T.AnchorBeam.001>>.Width` | Horizontal opening of the housing across the post face; tracks the beam's Width. Override with a literal to hold it off the beam size. |
| `Housing_Height` | *expr* `= <<TDim_T.AnchorBeam.001>>.Depth` | Vertical opening of the housing along the post; tracks the beam's Depth. Override with a literal to hold it off the beam size. |
| `Housing_Depth` | 1 in | Depth of the housing into the post, measured from post Face 4 (opposite reference Face 2). A deep housing spreads bearing across the full beam width. |
| `Tenon_Thickness` | 2 in | Tenon thickness — horizontal across the landed beam, centered on the beam's width. |
| `Tenon_Height` | *expr* `= <<TDim_T.AnchorBeam.001>>.Depth` | Tenon height at the mouth — the full beam depth, since the tenon's top is the beam's top face and only the underside is cut. |
| `Dovetail_Angle` | 5° (`App::PropertyAngle`) | Rise of the tenon's underside from the tip toward the shoulder, off the beam's axis. The mortise floor matches it. |
| `Tenon_Length` | 11 in | Tenon length from the beam's end A to the shoulder plane; must exceed the post's through-dimension so the tip emerges. |
| `Wedge_Depth` | 1 1/4 in | Height of the mortise above the seated tenon — the wedge seat, left open above the beam so the wedge can be driven. Must be at least Tenon_Length × tan Dovetail_Angle or the tenon cannot enter. |
| `Wedge_Width` | *expr* `= Tenon_Thickness` | Wedge stock width across the mortise; follows the tenon thickness. For the parts schedule — the wedge is not modeled here. |
| `Wedge_Length` | *expr* `= Tenon_Length` | Wedge stock length along the beam's axis, for the parts schedule. |
| `Wedge_Count` | 1 (`App::PropertyInteger`) | Number of wedges in this joint, for the parts schedule. Not geometry. |
| `Template_Handed` | `false` (`App::PropertyBool`) | Template metadata: false = symmetrical about the joint's vertical centerline plane (the dovetail's asymmetry is vertical, which hand mirroring never touches), so hand selection does not apply. |

**No `Tenon_Setback_Face1`.** The first draft carried one; the angled
underside replaced it, and an unused setback trips the strict
`joint-exceeds-footprint` pairing (`setback + Tenon_Height` against
`Housing_Height`) for a joint that is in fact fine.

`Template_Handed` is recognized by its **name prefix**, not its
property group — put it wherever reads best.

**The wedge is not modeled.** Two-role templates are what the tools
consume today; the wedge is the created-part role of the adopted N-part
design. Its cavity is modeled (it is simply the mortise surplus) and
its stock rides on the VarSet for the future parts schedule, the same
Tier-2 pattern as `Peg_Count`. A wedge to model today is an ordinary
standalone Body — pads are fine on created parts.

---

## Part C — mortise side, on `T.Post.001`

1. **Landing frame** `Socket.Lcs.WHD.000`:
   FlatFace on the post's `YZ_Plane` (canonical Face 4), offsets
   - `Base.x = <<TDim_T.Post.001>>.Depth / 2`
   - `Base.y = <<J-WedgedHalfDovetail-000>>.Joint_Station + <<J-WedgedHalfDovetail-000>>.Housing_Height / 2`
   - `Base.z = <<TDim_T.Post.001>>.Width - <<J-WedgedHalfDovetail-000>>.Housing_Depth`

   Origin at the centre of the beam's landing footprint, on the bearing
   plane. Axes: X across the post face, **Y up the post**, Z out of the
   wood. That Y axis is the joint's "up" — every dimension below that
   reads as above or below resolves along it, which is the whole reason
   the socket member must be plumb.
2. **Housing.** Sketch
   `Housing.Skt.WHD.000` on the frame's
   **XY plane**: rectangle centred on the origin, half-extents
   `= <<J-WedgedHalfDovetail-000>>.Housing_Height / 2` and
   `= <<J-WedgedHalfDovetail-000>>.Housing_Width / 2` from the sketch
   axes.

   **Bind these to the joint VarSet, not to the beam's Dims.** Both
   properties already track the beam; reaching into
   `TDim_T.AnchorBeam.001` from inside the post's body is the
   §4.3 violation the strict `cross-timber-dims-reference` rule exists
   for — it survives apply but breaks silently on duplication, where
   the copy keeps driving off the *original* beam.

   **Pocket** `Housing.WHD.000`, outward
   (Reversed as needed), Length
   `= <<J-WedgedHalfDovetail-000>>.Housing_Depth`.
3. **Through mortise.** Sketch
   `Mortise.Skt.WHD.000` on the frame's
   **YZ plane** — the elevation through the footprint centre:
   up-the-post × into-the-post. Driven dimensions:
   - opening height `= <<J-WedgedHalfDovetail-000>>.Tenon_Height + <<J-WedgedHalfDovetail-000>>.Wedge_Depth`
   - reach into the post `= <<J-WedgedHalfDovetail-000>>.Tenon_Length + <<J-WedgedHalfDovetail-000>>.Housing_Depth`
     (overshoots the far face, so the tenon emerges cleanly)
   - the near edge set back `= <<J-WedgedHalfDovetail-000>>.Housing_Depth`
     to the post face
   - the floor's slope as an Angle constraint
     `= 90 ° - <<J-WedgedHalfDovetail-000>>.Dovetail_Angle` off the
     vertical edge — **falling as it goes deeper into the post**, so it
     matches a tenon that is tallest at the tip
   - positioned against the footprint via
     `= <<J-WedgedHalfDovetail-000>>.Housing_Height / 2` from the frame
     centre, which puts the mortise floor at the footprint's bottom
     edge and lets the surplus rise above the beam

   **Pocket** `Mortise.WHD.000`: Mode
   **Symmetric** (`SideType`, enum index 2 — the `Midplane` boolean is
   deprecated and ignored in 1.1), Length
   `= <<J-WedgedHalfDovetail-000>>.Tenon_Thickness`. The sketch plane
   is mid-footprint, so the slot centres on the beam's width.

---

## Part D — tenon side, on `T.AnchorBeam.001`

Removal regions, not an island: the tenon touches the section boundary
at the top face (finding #14).

**Build both frames before any sketch** — every sketch below lands on
one of them.

1. **Landing frame**
   `Tail.Lcs.WHD.000`: FlatFace on
   the beam's `XY_Plane` (end A), **all offsets zero**.

   This frame sits at the section *corner*, which looks wrong next to
   the post's centred frame — it is not the frame that aligns. Leave it
   at zero: end-B placement rewrites its `Base.z` to `Dims.Length`, so
   any offset you put here is discarded when the joint is applied to
   the far end. The frame that meets the post is the mate frame, D.2.
2. **Mate frame**
   `Mate.Lcs.WHD.000`: "XY on plane"
   on the landing frame's **XY plane** child, offsets
   - `Base.x = <<TDim_T.AnchorBeam.001>>.Width / 2`
   - `Base.y = <<TDim_T.AnchorBeam.001>>.Depth / 2`
   - `Base.z = <<J-WedgedHalfDovetail-000>>.Tenon_Length`

   No rotation. Origin at the beam's section centre on the shoulder
   plane — which is exactly where the post's landing frame sits when
   the joint is engaged. **This is the frame that aligns**, and it is
   what makes Preview Mated Joint and auto-assembly work; without it
   `engagement_placement` returns None and applying the template cuts
   the joinery but seats nothing.
3. **Cheek cuts (plan).** Sketch
   `Cheeks.Skt.WHD.000` on the
   frame's **XZ plane**: centreline construction line at
   `= <<TDim_T.AnchorBeam.001>>.Width / 2`, two removal
   rectangles flanking the tenon — outer edges on the section boundary
   (`= <<TDim_T.AnchorBeam.001>>.Width / 2` from the centreline),
   inner edges at
   `= <<J-WedgedHalfDovetail-000>>.Tenon_Thickness / 2`, both spanning
   the stick axis from the end to
   `= <<J-WedgedHalfDovetail-000>>.Tenon_Length`.
   **Pocket** `Cheeks.WHD.000`:
   Through all, Symmetric.
4. **Dovetail underside.** Sketch
   `TailSlope.Skt.WHD.000` on the
   **landing frame's YZ plane** (not the body's origin plane — a sketch
   on the body plane will not follow the frame when the joint is
   re-placed). One removal region under the tenon, bounded by the
   stick's underside and the sloped cut: shoulder at
   `= <<J-WedgedHalfDovetail-000>>.Tenon_Length` from the end, and an
   Angle constraint `= <<J-WedgedHalfDovetail-000>>.Dovetail_Angle`
   sloping so the cut **deepens toward the shoulder** — leaving the
   tenon full-depth at the tip.
   **Pocket** `TailSlope.WHD.000`:
   Through all across the full width.

---

## Part E — verification

1. Pose the beam seated, or run Preview Mated Joint.
2. Clipping plane through the joint, side orthographic view. Check: the
   sloped faces meet along their full length; the mortise surplus is
   open above the beam's top face; the tip protrudes
   `Tenon_Length − (post Width − Housing_Depth)` = 2 in at defaults.
3. Parametric shakedown: `Dovetail_Angle` → 7° (mortise floor and tenon
   underside re-slope together); the beam's `Depth` (housing, footprint
   and tenon height all follow); `Wedge_Depth` (only the mortise top
   moves); `Joint_Station` (everything travels). Undo all.
4. Lint, then commit.

## Tooling notes

- **Apply the mortise role to a vertical member only.** Nothing in the
  tools enforces this — the placement machinery is orientation-blind by
  design — so it is on the person applying the joint. Faces 1–4 are all
  safe on a post, because the landing frame's Y stays up the stick
  whichever face it lands on; what is never safe is choosing a girt or
  beam for the mortise role.
- Post role: faces 1–4. Hand does not apply — `Template_Handed` false,
  so the dialog hides the option and apply refuses a mirrored request.
- Beam role: end A or B. The mate frame carries no authored rotation,
  so the end-B seat flip applies cleanly.
- The severing and footprint pre-flights have little to grab on this
  template (no setback pair, no width-named mortise parameter). The
  insertion relation in Part B is the working bound until
  template-declared constraints land (roadmap).
