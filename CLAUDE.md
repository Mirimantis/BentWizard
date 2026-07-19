# BentWizard

Timber framing workbench for FreeCAD 1.1.1. Square-rule layout, subtractive joinery, all geometry native. A prior attempt (old GitHub repo) failed by generating custom-coded geometry; it is reference-only — this repo starts from scratch on the lessons learned.

**Status:** Phase 0 complete. Phase 1 in progress: linter, `Joint_HousedMT` template (with mate frame), New Timber, Apply-Joint with full placement (end A/B, faces 1–4, hand) **plus auto-assembly** (each timber joint seats in the structure assembly the moment it's created), Remove Joint (also removes the joint's Fixed assembly joint), Preview Mated Joint, Duplicate Timbers (copies assemble into an offset bent sub-assembly), and Assemble Timbers (bulk/repair/reground) — done, all output lints clean. Architecture: **two-level structure assembly** — bent sub-assemblies inside a parent frame, grounded at the Principal Post, tie-beam `Length` drives bay width parametrically (see roadmap's adopted-design bullet, incl. the mate-parity rule for faces 1–3). Next: rebuild the test bent (second shakedown), per-joint 3D handle, Save-as-joint-template.

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

- **Two names, two jobs:** the Label is the **permanent identity** (what the piece IS, never its position); position is Tier-2 data in the `Position_Tag` property on Dims/joint VarSets, display-only for drawings. FreeCAD's immutable Internal Name (`Body003`) is never used semantically. Legacy MemberIDs (`P2-1`) are grandfathered advisory-clean.
- **Timber Bodies:** `T-<Role>[-<Qualifier>]-<serial>` — `T-Post-Level1-003`, `T-TieBeam_decorative-007`. The serial is the trailing all-digit segment; tools bump only that segment (never digits inside descriptive parts).
- **Joint instances:** `J-<Kind>-<serial>` — `J-HousedMT-001`; kind token from the template file stem.
- **VarSet labels:** `Kind_Owner` — `TimberDims_T-Post-003`, `Group_LoftDovetail`, `Project_Main`, `Order_Main`; a joint VarSet carries its joint's `J-<Kind>-<serial>` label directly.
- **Tree organization:** Dims VarSets nest inside their Bodies; joint VarSets live in a `TimberJointVars` Std Group (renamed from `Joints`, which collides with the `Joints` group every FreeCAD Assembly carries; `joints_group()` migrates legacy documents); bents/bays are user-arranged Std Groups (Duplicate Timbers can create one). Pure organization, no geometric effect.
- **Property names:** `Part_Attribute[_Qualifier]`, most-significant first — `Tenon_Thickness`, `Housing_Depth`, `Peg_Drawbore_Offset`. Face qualifiers `_Face1`/`_Face2` (Face 1 = XZ-plane face, Face 2 = YZ-plane face).
- **Joint features in bodies:** body-qualified — `<TimberLabel>_<Feature>_<JointLabel>` (e.g. `T-Post-003_Mortise_J-HousedMT-001`).
- **Tooltips mandatory** on every template-defined property: as brief as possible while still informative; always states which face/end it measures from.
- **Units:** the workbench defers to the user's FreeCAD unit schema (e.g. "Building US" for fractional inches) — never force imperial or metric. Imperial values in docs are example data.
- **Terminology:** use timber framing terms wherever applicable — names, UI, docs, instructions. BentWizard's joinery is a **timber joint** ("TimberJoint") in all user-facing text — plain "joint" alone is ambiguous against FreeCAD Assembly joints.
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

**Worktree GUI testing:** the `Mod\BentWizard` junction targets one directory, so it loads whichever checkout it points at — by default the main repo, *not* a worktree Claude is working in. To GUI-test a worktree branch's *uncommitted* code (preserving "test before commit"), run `scripts/dev-install.ps1 here` from that worktree, restart FreeCAD, and test; run `scripts/dev-install.ps1 main` to point back once the branch is **merged and the main checkout is updated** (`git checkout main && git pull` in the main repo dir first — pointing back before then loads the pre-merge main checkout and FreeCAD drops the branch's changes). `dev-install.ps1` with no argument shows the current target. This is also why FreeCAD can seem to ignore a branch's changes: the junction is still on another checkout.
