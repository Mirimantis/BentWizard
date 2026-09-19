# BentWizard

A timber framing workbench for FreeCAD 1.1.1: Mill Rule layout, subtractive joinery, and — the governing rule — **all geometry stays native**. Everything the workbench produces is ordinary FreeCAD (Sketches, Part Design features, datums, Assembly joints) and remains fully hand-editable with the workbench uninstalled.

This is a from-scratch rewrite; an earlier attempt that generated custom-coded geometry is kept only as a record of lessons learned.

## Status

- **Phase 0 — manual workflow definition: complete.** The joinery workflow (parametric timbers, housed mortise & tenon, housed dovetail, pegs/drawbore, assembly, TechDraw sheets, cut list) was proven by hand across twelve modeling sessions. The session files were retired in September 2026 once the rev-2 workbench replaced them; `docs/phase0-friction-findings.md` is what they taught.
- **Phase 1 — joint library & Apply-Joint tool: started.** First piece: a pure-Python model linter (`python -m freecad.bentwizard.linter <file.FCStd>`) implementing the workflow document's strict and advisory rules by reading FCStd files directly — no FreeCAD required. Next: the Apply-Joint tool, which reproduces the proven manual recipes programmatically.

## Documentation

- [Roadmap](docs/bentwizard-roadmap.md) — phases 0–5 and governing rules
- [Rev-2 workflow](docs/bentwizard-workflow-rev2.md) — the mechanism the workbench implements (timber-owned datums, cutter/adder joints copied from templates)
- [Phase 0 workflow](docs/bentwizard-phase0-workflow.md) — the superseded manual recipes, kept for their pegs, drawing and cut-list practice
- [Friction findings](docs/phase0-friction-findings.md) — what hurt in the manual workflow and the automation each finding implies

## Layout

- `package.xml` + `freecad/bentwizard/` — the workbench, in FreeCAD 1.x addon layout
- `docs/` — specification documents, spike records and joinery notes

A portable FreeCAD 1.1.x install is expected outside the repo, as a sibling of the checkout (e.g. `..\FreeCAD_1.1.3-Windows-x86_64-py311\`), for development and testing. The exact path and patch version vary per machine. It is not part of the repository (kept outside so it isn't exposed through the `Mod\BentWizard` dev-install junction). Run `scripts\dev-install.ps1 main` once per machine to create that junction.

## License

[LGPL-2.1-or-later](LICENSE), the same license as FreeCAD and its bundled workbenches.
