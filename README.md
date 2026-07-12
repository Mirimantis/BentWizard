# BentWizard

A timber framing workbench for FreeCAD 1.1.1: square-rule layout, subtractive joinery, and — the governing rule — **all geometry stays native**. Everything the workbench produces is ordinary FreeCAD (Sketches, Part Design features, datums, Assembly joints) and remains fully hand-editable with the workbench uninstalled.

This is a from-scratch rewrite; an earlier attempt that generated custom-coded geometry is kept only as a record of lessons learned.

## Status

- **Phase 0 — manual workflow definition: complete.** The joinery workflow (parametric timbers, housed mortise & tenon, housed dovetail, pegs/drawbore, assembly, TechDraw sheets, cut list) was proven by hand across twelve modeling sessions. Session artifacts live in `tests/`.
- **Phase 1 — joint library & Apply-Joint tool: next.** The tool reproduces the proven manual recipes programmatically: cloned native sketches/features bound to a shared per-joint VarSet, with expressions written by the tool instead of typed by hand.

## Documentation

- [Roadmap](docs/bentwizard-roadmap.md) — phases 0–5 and governing rules
- [Phase 0 workflow](docs/bentwizard-phase0-workflow.md) — the proven recipes and conventions; the specification the automation is built against
- [Friction findings](docs/phase0-friction-findings.md) — what hurt in the manual workflow and the automation each finding implies

## Layout

- `package.xml` + `freecad/bentwizard/` — the workbench, in FreeCAD 1.x addon layout
- `docs/` — specification documents
- `tests/` — Phase 0 session models (`.FCStd`) and session macros (`.FCMacro`)

A portable FreeCAD install is expected at `FreeCAD_1.1.1-Windows-x86_64-py311/` for development and testing; it is gitignored and not part of the repository.
