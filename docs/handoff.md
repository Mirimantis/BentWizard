# Session handoff

Living pointer for a fresh session. Read after CLAUDE.md and the rev-2
workflow doc. Update it as work lands.

## Where things stand (2026-10-08)

On `main`, FreeCAD 26.3 (the minimum). The test environment is the
2026.10.01 weekly (git `99c5620c5`, the 26.3 branch point) until a 26.3
release candidate replaces it. 195 tests green, run with
`-W error::DeprecationWarning`; every piece has been through Adam's GUI
round.

- **The rev-2 foundation.** New Timber, Add Datum, Apply / Remove Timber
  Joint, Duplicate Timbers, Seat Timbers, Show Face & End Marks, Audit
  Timbers, Store in Variable Set, and the template bar (New / Save as
  Joint Template). The shipped library is `Joint_Butt` and
  `Joint_HousedMT`.
- **The flat frame.** No Assembly object: the frame is a Std Group of
  bent and bay Std Groups. Every timber but the anchor is **seated by
  expression** (`Seat_J-…` under the placing joint's handle), and the
  anchor reads `ProjectVars.FrameOrigin`. Audit Timbers reports each
  timber as anchored, seated, provisional or loose, and each timber
  joint's misfit.
- **Timbers are filed in bents.** The first timber joint on a timber in
  no frame files it in a group inside the frame: the other timber's
  bent, else a new `Bent-NNN`, or whatever the framer names in the Apply
  dialog's **Bent / group** field. Seat Timbers has the same field and
  also tidies timbers left loose in the frame's root. Nothing already in
  a group moves, and nothing leaves its frame.
- **Seat Timbers** keeps the anchor where it is by default, and seats a
  selected group that no joint ties to the frame (a pair applied with
  seating unchecked) from a provisional root where it stands.
- **Timber Variables**, a docked panel that follows the selection: what
  sets the selected timber or timber joint, where each value is edited
  (its Var. Location), what else a shared value drives, and in-place
  editing as one undoable step. The listing is sticky: it changes only
  when another timber or joint is selected, and an amber line says so
  whenever nothing selected belongs to it. A row click selects where the
  value lives.
- **The 26.3 move is complete** (`freecad-26-3-compatibility-brief.md`).
  Booleans carry `UseLegacyBodyPlacement` (route (a)), and they keep
  it: route (b) is blocked upstream (below).

**Next:**
- **The roadmap's deferred list:** face labels per timber role,
  created-part roles (wedges, pegs), the dovetail rebuilt on the new
  contract (have timber-craft-researcher ground it first, building on
  `joinery-*.md`), and the beam tool.

**Waiting on upstream:**
- **Route (b), binding components globally** (2026-10-08,
  `spike-26-3-gui-results.md` finding 14). A per-timber pose VarSet
  converts a frame exactly, but on 26.3 a Boolean is not re-run when its
  Body moves. A Bay edit at 10 bents left 25 of 48 timbers in two solids
  with nothing Touched. Route (a) stays. Filed by Adam as upstream
  #33343, with the repro file from `scratch/boolean-stale/`. When a
  build carries a fix, rerun `tests/spike/spike_route_b.py` and
  `scratch/boolean-stale/boolean_stale_check.FCMacro`.
- Two box-selection regressions on the weekly,
filed by Adam (`spike-26-3-gui-results.md`, finding 13). A right-to-left
box selects every VarSet wherever it is drawn, and a Body whose Tip is a
PartDesign Boolean reports the Boolean's *tool* bounding box. Select
from the tree meanwhile. When a fixed weekly lands, rerun
`scratch/boolean-bbox/` (attached upstream) and drop the gotcha from
CLAUDE.md. Timber joint handles are not box-selectable, by Adam's
choice; a single click selects one.

## How it got here

**September 2026 — rev 2 and the flat frame.** The rev-1 code is gone:
`apply_joint.py`, `span.py`, the parity tables, `Stick_Allowance_*`, the
companion `Layout_` VarSet, `Template_Handed`, Preview Mated Joint,
Drive Length from Layout Distance, the old dovetail, and then
`assemble.py` with its Fixed-joint solver. Three GUI rounds shaped what
is there now:
- Apply restores the active document after reading a template
  (`template_library.open_hidden`).
- Components bind to the accessors' `HostPlacement`/`MatePlacement`,
  never to a datum, because of FreeCAD's datum scope rule.
- `apply.show_tip` fixes the view after Apply and Remove.
- The solver could not re-space a frame of 10 bents. That led to the
  flat frame, seated by expression and exact to 20 bents
  (`spike-flat-frame-results.md`; the build brief
  `rebuild-flat-frame-handoff.md`).

**October 2026 — 26.3, the panel, and a review.**
- The move to the 26.3 weekly retired the spin-box workaround and pinned
  every Boolean's operand frame.
- The Timber Variables panel landed, read-only first, then editing in
  place.
- A review of the rev-2 code (PR #29) fixed four bugs, each pinned by a
  regression test:
  - Remove Timber Joint missed a component sized only from its datums.
  - Re-anchoring moved the new anchor onto the old FrameOrigin.
  - Duplicate failed on a Float parameter.
  - A renamed joint VarSet vanished from every tool.
- The same review replaced whole-document scans with direct lookups. On
  a 12-bent frame the panel went from 1.7 s to 0.1 s per click, and
  Audit's placement report from 7.1 s to 0.12 s.
- Bent filing (PRs #29 and #31), Seat Timbers' anchor and
  provisional-root rules, and parameters no longer hidden by their names
  followed.
- The subagents were rebuilt as **freecad-scout** and
  **timber-craft-researcher** (PR #30).

## Architecture cheat-sheet (why the code is shaped this way)

- **Datums belong to timbers; a joint is applied to them.** Every datum
  is placed from `facetable.FACE_TABLE`, Z out of the material, so a
  cutter modelled in −Z and an adder in +Z work on every face and end.
  Pairing is two internal-Name strings (`MateDatum`, `Joint`). The joint
  VarSet records `HostDatum`, and the cross-timber accessors live on
  their own `Accessors_J-…` VarSet, because two datums reading each
  other is a dependency cycle.
- **Copy, don't rebuild.** `apply.py` copies the template's VarSet and
  component bodies with `copyObject(objs, False)`, re-points the datum
  references (both `<<Label>>` and the bare form a cross-document copy
  leaves), mirrors only a handed template, applies the Booleans in
  `ComponentOrder`, and refuses unless every timber is still one solid.
- **Seat by expression, never by a solver.** The placing joint's seat
  VarSet computes `anchor · near · flip · far⁻¹` from the two datums;
  the placed timber's `Placement` reads it (`frame.seat`). Placing
  joints form a spanning tree from the anchor (or from a provisional
  root). A joint whose timbers are both placed closes a loop and is
  checked by its misfit. The placement tree is not the load path.
- **Structural, never label-matched, never a document scan.**
  - A joint is a VarSet carrying `HostDatum` or `TemplateSource`
    (`datums.is_joint_varset`), so the framer may rename it.
  - Its datums are found through `HostDatum` and the host's
    `MateDatum`.
  - Its components, handle and Booleans come through the `InList` of
    the joint VarSet and its accessor VarSet.
  - A timber's Dims come from the stick pad's `LengthZ` binding, and its
    seat from the `<<Seat_…>>` its Placement reads.
  - Stored references are matched in the form FreeCAD writes
    (`naming.label_ref`).
- **GUI-free cores.** `timber`, `datums`, `apply`, `frame`,
  `duplicate`, `measure`, `variables` and `template_check` have no Qt.
  `commands.py` and the `view_*` modules are the GUI. Tests drive the
  cores headless; dialogs are checked by a GUI probe and Adam's round.

## Running things

- Tests: `<FreeCAD>\bin\python.exe -W error::DeprecationWarning -m
  unittest discover -s tests`, where `<FreeCAD>` is the 26.3 weekly
  beside the checkout (location varies per machine; see CLAUDE.md →
  Environment).
- Lint a file: `... python.exe -m freecad.bentwizard.linter <file.FCStd>`
- Rebuild the shipped library: `... python.exe scripts/build_library.py`
  (writes both templates and runs the template bar on them).
- Headless scripting: use the bundled `python.exe` (`freecadcmd.exe`
  swallows `print`), import FreeCAD first, and front-load the checkout
  with `tests/_repo_path.py`. Run steps that change the document inside
  `openTransaction`/`commitTransaction`, as the commands do. Without
  them, 26.3 can leave a re-anchored timber stuck `Touched`, which the
  GUI never does.
- GUI probes: the recipe is in CLAUDE.md → Environment. Close every
  document before closing the main window, or the probe stops on a save
  prompt.
- The workbench runs live from the working tree through the junction at
  `%APPDATA%/FreeCAD/v26-3/Mod/BentWizard`. **Restart FreeCAD after any
  change**: a session started before an edit keeps the old modules, and
  a module loaded later then calls into them. A `TypeError` about
  argument counts in the panel was exactly that (2026-10-08).
- A question about FreeCAD itself (an API, or "is this ours or
  FreeCAD's?") goes to **freecad-scout**; joinery practice goes to
  **timber-craft-researcher**.
- Scratch experiments go in `scratch/` (gitignored).

## Known limitations / backlog (the roadmap has the full list)

- Per-timber face labels (a `Role` on the Dims VarSet defaulting
  `FaceLabelXPos` … for drawings and the face pickers) are not built;
  the pickers show ±X/±Y.
- Created-part roles (wedges, pegs), the dovetail on the new contract,
  and the beam tool.
- A mirrored component's source body sits at the document root, and the
  mirroring's link to it is reported out of scope on every GUI
  recompute. Only handed templates mirror (`Handed` flag); both-hands
  templates, due with the dovetail, remove mirroring entirely.
- Route (b) of the 26.3 brief, blocked upstream (finding 14, #33343).
- Export to Assembly (flat-frame workstream E, Phase 2).
