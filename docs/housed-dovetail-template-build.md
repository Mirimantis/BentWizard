# Building `library/Joint_HousedDovetail.FCStd` — step-by-step

A housed, dropped-in dovetail between a girt (socket role) and a joist
or tie (tail role), tops flush. **Both members are horizontal** — the
joist is lowered into the girt's top face. Do not confuse this with the
wedged half-dovetail, whose socket role must be a post: same family,
different purpose, different template. The joist's end is shaped into a flared
tail on its upper portion; the girt gets a full-footprint housing in its
side face plus a flared socket cut down from its top face. The joist
drops in from above: vertical load bears on the housing ledger and the
socket floor, withdrawal is resisted by the flared flanks. This is
Phase 0's DT1 rebuilt from scratch under the updated conventions
(landing frames, mate frame, permissive `T-`/`J-` naming,
`Template_Handed` metadata). Values are imperial example data; enter
them per your FreeCAD unit schema.

**Acceptance:** zero strict findings and no advisories other than
`caution-threshold`.

## How to lint

**Save in FreeCAD first** — the linter reads the saved `.FCStd`, not
the open document. Then, from the repo root (or this worktree):

```bash
python -m freecad.bentwizard.linter library/Joint_HousedDovetail.FCStd
```

If `python` isn't on your PATH, FreeCAD's bundled interpreter works —
the linter is pure Python and never imports FreeCAD:

```bash
"C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe" -m freecad.bentwizard.linter library/Joint_HousedDovetail.FCStd
```

Findings print as `[rule] Label (InternalName): message`, strict
first; exit code 1 means strict findings remain. Lint after each part
— checkpoints below.

