# BentWizard

Timber framing workbench for FreeCAD 1.1.1. Timber-owned datums, cutter/adder joinery copied from templates, all geometry native. A prior attempt (old GitHub repo) failed by generating custom-coded geometry; it is reference-only — this repo starts from scratch on the lessons learned.

**Status (September 2026): rev-2 foundation rebuilt.** The rev-1 mechanism (faces 1–4 with parity tables, joints rebuilt sketch-by-sketch into the timber body, typed stick lengths with `Stick_Allowance_*` and a companion `Layout_` VarSet, `Template_Handed`) was replaced wholesale after spike rounds 1–3 and the datum-accessor session (`docs/session-frame-accessors.md`, Parts A–H). What exists now, headless-tested (108+ tests green) and awaiting Adam's GUI round: **New Timber** (centred section, `WidthX/WidthY/LengthZ`, both end datums created with it), **Add Datum** (a face at a station, from the face table), **Apply Timber Joint** (copy the template's VarSet and component bodies, pair the datums, re-point, mirror on parity, Boolean in order, assert one solid, pre-position and seat), **Remove Timber Joint**, **Duplicate Timbers**, **Assemble Timbers**, **Show Face & End Marks** (±X/±Y/A/B), **Audit Timbers** (design vs order length, end projections, solid count, datum pairing), **New Joint Template** / **Save as Joint Template** (the template bar: lint + skeleton + geometry sweep), and the shipped library `Joint_Butt` (starter) and `Joint_HousedMT`, both script-built by `scripts/build_library.py`. Retired: Preview Mated Joint, Drive Length from Layout Distance, `span.py`, `apply_joint.py`, the dovetail template (to be rebuilt on the new contract). Next: Adam's GUI test of the whole flow; then the front end's near-term items and the roadmap's deferred list (face labels per timber role, created-part roles, the dovetail, the beam tool).

## Read first

