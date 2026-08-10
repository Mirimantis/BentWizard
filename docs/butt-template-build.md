# Building `library/Joint_Butt.FCStd` — step-by-step

A butt joint: the squared end of one timber landing flush on a chosen
face of another, at a chosen station, with **no joinery cut at all**.
The connection is made outside the wood — a bracket, a strap, a plywood
gusset — so the model's job is to hold the two sticks in the right
relationship and publish the layout numbers, not to cut anything.

It has two purposes, and both matter:

1. **A real project joint.** Bracketed and gusseted connections are
   ordinary in the frames this workbench is for, and until now there was
   no way to declare one.
2. **The starter skeleton for authoring new templates.** It carries
   every piece a template needs — two timbers with their Dims, a landing
   frame, a mate frame, `Frame_Role` on both, a joint VarSet, a
   companion layout VarSet — and nothing else. Author a new joint by
   copying this and adding geometry, **never** by copying a template
   that already has joinery in it (finding #12, one level up: the
   phantom-feature problem applies to templates as much as to timbers).

It is also the proving ground for the **frames-at-face** convention
(August 2026). With `Stick_Allowance_FTF = 0` the mate frame lands
exactly on the stick's end, so a driven `Length` must come out equal to
the clear-span distance to the last decimal — any discrepancy in the
convention shows up here immediately, with no joinery to hide behind.

Values below are imperial example data; enter them per your FreeCAD unit
schema.

**Acceptance:** zero strict findings **and zero advisories**. Unlike the
joinery templates there is no `caution-threshold` exemption — there are
no cuts to be cautious about, so this file must be completely silent.

## How to lint

**Save in FreeCAD first** — the linter reads the saved `.FCStd`, not the
open document. Then, from the repo root:

```bash
python -m freecad.bentwizard.linter library/Joint_Butt.FCStd
```

If `python` isn't on your PATH, FreeCAD's bundled interpreter works —
the linter is pure Python and never imports FreeCAD:

```bash
"C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe" -m freecad.bentwizard.linter library/Joint_Butt.FCStd
```

Findings print as `[rule] Label (InternalName): message`, strict first;
exit code 1 means strict findings remain. Lint after each part.

Template-wide conventions:

- Template placeholders use the production naming scheme with serial
  `000`/`001`: bodies `T.Post.001` / `T.Girt.001`, joint VarSet
  `J-Butt-000`. Apply-Joint rewrites all of them; the instance kind
  token comes from the file stem (`Joint_Butt` → `J-Butt-001`).
- **Separators: `_` after a kind prefix, your choice inside a label —
  except the joint VarSet.** The `_` in `TDim_`, `Layout_`, `Group_`,
  `Project_`, `Order_` is a namespace separator marking where the prefix
  ends and the owner's own label begins, so `TDim_T.Post.001` is correct:
  fixed prefix, free-form owner. Within a label, `-` `.` `_` and space
  are equal (permissive naming, July 2026). The exception is the **joint
  instance label, which needs both hyphens** — `J-Butt-000`, not
  `J-Butt.000` — because it is not a name you keep: Apply-Joint discards
  it and regenerates `J-<Kind>-<serial>` from the file stem via
  `naming.joint_label()`. The companion follows its joint, so
  `Layout_J-Butt-000`. Rule of thumb: **names you keep are permissive,
  names the tool regenerates have a fixed shape.**
- Joint features are descriptive-first, `<Descriptive>[.<TypeTag>].BUT.000`.
  Here that is only the three frames. Declare `Template_Abbrev = "BUT"`
  on the joint VarSet; Apply-Joint rewrites exactly that suffix.
- Feature labels must be **unique across both halves** — the timber name
  no longer separates them.
- Every frame carries a `Frame_Role` string property, `Landing` or
  `Mate`.