Template-wide conventions (updated since the MT build; supersede that
doc's bent-0 placeholders):

- Template placeholder names use the production scheme with serial
  `000`/`001`: bodies `T-Girt-001` / `T-Joist-001`, joint VarSet
  `J-HousedDovetail-000`. Apply-Joint rewrites all of them on apply;
  the instance kind token comes from the file stem
  (`Joint_HousedDovetail` → `J-HousedDovetail-001`).
- Joint features are body-qualified:
  `<TimberLabel>_<Feature>_<JointLabel>`.
- Pick every attachment reference **from the model tree, never the 3D
  view** (finding #8), and never a solid face.
- **Double-click the target body to activate it before creating any
  datum or sketch** — root-level strays cannot be attached to from body
  sketches; fix by dragging into the body.
- The rebuilder clones only **lines and circles** and the standard
  constraint set — no arcs, splines, or sketch Points. Everything below
  respects that.
- No shoulder datums: assembly and preview run on the
  JointFrame/MateFrame pair, so the MT template's Part D.3 datum has no
  equivalent here.

---

## Part A — the two timbers

Use **New Timber** twice in an empty document saved as
`library/Joint_HousedDovetail.FCStd` (it creates the Body, the nested
`TimberDims_<label>` VarSet with tooltips, section sketch, and stick
pad — all of the MT recipe's Part A):

| Timber | Label | Width | Depth | Length |
|---|---|---|---|---|
| Girt (socket role) | `T-Girt-001` | 8 in | 10 in | 96 in |
| Joist (tail role) | `T-Joist-001` | 6 in | 8 in | 96 in |

Differing sections keep the roles readable and surface edge cases.
Installed orientation: Width horizontal, Depth vertical for both — the
joist crosses the girt at right angles, tops flush.

**Checkpoint A:** lint — zero findings.

---

## Part B — the joint VarSet

Create a Std Group labeled `TimberJointVars` (production documents keep
joint VarSets there; templates match). Inside it, one **VarSet** labeled
`J-HousedDovetail-000`. Properties in group `Joint` except where noted;
all `App::PropertyLength` except `Template_Handed`.

| Property | Value | Tooltip |
|---|---|---|
| `Joint_Station` | 48 in | Distance from the girt's end A (Z=0) to the near edge of the housing opening, along the girt. |
| `Housing_Width` | *expr* `= <<TimberDims_T-Joist-001>>.Width` | Housing opening along the girt; tracks the joist's Width. Override with a literal to hold it off the joist size. |
| `Housing_Height` | *expr* `= <<TimberDims_T-Joist-001>>.Depth` | Housing opening down the girt's face from its top face; tracks the joist's Depth. Override with a literal to hold it off the joist size. |
| `Housing_Depth` | 1/2 in | Depth of the housing into the girt's landed face; its ledger carries the joist's underside. |
| `Tail_Length` | 4 in | Tail length from the joist's end A to the shoulder plane; also the socket's reach beyond the housing floor. |
| `Tail_Depth` | 3 in | Vertical depth of the tail, measured down from the flush top faces; the socket floor sits this far below the girt's top. |
| `Tail_Width_Root` | 3 in | Tail width across the joist at the shoulder (the narrow end), centered on the joist's width. |
| `Tail_Width_Tip` | 4 in | Tail width across the joist at its end A (the wide end); must exceed Tail_Width_Root for the flanks to hold. |
| `Template_Handed` | `false` (`App::PropertyBool`) | Template metadata: false = joint is fully symmetrical about its centerline, so hand selection does not apply. |

Template metadata is recognized by the `Template_` **name prefix**, not
by its property group — put it in whichever group reads best.

The dovetail geometry is defined from the centerline (root and tip
widths, both centered), which is exactly why `Template_Handed` is
false. Rename the VarSet immediately after creating it.

**Checkpoint B:** lint — zero findings (junction bindings to a mating
timber's Dims are the sanctioned §4.3 pattern).

---

## Part C — socket side, on `T-Girt-001`

One landing frame carries all placement; sketches are frame-local and
reference only the joint VarSet (plus the girt's own Dims).

1. **Landing frame** `T-Girt-001_JointFrame_J-HousedDovetail-000`
   (datum coordinate system): attach FlatFace to the girt's `YZ_Plane`
   (the canonical Face-4 authoring plane), offset expressions:
   - `Base.x = <<TimberDims_T-Girt-001>>.Depth - <<J-HousedDovetail-000>>.Housing_Height / 2`
     — footprint center sits half the opening below the girt's top face
   - `Base.y = <<J-HousedDovetail-000>>.Joint_Station + <<J-HousedDovetail-000>>.Housing_Width / 2`
   - `Base.z = <<TimberDims_T-Girt-001>>.Width - <<J-HousedDovetail-000>>.Housing_Depth`
     — the bearing (housing-floor) plane
   Expected axes (verify in the 3D view): frame X **up the girt's
   depth** (vertical), frame Y **along the girt** (the station axis),
   frame Z **out of the wood**. Unlike the MT post, the "across the
   face" axis is vertical here — the joist crosses the girt, so the
   footprint's vertical extent is `Housing_Height` (along frame X) and
   `Housing_Width` runs along frame Y.
2. **Housing.** Sketch `T-Girt-001_HousingSketch_J-HousedDovetail-000`
   on the frame's **XY plane**: rectangle centered on the origin using
   the sketch axes as centerlines — edges at
   `= <<J-HousedDovetail-000>>.Housing_Height / 2` from origin along
   frame X, `= <<J-HousedDovetail-000>>.Housing_Width / 2` along frame
   Y. The top edge must land exactly on the girt's top face (visual
   check; a profile edge on the section boundary is fine for a pocket —
   only kept islands must stay interior).
   **Pocket** `T-Girt-001_Housing_J-HousedDovetail-000`, direction
   outward, Length `= <<J-HousedDovetail-000>>.Housing_Depth`. Verify
   with a side orthographic view, never wireframe.
3. **Socket.** Sketch `T-Girt-001_SocketSketch_J-HousedDovetail-000` on
   the frame's **YZ plane** (the horizontal plane: along-girt ×
   into-the-wood), then lift it to the girt's top face with an
   attachment-offset **expression** (a literal would trip the
   stale-offset advisory):
   `AttachmentOffset.Base.z = <<J-HousedDovetail-000>>.Housing_Height / 2`
   — if the sketch drops below the footprint center instead of rising
   to the top face, negate the expression. Draw the flared plan-form:
   - centerline construction line along the into-the-wood axis
   - root edge on the bearing-plane trace (sketch position 0 along the
     wood axis), half-widths `= <<J-HousedDovetail-000>>.Tail_Width_Root / 2`
     each side of the centerline
   - tip edge at `= <<J-HousedDovetail-000>>.Tail_Length` into the
     wood, half-widths `= <<J-HousedDovetail-000>>.Tail_Width_Tip / 2`
   - two flank lines closing the trapezoid
   (Half-width constraints off a centerline, never Symmetric — finding
   #13.) The zone between the girt's face and the bearing plane is
   already removed by the housing, so the socket profile starts at the
   bearing trace.
   **Pocket** `T-Girt-001_Socket_J-HousedDovetail-000`, direction
   **down into the girt** (toggle Reversed if it grows upward), Length
   `= <<J-HousedDovetail-000>>.Tail_Depth`. The socket floor lands
   Tail_Depth below the girt's top — the tail's bottom bears there.

**Checkpoint C:** lint — zero strict findings. I verify resolved
frame/sketch placements from the file.

---

## Part D — tail side, on `T-Joist-001`

Removal regions, not an island — the tail touches the section boundary
at the top face, exactly the §4.5 / finding #14 case.

**Build both frames before any sketch** — every sketch below lands on
one of them.

1. **Landing frame** `T-Joist-001_JointFrame_J-HousedDovetail-000`:
   attach FlatFace to the joist's `XY_Plane` (end A), all offsets zero
   (frame axes = body axes).

   This frame sits at the section *corner*, unlike the girt's centred
   landing frame — it is **not** the frame that aligns when the joint
   engages; the mate frame (D.2) is. Leave it at zero offsets: end-B
   placement rewrites its `Base.z` to `Dims.Length`, discarding
   anything you put there.
2. **Mate frame** `T-Joist-001_MateFrame_J-HousedDovetail-000`: attach
   "XY on plane" to the landing frame's **XY plane** child
   (tree-select). Offsets:
   - `Base.x = <<TimberDims_T-Joist-001>>.Width / 2`
   - `Base.y = <<TimberDims_T-Joist-001>>.Depth / 2`
   - `Base.z = <<J-HousedDovetail-000>>.Tail_Length`
   - **Rotation: axis Z, angle 90°** (literal — rotations are exempt
     from the stale-offset advisory). The girt frame's X axis is
     vertical, so the joist's depth axis must turn onto it: after the
     turn, mate X points toward the joist's top face (body +Y), mate Y
     across the width, mate Z along the stick away from the tail.
   Verify: origin at the section center on the shoulder plane
   (3, 4, 4) in. **This is the frame that aligns** — when engaged it
   coincides axis-for-axis with the girt's landing frame, and it is
   what makes Preview and auto-assembly work; without it
   `engagement_placement` returns None and applying the template cuts
   the joinery but seats nothing.
3. **Flank cuts (plan).** Sketch
   `T-Joist-001_TailFlankSketch_J-HousedDovetail-000` on the frame's
   **XZ plane** (the Face-1 reference plane; the plan view of the
   joist). Draw:
   - centerline construction line along the stick at
     `= <<TimberDims_T-Joist-001>>.Width / 2`
   - two removal quadrilaterals flanking the tail: outer edges on the
     section boundary (x = 0 and x = Width), spanning the stick axis
     from the end (0) to `= <<J-HousedDovetail-000>>.Tail_Length`;
     inner (flank) edges from half-width
     `= <<J-HousedDovetail-000>>.Tail_Width_Tip / 2` at the stick end
     to `= <<J-HousedDovetail-000>>.Tail_Width_Root / 2` at the
     shoulder, each dimensioned from the centerline
   **Pocket** `T-Joist-001_TailFlanks_J-HousedDovetail-000`: Through
   all, direction into the timber (the sketch lies on the reference
   face, so one direction crosses the full depth; toggle Reversed if it
   cuts into air).
4. **Underside cut.** Sketch
   `T-Joist-001_TailUndersideSketch_J-HousedDovetail-000` on the
   frame's **YZ plane** (the Face-2 reference plane; the elevation):
   one rectangle with a corner at the origin, spanning the stick axis
   from 0 to `= <<J-HousedDovetail-000>>.Tail_Length` and the depth
   from 0 (the underside) to
   `= <<TimberDims_T-Joist-001>>.Depth - <<J-HousedDovetail-000>>.Tail_Depth`.
   What remains above it is the tail, hanging from the flush top face.
   **Pocket** `T-Joist-001_TailUnderside_J-HousedDovetail-000`: Through
   all, direction across the full width.

**Checkpoint D:** lint — zero strict findings.

---

## Part E — inspection pose and verification

1. Set `T-Joist-001`'s Body Placement so the joist sits seated — tail
   in the socket, tops flush (finding #7a; display-only). Optionally
   run Preview Mated Joint on `J-HousedDovetail-000` instead and
   compare.
2. Verify per §5: top and side orthographic views; clipping plane
   through the socket; Measure — flank faces touch (0 engaged), joist
   underside on the housing ledger, tail bottom on the socket floor.
3. Parametric shakedown: change `TimberDims_T-Joist-001.Depth` to
   10 in — housing and footprint must deepen and the frame must stay on
   the girt's top face; change `Joint_Station` — everything travels;
   change `Tail_Width_Tip` — socket and tail flanks move in lockstep;
   change `Tail_Depth` — socket floor and underside cut track. Undo
   all.
4. Final lint, then commit.

## Tooling notes (what Apply-Joint supports today)

- Girt role: authored on the canonical Face 4; **face 2** (the opposite
  side face) is the meaningful alternative. Faces 1/3 would put the
  flush-top geometry on the girt's top/bottom faces — geometrically
  nonsensical for this template, and nothing stops you yet: don't.
- Joist role: end A or B. The end-B seat flip composes with this
  template's authored 90° mate-frame turn (`mate_flip_rotation`,
  unit-tested); this template is its first real exercise, so verify
  seating in the viewport on first end-B use.
- Hand: not applicable — `Template_Handed` false, and the apply dialog
  hides the hand option for this template.
- No `Tenon_*`/`Housing_*` name pairing means the apply pre-flight's
  footprint check has nothing to grab here; parameter bounds for
  dovetails arrive with template-declared constraints (roadmap). Until
  then: keep Tail_Width_Tip comfortably under the joist width and
  Tail_Length + Housing_Depth under the girt width.
