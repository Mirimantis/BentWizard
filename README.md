# BentWizard

A timber framing workbench for FreeCAD 1.1.1: Mill Rule layout, subtractive joinery, and — the governing rule — **all geometry stays native**. Everything the workbench produces is ordinary FreeCAD (Sketches, Part Design features, datums, Assembly joints) and remains fully hand-editable with the workbench uninstalled.

This is a from-scratch rewrite; an earlier attempt that generated custom-coded geometry is kept only as a record of lessons learned.

## Status

- **Phase 0 — manual workflow definition: complete.** The joinery workflow (parametric timbers, housed mortise & tenon, housed dovetail, pegs/drawbore, assembly, TechDraw sheets, cut list) was proven by hand across twelve modeling sessions. Session artifacts live in `phase0/`.
- **Phase 1 — joint library & Apply-Joint tool: started.** First piece: a pure-Python model linter (`python -m freecad.bentwizard.linter <file.FCStd>`) implementing the workflow document's strict and advisory rules by reading FCStd files directly — no FreeCAD required. Next: the Apply-Joint tool, which reproduces the proven manual recipes programmatically.

## Documentation

- [Roadmap](docs/bentwizard-roadmap.md) — phases 0–5 and governing rules
- [Phase 0 workflow](docs/bentwizard-phase0-workflow.md) — the proven recipes and conventions; the specification the automation is built against
- [Friction findings](docs/phase0-friction-findings.md) — what hurt in the manual workflow and the automation each finding implies

## Layout

- `package.xml` + `freecad/bentwizard/` — the workbench, in FreeCAD 1.x addon layout
- `docs/` — specification documents
- `phase0/` — Phase 0 session models (`.FCStd`) and session macros (`.FCMacro`)

A portable FreeCAD install is expected outside the repo, alongside the project at `C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\`, for development and testing; it is not part of the repository (kept outside so it isn't exposed through the `Mod\BentWizard` dev-install junction).

## License

[LGPL-2.1-or-later](LICENSE), the same license as FreeCAD and its bundled workbenches.