- Pick every attachment reference **from the model tree, never the 3D
  view** (finding #8), and never a solid face.
- **"XY on plane" is the GUI's name for the `FlatFace` attachment mode**
  (`MapMode` index 5, which is what lands in `Document.xml`). Selecting a
  single plane and creating the datum auto-selects it, so the Attachment
  panel showing *"Attached with mode XY on plane"* means it is already
  right — read the label as the instruction it is: put the new object's
  XY plane onto the referenced plane.
- **Double-click the target body to activate it before creating any
  datum** — root-level strays cannot be attached to from body sketches.

---

## Part A — the two timbers

Use **New Timber** twice in an empty document saved as
`library/Joint_Butt.FCStd` (it creates the Body, the nested
`TDim_<label>` VarSet with tooltips, the section sketch, and the stick
pad):

| Timber | Role | Label | Width | Depth | Length |
|---|---|---|---|---|---|
| Post | anchor (landed on) | `T.Post.001` | 10 in | 8 in | 96 in |
| Girt | entering (lands) | `T.Girt.001` | 6 in | 8 in | 96 in |

A **non-square post is deliberate**: `Grid_Setback` is half the post's
dimension *along the joint normal*, which is Width on faces 2/4 and
Depth on faces 1/3. With a square post that distinction is invisible and
a face-swap error cannot be seen.

**Checkpoint A:** lint — zero findings.

---

## Part B — the companion layout VarSet

**Build the companion first.** It is the pure source the joint VarSet
consumes from, and authoring it first makes that direction obvious; it
is also the order Apply-Joint creates them in.

Create a Std Group labeled `TimberJoints` at the document root (pure
organization — inert in a template, and it is where production documents
keep joint VarSets before assimilation). Inside it, a **VarSet** labeled
`Layout_J-Butt-000`.

| Property | Type | Group | Value | Tooltip |
|---|---|---|---|---|
| `VarSet_Role` | `App::PropertyString` | `Template` | `Layout` | Marks this as the joint's companion layout VarSet: the pure source holding the length-consuming parameters. Tools resolve the companion through this, never by label. |
| `Grid_Setback` | `App::PropertyDistance` | `Layout` | *expr* `= <<TDim_T.Post.001>>.Width / 2` | Half the landed timber's thickness along the joint normal — the term that converts a clear span to an on-center distance. |
| `Stick_Allowance_FTF` | `App::PropertyDistance` | `Layout` | `0 in` | Stick this joint consumes beyond the landed timber's face, along the entering timber's axis. Zero for a butt joint: the squared end stops at the face. |
| `Stick_Allowance_OC` | `App::PropertyDistance` | `Layout` | *expr* `= Stick_Allowance_FTF - Grid_Setback` | Stick this joint consumes beyond the landed timber's centerline, along the entering timber's axis. Negative when the stick stops short of the grid line. |

`Stick_Allowance_FTF` stays a **literal**, not an expression, on purpose:
it is the one field an author replaces when they build a real joint on
this skeleton (`= Tenon_Length + Housing_Depth`, or whatever their
joinery sums to), and as a literal it appears as an editable row in the
Apply dialog — which is also what lets a framer dial in a deliberate
standoff for a bracketed connection.

Both allowances are `App::PropertyDistance`, not `Length`: `_OC` is
routinely negative, and a `Length` clamps at zero.

**Checkpoint B:** lint — zero findings.

---

## Part C — the joint VarSet

Inside the same group, a **VarSet** labeled `J-Butt-000`.

| Property | Type | Group | Value | Tooltip |
|---|---|---|---|---|
| `Joint_Station` | `App::PropertyLength` | `Joint` | 48 in | Distance from the landed timber's end A (Z=0) to the lower edge of the landing footprint, along its length. |
| `Landing_Width` | `App::PropertyLength` | `Joint` | *expr* `= <<TDim_T.Girt.001>>.Width` | Width of the landing footprint across the landed timber's face; tracks the entering timber's Width. Override with a literal to hold the footprint off the entering timber's size. |
| `Landing_Height` | `App::PropertyLength` | `Joint` | *expr* `= <<TDim_T.Girt.001>>.Depth` | Height of the landing footprint up the landed timber's face; tracks the entering timber's Depth. Override with a literal to hold the footprint off the entering timber's size. |
| `Stick_Allowance_FTF` | `App::PropertyDistance` | `Joint` | *expr* `= <<Layout_J-Butt-000>>.Stick_Allowance_FTF` | Stick consumed beyond the landed timber's face; positions the mate frame. Authored on the companion layout VarSet — edit it there. |
| `Template_Abbrev` | `App::PropertyString` | `Template` | `BUT` | Template metadata: the short token this joint's feature labels carry. |
| `Template_Handed` | `App::PropertyBool` | `Template` | `false` | Template metadata: false = the joint is fully symmetrical about its centerline, so hand selection does not apply. |

Template metadata is recognized by the `Template_` **name prefix**, not
by its group.

Three things here are load-bearing and easy to get wrong:

- **`Landing_Width` / `Landing_Height` are the §4.3 junction.** The
  landing frame lives in the post's body and must not reference the
  girt's Dims directly — that is the strict `cross-timber-dims` rule.
  Cross-timber coupling goes through the joint VarSet, always.
- **`Stick_Allowance_FTF` must exist on the joint VarSet**, even though
  the companion is where the value is authored. `joint_members` finds a
  joint's parts by closing over the literal token `<<J-Butt-000>>` in
  expressions, and `<<Layout_J-Butt-000>>` does **not** contain that
  token. A mate frame bound straight to the companion would silently
  stop being part of the joint — no Preview, no assembly seat, no
  handle, and `rule_frame_role` would pass without ever checking it.
  Routing through this consumed copy is what keeps the frame visible.
- **`Template_Handed` is false** because a squared end butting a face is
  symmetrical about its centerline; there is no hand to choose.

**Checkpoint C:** lint — zero findings (junction bindings to a mating
timber's Dims are the sanctioned §4.3 pattern, and the linter exempts
them).

---

## Part D — the landing frame, on `T.Post.001`

Activate `T.Post.001`. **Create coordinate system**
`Bearing.Lcs.BUT.000`, attached **"XY on plane" to the post's `YZ_Plane`**
(the canonical Face-4 authoring plane; tree-select it), then:

| Offset | Expression | Meaning |
|---|---|---|
| `Base.x` | `= <<TDim_T.Post.001>>.Depth / 2` | center of the face, across |
| `Base.y` | `= <<J-Butt-000>>.Joint_Station + <<J-Butt-000>>.Landing_Height / 2` | center of the landing footprint, up the post |
| `Base.z` | `= <<TDim_T.Post.001>>.Width` | **the face itself** |

Add a string property `Frame_Role` (group `TimberJoint`) with the value
`Landing`, and this tooltip: *This frame's role in the timber joint:
'Landing' (where the joint sits on this timber) or 'Mate' (the pose this
timber takes when seated).*

Expected axes — verify in the 3D view: frame **X across the post's
depth**, frame **Y up the post**, frame **Z out of the wood**. The frame
origin sits on the post's face, dead center of where the girt will land.

`Base.z` is the whole point of the convention change. Previously a
housed joint set this to `Width - Housing_Depth` — the bearing plane —
which made the frame's position depend on the housing, and made the
clear-span allowance a piece of arithmetic every template had to get
right on its own. On the face, the mate frame's offset from the stick
end simply **is** the allowance.

Every offset must be an **expression**, never a typed number: a literal
nonzero offset trips the `stale-attachment-offset` advisory, and more
importantly it would not follow a section change.

**Checkpoint D:** lint — zero findings.

---

## Part E — the girt's frames, on `T.Girt.001`

Activate `T.Girt.001`. **Order matters** — build the end frame first,
because the mate frame attaches to it, and because `TemplateSpec` takes
the **first** LCS in the body's feature order as the role's landing
frame and reads its attachment plane to decide whether the role gets
End A/B selection or Face 1–4 selection.

1. **End frame** `End.Lcs.BUT.000`: attach **"XY on plane" to the girt's
   `XY_Plane`** (end A), **all offsets zero** — frame axes are the body
   axes there. Add `Frame_Role = Landing` (same property and tooltip as
   Part D).

   It carries no expressions of its own, and does not need any: it
   becomes part of the joint through the mate frame that attaches to it,
   which `joint_members` reaches by closing over attachment supports.

2. **Mate frame** `Mate.Lcs.BUT.000`: **Create coordinate system**,
   attach **"XY on plane" to `End.Lcs.BUT.000`'s XY plane** — tree-select
   the frame's child plane so the reference is recorded as a
   sub-element. Selecting the child plane **object** instead trips the
   strict `lcs-child-plane-reference` rule (it resolves to an identity
   placement, so the frame silently lands at the body origin).

   | Offset | Expression |
   |---|---|
   | `Base.x` | `= <<TDim_T.Girt.001>>.Width / 2` |
   | `Base.y` | `= <<TDim_T.Girt.001>>.Depth / 2` |
   | `Base.z` | `= <<J-Butt-000>>.Stick_Allowance_FTF` |

   Add `Frame_Role = Mate`.

   `Base.z` resolves to zero here, which is correct and is exactly what
   makes this template the clean test of the convention — but it must
   still be written as the **expression above**, not left as a typed 0.
   An undriven offset would not follow an author's edit once they build
   real joinery on this skeleton.

Verify: the mate frame's origin sits at the girt's section center on its
end-A face, axes parallel to the girt's own (X across Width, Y across
Depth, Z along the stick, away from end A).

