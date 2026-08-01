# BentWizard

Timber framing workbench for FreeCAD 1.1.1. Mill Rule layout, subtractive joinery, all geometry native. A prior attempt (old GitHub repo) failed by generating custom-coded geometry; it is reference-only — this repo starts from scratch on the lessons learned.

**Status:** Phase 0 complete. Phase 1 in progress: linter, `Joint_HousedMT` template (with mate frame), New Timber, Apply-Joint with full placement (end A/B, faces 1–4, hand) **plus auto-assembly** (each timber joint seats in the structure assembly the moment it's created), Remove Joint (also removes the joint's Fixed assembly joint), Preview Mated Joint, Duplicate Timbers (copies assemble into an offset bent sub-assembly), and Assemble Timbers (bulk/repair/reground) — done, all output lints clean. Architecture: **two-level structure assembly** — bent sub-assemblies inside a parent frame, grounded at the Principal Post, tie-beam `Length` drives bay width parametrically (see roadmap's adopted-design bullet, incl. the mate-parity rule for faces 1–3). Second shakedown testing produced the July 2026 notes, folded into the roadmap (Mill Rule reframe; permissive naming with dot default separator; Handed flag; N-part templates; parametric angles; beam tool) — of which New Timber **expression fields** and **copy-from-selected** are implemented. The **per-joint 3D handle** is built: `Handle_J-<Kind>-<serial>`, a proxy-less `App::FeaturePython` group holding the joint VarSet, filed in its bent's `TimberJoints_<Assembly>` group, marked in 3D by a workbench-gated ViewProvider, with whole-joint operations on its context menu (`joint_handle.CONTEXT_ACTIONS`). Next: Save-as-joint-template, Handed template flag, companion `Layout_` VarSet.

## Read first

- [docs/bentwizard-roadmap.md](docs/bentwizard-roadmap.md) — phases, governing rules, adopted designs
- [docs/bentwizard-phase0-workflow.md](docs/bentwizard-phase0-workflow.md) — the proven manual recipes the tools must reproduce; **this is the spec Phase 1 is built against**
- [docs/phase0-friction-findings.md](docs/phase0-friction-findings.md) — numbered findings (#1–#14) cited throughout; each maps to an automation requirement

## Governing rules (non-negotiable)

1. **Tier 1 — geometry stays native.** All solid geometry is ordinary FreeCAD objects: Sketches, Part Design features, datums, Assembly joints. Test: uninstall the workbench — the model must open, edit, and recompute identically.
2. **Tier 2 — data degrades gracefully.** Non-geometric data (species, grade, roles, joint metadata) lives in custom properties on native objects, visible and round-trip-safe without the workbench. Workbench-gated *functionality* is fine; gated geometry is not.
3. **Subtractive joinery.** Pockets and holes, never pads, for cuts *into timbers*. `Length` in a timber's Dims VarSet = the full stick as purchased, tenons included. (Standalone created parts — a tusk-tenon wedge — are ordinary solids; pads fine.)
4. **Mill Rule.** Drawings dimension an idealized straight, square timber. Reference faces on the XZ/YZ origin planes; all joint layout measures from reference faces and stick ends. Housings are optional bearing features with designed depths. Square Rule's reduce-to-ideal housing is field work on the rough stick — never a drawn dimension, outside the model (reframed July 2026; see roadmap Layout rules).

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
  - `view_joint_handle.py` — the only GUI-side module besides `commands.py`/`init_gui.py`; the joint marker's ViewProvider, attached at runtime (nothing about it is persisted)
- `library/` — joint template library: one ordinary `.FCStd` per joint, must lint clean (strict and advisory); see `library/README.md`
- `docs/` — roadmap, workflow spec, findings log
- `phase0/` — Phase 0 session artifacts: `.FCStd` models and `.FCMacro` session transcripts. `TimberTemplate.FCStd` is the pristine timber template; the `Joint_HouseMT session N` files are the per-session snapshots.
- `tests/` — stdlib-only unittest suite: `python -m unittest discover -s tests` (bundled python works). `tests/fixtures/Joint_HouseMT_session_12.FCStd` is the ground-truth dirty file (every §7 debt must be caught); `TimberTemplate.FCStd` is the strict-clean control.

## Conventions (from the workflow doc — apply to all generated objects)

- **Two names, two jobs:** the Label is the **permanent identity** (what the piece IS, never its position); position is Tier-2 data in the `Position_Tag` property on Dims/joint VarSets, display-only for drawings. FreeCAD's immutable Internal Name (`Body003`) is never used semantically. Legacy MemberIDs (`P2-1`) are grandfathered advisory-clean.
- **Timber Bodies:** free-form label ending in separator + serial (permissive since July 2026). Recommended style `T-<Role>[-<Qualifier>]-<serial>` (`T-Post-Level1-003`); dotted/spaced forms fine (`T-Post.Balcony.001`). The serial is the trailing digit run after a separator (`-`/`.`/`_`/space); tools bump only it, preserving the separator (never digits glued into descriptive parts, `Level1`); appending to a serial-less name uses its trailing separator, else the family's, else the base's last separator, defaulting to `.`. Reserved characters (strict lint): `>`, `\`, `;`, line breaks — they break `<<Label>>` expressions / Placement_Record.
- **Joint instances:** `J-<Kind>-<serial>` — `J-HousedMT-001`; kind token from the template file stem.
- **VarSet labels:** `Kind_Owner` — `TDim_T-Post-003`, `Group_LoftDovetail`, `Project_Main`, `Order_Main`; a joint VarSet carries its joint's `J-<Kind>-<serial>` label directly. The Dims prefix shortened from `TimberDims_` (July 2026); legacy VarSets are grandfathered, never migrated — the prefix is a hint, the binding is resolved structurally from the base pad's `Length` expression.
- **Tree organization:** Dims VarSets nest inside their Bodies; a joint VarSet nests in its **handle**, and handles live in a `TimberJoints_<Assembly>` Std Group *inside the assembly the joint belongs to* — one folder of joints per bent, one node per joint, the frame's group holding cross-bent ties (`joint_handle.handle_group`; the container is the joint's Fixed-assembly-joint's, never re-derived). Re-filing respects a user's own arrangement: a VarSet dragged out beside its handle stays put. Named apart from `Joints`, the group every FreeCAD Assembly carries; root-level `TimberJointVars`/`Joints` groups from earlier documents are renamed in place, and a joint with no assembly waits in a bare root `TimberJoints` group. Bents/bays are also user-arranged Std Groups (Duplicate Timbers can create one). Pure organization, no geometric effect.
- **Per-joint handle:** `Handle_J-<Kind>-<serial>` — a proxy-less `App::FeaturePython` with a `Joint` link to its joint's VarSet and a `Frame` link to the anchor's landing frame. Both bindings are **structural, never label-matched** (`is_handle`/`find_handle` ignore the label; a renamed handle must still resolve — the lesson of `Frame_Role` and `find_fixed_joint`). It holds the VarSet via `App::GroupExtensionPython` — and the ViewProvider must carry `Gui::ViewProviderGroupExtensionPython` to match, or the tree won't draw the nesting no matter what `Group` says (an App-side group extension is only half of a group; headless tests can't see the difference). Created by Apply Timber Joint, re-filed by `assimilate_joint`, removed by Remove Joint, adopted doc-wide by Assemble Timbers. The marker (`view_joint_handle.py`, GUI-only) is **view-only** — the handle owns no Placement and takes no part in the solve; position comes from the frame's global placement, refreshed by a document observer. Its ViewProvider Proxy is **Transient** (never saved): markers are attached at runtime by `view_joint_handle.install()` when the workbench activates and by the restore observer, so a document opened without BentWizard is silent (a persisted proxy printed a `ModuleNotFoundError` traceback per handle). Whole-joint operations register in `joint_handle.CONTEXT_ACTIONS` rather than in the ViewProvider. The marker's scene graph roots in an `SoFCSelection` — that is what routes a 3D pick to the handle; a plain separator let the click escalate to the container instead. **Joint operations are reached from the tree** (double-click → the joint's VarSet; right-click → the registered actions): FreeCAD dispatches neither `doubleClicked` nor `setupContextMenu` from the 3D view (upstream #14701/#11429/#12826, open against Assembly's own joint markers too), so a 3D click selects the handle and the toolbar commands preselect from it.
- **Property names:** `Part_Attribute[_Qualifier]`, most-significant first — `Tenon_Thickness`, `Housing_Depth`, `Peg_Drawbore_Offset`. Face qualifiers `_Face1`/`_Face2` (Face 1 = XZ-plane face, Face 2 = YZ-plane face).
- **Joint features in bodies:** descriptive-first (July 2026) — `<Descriptive>[.<TypeTag>].<Abbrev>.<serial>`: `Mortise.HMT.001`, `TailSlope.Skt.WHD.001`, `Mate.Lcs.WHD.001`. The cut is bare; its sketch and datums are tagged `.Skt`/`.Lcs`/`.Dtm`. `<Abbrev>` is the template's `Template_Abbrev`; **Apply-Joint rewrites exactly that suffix** (strict lint). No timber name: membership is structural, no expression targets a feature label, and the tree already nests it under its Body — so **a template's feature labels must be unique across both halves** (`MortisePegBore`/`TenonPegBore`). Timber base features take the same shape with their own timber as the qualifier: `Section.Skt.T-Post-001`, `Stick.T-Post-001` (FreeCAD forces unique labels, so an unqualified `Stick` collects a meaningless auto-counter).
- **Joint frame role is Tier-2 data, not a label:** each landing/mate frame carries `Frame_Role` = `Landing` or `Mate`, read by Preview, Assemble, Duplicate and the end-B seat flip. It replaced a `JointFrame`/`MateFrame` substring match that failed silently on a renamed frame (strict lint: one `Landing` per role, at most one `Mate` per joint).
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

## Subagents

Four project subagents live in `.claude/agents/`. Delegate to them explicitly by name when their trigger condition fits; otherwise do the work in the main session.

- **freecad-api-scout** — when the exact FreeCAD 1.1 API surface (a class, method, enum, workbench behavior) is uncertain and needs to be confirmed before writing code against it.
- **timber-craft-researcher** — when a feature needs grounding in real traditional joinery/layout practice, before a joint template or Mill Rule behavior is designed.
- **fcstd-verifier** — after implementing or modifying a tool, to verify the resulting `.FCStd` (placement chain, linter, tests) before reporting the change ready for Adam's GUI test.
- **git-workflow** — after Adam has GUI-tested and approved a change, to stage it and draft the commit message.

**What stays in the main session, not delegated:** joint geometry/placement logic, GUI (TaskPanel) code, and anything reconciling the two — this is the core spatial-reasoning work the project depends on getting right, and a fresh-context subagent doesn't have the surrounding design reasoning to do it safely.

Subagents start with a fresh context window — they only see what's in the invocation prompt, not this conversation. When delegating, state the specific file(s), what changed, and what's being asked for; don't assume the subagent can infer it.

Agent files are loaded at session start. After adding or editing a file in `.claude/agents/`, restart the Claude Code session before it's available.
