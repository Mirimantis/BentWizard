# Joint template library

One ordinary `.FCStd` file per joint template. A template contains:

- one VarSet — the joint's parameter schema (the apply dialog is generated
  from it; tooltips mandatory on every property),
- per-role feature stacks (e.g. mortise side / tenon side) built to the
  Phase 0 workflow conventions,
- non-geometric schedule data (e.g. `Peg_Count`) as VarSet properties.

Templates must lint clean (strict **and** advisory):
`python -m freecad.bentwizard.linter library/<template>.FCStd`

First template: the housed mortise & tenon — build recipe in
[docs/mt-template-build.md](../docs/mt-template-build.md).

A "Save as joint template" tool will validate and register user-authored
joints here; a user-override directory is planned alongside the Phase 3
reference-data system. Manifest format is an open item (workflow doc §8).