**Checkpoint E:** lint — zero strict **and zero advisory** findings. This
is the acceptance bar; the file ships only when it is silent.

---

## Part F — inspection pose and verification

1. Set `T.Girt.001`'s Body Placement so the girt sits as-assembled —
   its end A flat on the post's face at the station (finding #7a). Body
   Placement is display-only; it does not affect the feature tree or the
   linter.

   Do not eyeball it. In the Python Console:

   ```python
   from freecad.bentwizard import apply_joint
   doc = App.ActiveDocument
   vs = doc.getObjectsByLabel("J-Butt-000")[0]
   mover, anchor, pl = apply_joint.engagement_placement(vs)
   mover.Placement = pl
   doc.recompute()
   ```

   This is the same `engagement_placement` Preview Mated Joint and
   Assemble Timbers use, so the inspection pose is the production pose:
   the seat is derived from the frames rather than approximated, and a
   frame that is wrong looks wrong instead of merely looking plausible.

   To read the misfit as a number (expect ~1e-14 mm, i.e. float noise):

   ```python
   f = apply_joint.joint_role_frames(vs)
   print((f[mover]["mate"].getGlobalPlacement().Base
          - f[anchor]["landing"].getGlobalPlacement().Base).Length)
   ```

2. Verify per §5: a top and a side orthographic view (never wireframe
   when profiles align in two axes), and Measure between the girt's end
   face and the post's face — expect **0**.