- [docs/bentwizard-workflow-rev2.md](docs/bentwizard-workflow-rev2.md) — the mechanism this code implements (its LCS is our "datum"; see Terminology)
- [docs/session-frame-accessors.md](docs/session-frame-accessors.md) — the proving session behind it, Parts A–H
- [docs/bentwizard-roadmap.md](docs/bentwizard-roadmap.md) — phases, governing rules, adopted designs, deferred items
- [docs/phase0-friction-findings.md](docs/phase0-friction-findings.md) — numbered findings (#1–#15) cited throughout; `docs/bentwizard-phase0-workflow.md` is the superseded rev-1 spec, kept as history

## Governing rules (non-negotiable)

1. **Tier 1 — geometry stays native.** All solid geometry is ordinary FreeCAD objects: Sketches, Part Design features, LCS datums, Booleans, Assembly joints. Test: uninstall the workbench — the model must open, edit, and recompute identically.
2. **Tier 2 — data degrades gracefully.** Non-geometric data (species, grade, roles, pairing, component roles) lives in custom properties on native objects, visible and round-trip-safe without the workbench. Workbench-gated *functionality* is fine; gated geometry is not.
3. **Prefer native mechanisms over reimplementation.** Instancing is `copyObject`, not a rebuild engine; placement is an expression, not computed geometry. Both prior failures violated this in different ways.
4. **The timber is the design solid.** `LengthZ` is the frame dimension, bearing face to bearing face; it does not change when joinery is applied or swapped. Joinery is a **cutter** (modelled in −Z, `Cut`) and/or an **adder** (modelled in +Z, `Fuse`) applied as `PartDesign::Boolean`s. Order length is measured off the finished solid (`measure.py`), never typed. No layout doctrine: square rule versus mill rule is shop practice.

## Environment

- A portable FreeCAD 1.1.x install lives **outside the repo**, as a sibling of the checkout (not repo content). **Its location and patch version differ per machine** — find it as `..\FreeCAD_1.1.*-Windows-x86_64-py311\` next to the checkout, and never hard-code one machine's path into code or docs. Known locations (update when a machine changes):
  - `C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\`
  - `C:\Users\Admin\projects\FreeCAD_1.1.3-Windows-x86_64-py311\`

  Below, `<FreeCAD>` means that install's root.
  - GUI: `<FreeCAD>\bin\freecad.exe`
  - Headless: `<FreeCAD>\bin\freecadcmd.exe <script.py>` — note it swallows Python `print` output; for scripts that report, use the bundled python instead
  - Bundled Python 3.11: `<FreeCAD>\bin\python.exe` (imports `FreeCAD` directly; runs the test suite and `scripts/build_library.py`)
  - Scripted GUI probe (for GUI-only behaviour: active document, tree, command enablement): `freecad.exe --log-file <log> <probe.py>`, with the probe's work in a `QtCore.QTimer.singleShot(4000, run)` (the main window must be up), `App.Console.PrintLog("MARK: …")` markers to correlate the log, `Gui.Command.get(name).isActive()` for enablement, and `Gui.getMainWindow().close()` from a timer to exit; it blocks until the window closes. The session's probes live in the scratchpad, not the repo.
- FreeCAD loads the workbench live via a **directory junction**: `%APPDATA%\FreeCAD\v1-1\Mod\BentWizard` → the repo root (all 1.1.x releases share the `v1-1` config folder; on a fresh machine, `scripts/dev-install.ps1 main` creates it). Edit code in the repo, restart FreeCAD, and it's live — never copy the folder into `Mod`.
- `.FCStd` files are zip archives; inspect by unzipping and reading `Document.xml` (see Verification below).
- FreeCAD 1.1 API gotchas: on Pad/Pocket, `Midplane`/`Reversed` are deprecated in favour of `SideType` (but `Reversed` still flips a Pad's direction and the component helpers use it). `App::PropertyLength` clamps a negative *literal* to 0 but not an expression — a typing guard, never an invariant; use `Distance` for signed values (`Station`). Constrained property types (`PropertyFloatConstraint` etc.) do not persist their bounds and expressions bypass them, so declared ranges are sibling `<Name>Min`/`<Name>Max` properties. `PartDesign::Boolean.addObjects` drags a `Part::Mirroring`'s `Source` in as a second operand — assign `Group = [operand]` directly. A cross-document `copyObject` rewrites an unresolvable `<<Label>>` into a bare `Label.Prop` form; `apply._substitute` matches both. A headless `recompute()` leaves an Assembly `Touched` until `solve()` runs. `App.openDocument(path, hidden=True)` makes the hidden file the **active document** (App and Gui), and closing it leaves *no* active document — in the GUI every command that needs one greys out; always go through `template_library.open_hidden`, which restores it (`App.setActiveDocument` / `Gui.setActiveDocument`). **A datum's child axes/planes are filed under the FIRST GeoFeatureGroup in the datum's in-list, membership unchecked** (`getGroupOfObject` on an `App::DatumElement` resolves through its LCS): a component Body whose `Placement` read `<<D_…>>.Placement` could come before the owning timber, and the datum then failed its scope check on the next recompute (`Link(s) to object(s) 'XZ_Plane005 …' go out of the allowed scope`, Adam's second GUI round). Hence the `HostPlacement`/`MatePlacement` accessors: only non-GeoFeatureGroup objects (the VarSet, sketches, a `Part::Mirroring`) may link a datum. Features added from Python leave the previous Tip visible and a removed Tip leaves nothing visible — `apply.show_tip` fixes the view after Apply and Remove. Undoing an Apply prints two `getOverlayIcons … 'NoneType' has no attribute 'isPartConnected'` tracebacks from `Mod/Assembly/JointObject.py` — FreeCAD's icon code is not null-safe while undo dismantles the assembly; harmless, not ours.

## Repo layout

- `freecad/bentwizard/` — the workbench package (FreeCAD 1.x addon-manager layout; `package.xml` at root)
  - `facetable.py` — the face table, pure data: where a datum sits on each face/end, its rotation, its `WidthU/WidthV/DepthW` bindings and its parity. The single source for `datums.py`, the linter and the face marks.
  - `naming.py` — labels, serials, Tier-2 property names, component/Boolean/mirror label forms (pure Python)
  - `fcstd.py` — pure-Python FCStd/Document.xml reader (no FreeCAD import)
  - `timber.py` — New Timber; `dims_varset` resolves a body's Dims structurally (its stick pad's `LengthZ` binding)
  - `datums.py` — Add Datum, pairing (`pair`/`unpair`), the seat (`seat_delta`, `misfit`), `verify_datum`
  - `component.py` — authoring helpers for component bodies (`new_component`, `add_prism`, `apply_boolean`); used by the library build script and the tests
  - `template.py` — `TemplateSpec`: what a template declares, read purely
  - `apply.py` — Apply / Remove Timber Joint; `joint_members`, `joint_datums`, `bent_joints`
  - `assemble.py` — the two-level structure assembly (container rules, `assimilate_joint`, Assemble Timbers)
  - `joint_handle.py` — the per-joint handle (`Joint` and `Datum` links, `TimberJoints_<Assembly>` filing); `view_joint_handle.py` its marker (GUI, transient)
  - `duplicate.py` — Duplicate Timbers (rebuild, re-place datums, re-apply joints)
  - `measure.py` — order length, end projection, solid count, off the finished solid in the timber's own frame
  - `linter.py` — rev 2 §6 as pure-Python rules; `python -m freecad.bentwizard.linter <file.FCStd>` (exit 1 on strict findings)
  - `template_check.py` — the template bar: skeleton rules (pure) and `check_geometry` (FreeCAD: one solid, growth direction, the parameter sweep)
  - `template_library.py` — template folders (user's ahead of shipped `library/`), starters, save / new-from-starter
  - `view_face_marks.py` — ±X/±Y/A/B labels in the 3D view (not objects)
  - `undo_repair.py` — re-arms expression bindings after undo (finding #15)
  - `commands.py` / `init_gui.py` — the GUI side
- `library/` — the shipped templates; see `library/README.md`. Rebuilt by `scripts/build_library.py` (bundled python), which also runs the bar on them.
- `docs/` — roadmap, rev-2 workflow, session and spike records, findings log; `joinery-*.md` are notes for joints not yet rebuilt (brace M&T, housed dovetail, wedged half-dovetail); `bentwizard-phase0-workflow.md` is the superseded rev-1 spec, kept for its pegs / TechDraw / cut-list practice until Phases 2–3 have their own docs
- `devBuildMacros/` — the naming-prompt dev helper (`EnforceNaming`), slated to become its own plugin (roadmap). The Phase 0 session files and spike macros were deleted in September 2026; the spike records in `docs/` and `tests/spike/` are what remains of them
- `tests/` — unittest suite: `python.exe -m unittest discover -s tests` with the bundled python (pure-Python modules also run under any interpreter and skip the FreeCAD ones). `tests/spike/` holds the round 1–3 spike harnesses (run under freecadcmd; they write into `docs/` and `scratch/`).

## Terminology

- **Datum, never "frame".** The LCS a timber carries is a *datum* (`D_T-Post-001_YPos_001`, `MateDatum`, host datum, mate datum, "datum accessors"). To a framer a *frame* is a structure made of wood — the parent assembly is `Frame-NNN`. The rev-2 and session docs still say "frame" for the LCS; that is historical wording.
- BentWizard's joinery is a **timber joint** in all user-facing text — plain "joint" alone is ambiguous against FreeCAD Assembly joints.
- Use timber framing terms wherever applicable; the audience is framers and carpenters (individual DIY builders through small contractors), not CAD users. Name things after the work, not the implementation. A few hours of learning is an acceptable price, weeks is not. "Not prescriptive" means *not deciding for the user*, not *interrogating the user*.

## Conventions

- **Timber:** Body labelled with a permanent identity ending in separator + serial (`T-Post-003`, `T-Post.Balcony.001`; reserved characters `>`, `\`, `;`, line breaks), Dims VarSet `TDim_<label>` nested in it with `WidthX`, `WidthY`, `LengthZ` (`App::PropertyLength`) and `PositionTag` (display-only). Section sketch centred on the origin, half-width constraints from the origin (never Symmetric, finding #13), stick pad to `LengthZ`, end datums `D_<label>_A` (Station 0, 180° about Y) and `D_<label>_B` (Station = `LengthZ`, identity).
- **Datum:** `Part::LocalCoordinateSystem` inside its timber, `MapMode` Deactivated, placed from `facetable.FACE_TABLE` — never by attachment (three axis bugs came from attached-datum mapping) and never by hand (two GUI failures came from typing placement fields). Group `Datum`: `Face` (`XPos XNeg YPos YNeg EndA EndB`, declared, never guessed), `Station` (`Distance`, drives `.Placement.Base.z`; may be an expression on a project VarSet), `WidthU/WidthV/DepthW` (own Dims per the row), `MateDatum` and `Joint` (internal-Name **strings** — a link cannot cross a Body boundary). Rule: local Z out of the material, local Y along the timber toward end A, X = Y × Z. Faces are `+X −X +Y −Y`; no reference faces, no numbering.
- **Joint VarSet:** `J-<Kind>-<serial>` (a template's own is `-000`; the file stem is the kind). Parameters in group `Joint`, UpperCamelCase, tooltips mandatory. The tool writes `HostWidthU … MateDepthW` and `HostPlacement`/`MatePlacement` (group `Datums`) reading the two datums — **datums never read each other** (object-granular cycle; the Step 0 probe hit it), and **no Body ever reads a datum's Placement** (see the scope gotcha under Environment). Ranges `<Name>Min/Max` in group `Ranges`; `TemplateSource`, `SweepFindings` in group `Template`.
- **Component:** a `PartDesign::Body` with `ComponentRole` (`Cutter`/`Adder`) and `ComponentOrder`, `Placement` bound to its joint VarSet's `HostPlacement`/`MatePlacement` (never to the datum itself — strict lint `component-placement-direct`), labelled `<Descriptive>.<Kind>.<serial>`; its Boolean `Cut.<comp>`/`Fuse.<comp>`, its mirroring `Mirror.<comp>`. **A component reads only its own datum and its joint VarSet** (strict lint `component-reference-scope`). Cutters before adders unless the cutter deliberately trims the adder (the orders do not commute — round 3 T5).
- **Parity and the mirror rule:** `EndB`, `XPos`, `YPos` are +; `EndA`, `XNeg`, `YNeg` are −. Apply mirrors a component across its local X (`Part::Mirroring`, the mirroring carries the Placement) when the target datum's parity differs from the authoring datum's, so a component keeps its timber-local offsets at either end and on opposite faces. Pinned by `test_apply.test_parity_keeps_timber_local_offsets`.
- **The seat:** paired datums seat antiparallel — `Offset1` = 180° about local Y on every Fixed joint; the mover's pose is `host_g · flip · mate_g⁻¹` (`datums.seat_delta`). **Never recompute between creating the Fixed joint and pre-positioning the mover**: with the joint present and the mover parked far away and rotated, MbD rotated the *grounded* post ~20°. With pre-positioning every face × end seats exactly (`test_apply.test_matrix_every_face_and_end`).
- **One solid is the assertion.** A 1 mm gap, a cutter spanning the section and a seat in the wrong frame each gave exactly the expected volume; only `len(Solids) == 1` told a joint from a severed timber. Apply refuses on it, `measure.is_whole` reports it, the sweep hunts for it.
- **Property names** UpperCamelCase (`TenonLength`, not `Tenon_Length`); labels exempt.
- **Tree:** Dims nests in its Body; a joint's VarSet nests in its handle, in `TimberJoints_<Assembly>` inside the assembly its Fixed joint lives in; component bodies are claimed by their Booleans; a mirrored component's source body stays at root beside its mirroring.
- **Units:** the workbench defers to the user's FreeCAD unit schema — never force imperial or metric. Imperial values in docs are example data.
- **Cross-timber coupling only via the joint VarSet** (the accessors). Body-internal features never reference a foreign Dims VarSet.
- **Never reference solid faces** — sketch supports, assembly joints and dimensions attach to origin planes/datums selected by object reference, never 3D picks.
- **Duplication:** new timbers only via `new_timber`, never by copying a jointed body (findings #2, #12); joints re-applied from their `TemplateSource`; Dims expressions carried, expressions naming the source itself copied as literals.

## Verification methodology

- In-model: top/side orthographic views (never trust wireframe when profiles align in two axes), clipping planes through joints, Measure tool between mating faces, **Audit Timbers** for solid counts and datum pairing.
- In-file: unzip the `.FCStd`, read `Document.xml`, and **always resolve the full placement chain** before interpreting coordinates. Read rotations from the placement quaternion (Q0–Q3), not axis/angle attributes; q and −q are the same rotation. Sketch-local coordinates are NOT global once a placed datum is involved (finding #10).
- Every geometry test asserts the analytic value, one solid, nothing outside `Up-to-date`, console silent (rev 2 §5). Headless is a filter, not an oracle: recompute-ordering failures were GUI-only (`Tool shape is null`), so anything touching recompute order needs Adam's GUI check.
- If Adam's viewport contradicts the file analysis, the viewport wins until the analysis is re-derived from resolved placements.

## Division of labor

Adam: FreeCAD driving, joinery domain decisions, testing against real workflow. Claude: all Python development, FreeCAD API research, step-by-step instructions, file-inspection verification.

**Commit workflow:** build + headless-test, then Adam GUI-tests and approves BEFORE committing — low-hanging bugs get fixed pre-commit, so commits land tested.

**Worktree GUI testing:** the `Mod\BentWizard` junction targets one directory, so it loads whichever checkout it points at — by default the main repo. To GUI-test a worktree branch's *uncommitted* code, run `scripts/dev-install.ps1 here` from that worktree, restart FreeCAD, and test; run `scripts/dev-install.ps1 main` to point back once the branch is merged and the main checkout updated. `dev-install.ps1` with no argument shows the current target.

## Subagents

Four project subagents live in `.claude/agents/`. Delegate to them explicitly by name when their trigger condition fits; otherwise do the work in the main session.

- **freecad-api-scout** — when the exact FreeCAD 1.1 API surface (a class, method, enum, workbench behavior) is uncertain and needs to be confirmed before writing code against it.
- **timber-craft-researcher** — when a feature needs grounding in real traditional joinery/layout practice, before a joint template is designed.
- **fcstd-verifier** — after implementing or modifying a tool, to verify the resulting `.FCStd` (placement chain, linter, tests) before reporting the change ready for Adam's GUI test.
- **git-workflow** — after Adam has GUI-tested and approved a change, to stage it and draft the commit message.

**What stays in the main session, not delegated:** joint geometry/placement logic, GUI (dialog) code, and anything reconciling the two — this is the core spatial-reasoning work the project depends on getting right, and a fresh-context subagent doesn't have the surrounding design reasoning to do it safely.

Subagents start with a fresh context window — they only see what's in the invocation prompt, not this conversation. When delegating, state the specific file(s), what changed, and what's being asked for; don't assume the subagent can infer it.

Agent files are loaded at session start. After adding or editing a file in `.claude/agents/`, restart the Claude Code session before it's available.
