# Joint template library

One ordinary `.FCStd` file per joint template. A template contains:

- one VarSet — the joint's parameter schema (the apply dialog is generated
  from it; tooltips mandatory on every property),
- optionally a second VarSet marked `VarSet_Role = "Layout"` — the
  companion holding the length-consuming parameters authoritatively, so
  a timber's `Length` can derive from a layout distance,
- per-role feature stacks (e.g. mortise side / tenon side) built to the
  Phase 0 workflow conventions, each hanging off one landing-frame LCS
  (side-landing roles authored on Face 4, **frame origin on the timber's
  face** at the landing footprint's center — never inset to a housing's
  bearing plane; end-landing roles on end A),
- a **mate frame** LCS on each role that enters its mate, coinciding
  axis-for-axis with the mating role's landing frame when engaged
  (drives Preview Mated Joint and assembly). Because the landing frame
  is on the face, the mate frame's offset from the stick end **is** the
  clear-span allowance — place it at `Stick_Allowance_FTF`, and read it
  from the *joint* VarSet's consumed copy, never from the companion
  directly (`joint_members` closes over the `<<J-…>>` token, which
  `<<Layout_J-…>>` does not contain — a frame bound straight to the
  companion silently stops being part of the joint),
- non-geometric schedule data (e.g. `Peg_Count`) as VarSet properties.

Templates must lint clean (strict **and** advisory):
`python -m freecad.bentwizard.linter library/<template>.FCStd`

Build recipes (one doc per template; the MT doc also documents the
baseline process the others build on):

- Butt joint — a squared end landing flush on a face at a chosen
  station, no joinery. The **starter skeleton** to author new templates
  from (finding #12: never copy a jointed template), and a valid project
  joint in its own right for bracketed or gusseted connections —
  [docs/butt-template-build.md](../docs/butt-template-build.md)
  (`Joint_Butt.FCStd`)
- Housed mortise & tenon —
  [docs/mt-template-build.md](../docs/mt-template-build.md)
  (built: `Joint_HousedMT.FCStd`)
- Housed dovetail — joist dropped into a **horizontal** girt's top
  face, tops flush —
  [docs/housed-dovetail-template-build.md](../docs/housed-dovetail-template-build.md)
- Wedged half-dovetail (anchor-beam through tenon) — beam into a
  **vertical** post; the socket role must be a post or other vertical
  member —
  [docs/wedged-half-dovetail-template-build.md](../docs/wedged-half-dovetail-template-build.md)
  (`Joint_WedgedHalfDovetail.FCStd` — modeled, finishing the lint
  cleanup; the recipe is written from the built file)
- Brace mortise & tenon (parametric angle, default 45°) —
  [docs/brace-mt-template-build.md](../docs/brace-mt-template-build.md)

## Authoring your own

**"Landing frame" and "mate frame" are roles, not labels.** Nothing in
the tree is called "landing frame" — the role lives in each frame's
`Frame_Role` property, and the label says what the frame is on its
timber (`Bearing.Lcs.BUT.000` and `End.Lcs.BUT.000` are `Joint_Butt`'s
two landing frames; `Mate.Lcs.BUT.000` is its mate frame). Cuts hang off
the landing frame in their own body; nothing may attach to a mate frame.

**New Joint Template** creates a file from a starter skeleton (a
template carrying no joinery — `Joint_Butt.FCStd` today; the tool finds
starters structurally, so anything jointless qualifies) and opens it
ready to model the cuts in. Never copy a template that already has cuts
in it: those come along as phantom features (finding #12).

**Save as Joint Template** writes the open authoring document into your
template folder and reports what validation found. It validates but
never refuses — the report is a checklist, and a template with findings
is saved anyway. The bar is the same one this directory's files clear:
the linter's rules (`linter.py`), the skeleton every template carries
(`template_check.py` — the completeness half the linter cannot see), the
file-stem contract, and a real `TemplateSpec` load.

Two folders are searched, the user's ahead of this one, so a locally
revised copy of a shipped joint shadows it rather than appearing twice:

- **your template folder** — `<FreeCAD user app data>/BentWizard/library`
  by default, changed by saving a template elsewhere and accepting the
  offer (stored as `TemplateDir` under
  `BaseApp/Preferences/Mod/BentWizard`),
- **this shipped library**.

The **file stem is the joint's name**: `Joint_BraceMT.FCStd` makes every
joint applied from it `J-BraceMT-<serial>`, which is what reaches the
cut list. Saving offers to relabel the document's joint VarSet, its
companion and every feature suffix to match — safe, because FreeCAD
re-points every `<<Label>>` expression when an object is relabeled.

Manifest format is still an open item (workflow doc §8).
