# BentWizard

Timber framing workbench for FreeCAD 1.1.1. Square-rule layout, subtractive joinery, all geometry native. A prior attempt (old GitHub repo) failed by generating custom-coded geometry; it is reference-only — this repo starts from scratch on the lessons learned.

**Status:** Phase 0 complete. Phase 1 in progress: linter, `Joint_HousedMT` template (with mate frame), New Timber, Apply-Joint with full placement (end A/B, faces 1–4, hand), Remove Joint, and Preview Mated Joint done — all output lints clean. Next: build the test bent with the tools (validation shakedown), duplicate-bent tooling, Save-as-joint-template.

## Read first

- [docs/bentwizard-roadmap.md](docs/bentwizard-roadmap.md) — phases, governing rules, adopted designs
- [docs/bentwizard-phase0-workflow.md](docs/bentwizard-phase0-workflow.md) — the proven manual recipes the tools must reproduce; **this is the spec Phase 1 is built against**
- [docs/phase0-friction-findings.md](docs/phase0-friction-findings.md) — numbered findings (#1–#14) cited throughout; each maps to an automation requirement

## Governing rules (non-negotiable)

1. **Tier 1 — geometry stays native.** All solid geometry is ordinary FreeCAD objects: Sketches, Part Design features, datums, Assembly joints. Test: uninstall the workbench — the model must open, edit, and recompute identically.
2. **Tier 2 — data degrades gracefully.** Non-geometric data (species, grade, roles, joint metadata) lives in custom properties on native objects, visible and round-trip-safe without the workbench. Workbench-gated *functionality* is fine; gated geometry is not.
3. **Subtractive joinery.** Pockets and holes, never pads, for joints. `Length` in a timber's Dims VarSet = the full stick as purchased, tenons included.
4. **Square rule.** Reference faces on the XZ/YZ origin planes; all joint layout measures from reference faces and stick ends.

## Environment

- Portable FreeCAD 1.1.1 lives **outside the repo** at `C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\` (sibling of the project; not repo content). It is deliberately outside so it isn't exposed through the `Mod\BentWizard` junction (see below).
  - GUI: `C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\bin\freecad.exe`
  - Headless (scripts, file inspection, future CI-style checks): `C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\bin\freecadcmd.exe <script.py>`
  - Bundled Python 3.11: `C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe` (imports `FreeCAD` directly)
- FreeCAD loads the workbench live via a **directory junction**: `C:\Users\Adam\AppData\Roaming\FreeCAD\v1-1\Mod\BentWizard` → the repo root. Edit code in the repo, restart FreeCAD (or reload the workbench), and it's live — never copy the folder into `Mod`. (The portable FreeCAD is kept out of the repo so it isn't seen nested inside this junction.)
- `.FCStd` files are zip archives; inspect by unzipping and reading `Document.xml` (see Verification below).
- FreeCAD 1.1 API gotcha: on Pad/Pocket (FeatureExtrude), `Midplane`/`Reversed` are deprecated and ignored — direction/symmetry live in `SideType` (GUI "Mode"; enum index 2 = Symmetric). Read/write `SideType` in tools and file checks.

## Repo layout

- `freecad/bentwizard/` — the workbench package (FreeCAD 1.x addon-manager layout; `package.xml` at root)
  - `fcstd.py` — pure-Python FCStd/Document.xml reader (no FreeCAD import)
  - `linter.py` — workflow doc §6 as executable rules; run with `python -m freecad.bentwizard.linter <file.FCStd>` (exit 1 on strict findings)
- `library/` — joint template library: one ordinary `.FCStd` per joint, must lint clean (strict and advisory); see `library/README.md`
- `docs/` — roadmap, workflow spec, findings log
- `phase0/` — Phase 0 session artifacts: `.FCStd` models and `.FCMacro` session transcripts. `TimberTemplate.FCStd` is the pristine timber template; the `Joint_HouseMT session N` files are the per-session snapshots.
- `tests/` — stdlib-only unittest suite: `python -m unittest discover -s tests` (bundled python works). `tests/fixtures/Joint_HouseMT_session_12.FCStd` is the ground-truth dirty file (every §7 debt must be caught); `TimberTemplate.FCStd` is the strict-clean control.

## Conventions (from the workflow doc — apply to all generated objects)

- **Timber Bodies:** MemberID labels, `[RolePrefix][BentNumber]-[Position]` (e.g. `P2-1`); bay refs for longitudinal members (`PU-B2-3`).
- **VarSet labels:** `Kind_Owner` — `TimberDims_P2-1`, `Joint_MT_B2a`, `Group_LoftDovetail`, `Project_Main`, `Order_Main`.
- **Property names:** `Part_Attribute[_Qualifier]`, most-significant first — `Tenon_Thickness`, `Housing_Depth`, `Peg_Drawbore_Offset`. Face qualifiers `_Face1`/`_Face2` (Face 1 = XZ-plane face, Face 2 = YZ-plane face).
- **Joint features in bodies:** body-qualified — `MemberID_Feature_JointID` (e.g. `P2-1_Mortise_MT_B2a`).
- **Tooltips mandatory** on every template-defined property: as brief as possible while still informative; always states which face/end it measures from.
- **Units:** the workbench defers to the user's FreeCAD unit schema (e.g. "Building US" for fractional inches) — never force imperial or metric. Imperial values in docs are example data.
- **Terminology:** use timber framing terms wherever applicable — names, UI, docs, instructions.
- **Width horizontal, Depth vertical** in a member's installed orientation, wherever applicable (soft convention — timbers meet in many orientations).
- **One VarSet per joint instance**, holding parameters for both halves (mated-pair mechanism).
- **Cross-timber coupling only via the joint VarSet** (workflow doc §4.3): a parameter tracking the mating timber's dimension is a joint VarSet property bound to that timber's Dims; body-internal features never reference a foreign Dims VarSet.
- **Sketch symmetry:** centerline construction line + half-width constraints, never the Symmetry constraint (finding #13).
- **Island pockets** require a strictly interior island; if the kept profile touches the section boundary, sketch removal regions directly (finding #14).
- **Datum strategy:** sketch on native origin planes/faces with zero offset; depth via pocket/pad length, not datum offset; position along the timber via sketch constraint. Reserve offset datums for genuinely floating planes and verify resolved placement (finding #10).
- **Never reference solid faces** — sketch supports, assembly joints, and dimensions attach to origin planes/datums selected by object reference, never 3D picks.
- **Duplication:** new timbers only from the pristine template, never from a jointed body (phantom features, finding #12); audit every expression in any duplicate (finding #2).
- **Parameter groups:** instance → type → section → project by expression binding, ≤3 layers; override = replace one property's expression with a literal; membership IS the binding.

Linter rules (strict vs. advisory) are enumerated in workflow doc §6 — treat that list as the source of truth when building validation.

## Verification methodology

- In-model: top/side orthographic views (never trust wireframe when profiles align in two axes), clipping planes through joints, Measure tool between mating faces.
- In-file: unzip the `.FCStd`, read `Document.xml`, and **always resolve the full placement chain** (Body placement × sketch/datum placement) before interpreting sketch coordinates. Read rotations from the placement quaternion (Q0–Q3), not axis/angle attributes. Sketch-local coordinates are NOT global once an offset/rotated datum is involved — this produced the project's one false diagnosis (finding #10).
- If Adam's viewport contradicts the file analysis, the viewport wins until the analysis is re-derived from resolved frames.

## Division of labor

Adam: FreeCAD driving, joinery domain decisions, testing against real workflow. Claude: all Python development, FreeCAD API research, step-by-step instructions, file-inspection verification.

**Commit workflow:** build + headless-test, then Adam GUI-tests and approves BEFORE committing — low-hanging bugs get fixed pre-commit, so commits land tested. (Adopted after the Phase 1 shakedown.)
