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

A "Save as joint template" tool will validate and register user-authored
joints here; a user-override directory is planned alongside the Phase 3
reference-data system. Manifest format is an open item (workflow doc §8).