3. Parametric shakedown:
   - change `Joint_Station` — the girt travels up and down the post
   - change `TDim_T.Girt.001.Depth` — the landing footprint's height
     follows, so the frame stays centered on the girt
   - change `TDim_T.Post.001.Width` — the landing frame stays on the
     face as the post fattens, and `Grid_Setback` follows
   - set `Layout_J-Butt-000.Stick_Allowance_FTF` to `1 in` — the mate
     frame lifts off the end, i.e. the girt would seat 1 in *into* the
     post. Put it back to 0.

   **Re-run step 1's snippet after each of these.** Body Placement is a
   plain literal — it does not follow a parameter edit — so the girt
   keeps its old pose while the frames move, and the gap you are looking
   at is stale rather than real.

   Undo all, or close without saving and re-verify defaults.
4. Final lint (strict **and** advisory silent), then the test suite:

```bash
"C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe" -m unittest discover -s tests
```

---

## Part G — what to check once it applies

These are the behaviors this template exists to prove, and they are the
GUI test before it is committed:

- **The seat, across the placement matrix.** Apply it at faces 1–4 on
  the post and ends A and B on the girt — eight combinations. Each time
  the girt's squared end must sit flat on the chosen post face at the
  station, with no overlap and no gap. Faces 1 and 3 exercise the
  `Grid_Setback` face swap; faces 2 and 3 plus end B exercise the mate
  parity flip.
- **The handle.** One appears at the joint, its context menu works, and
  Remove Joint takes the handle, the joint VarSet and the companion.
- **Preview Mated Joint** shows the girt's ghost flush on the face.
- **Drive Length from Layout Distance.** Put a girt between two posts
  with a butt joint at each end and drive its `Length` on the clear-span
  basis. Because both allowances are zero, the driven `Length` must
  equal the authored distance **exactly** — that is the convention check
  with nothing to hide behind. On the on-center basis it must come out
  at the distance minus half of each post's dimension along the joint
  normal (Width on faces 2/4, Depth on faces 1/3).
- **The invariance that matters.** With `Length` driven, changing
  `Stick_Allowance_FTF` must re-cut the stick and leave both posts where
  they are. With `Length` typed as a literal instead, the same edit
  moves a post — that is expected, and it is the reason driving exists.
