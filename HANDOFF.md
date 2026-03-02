# Handoff Notes — 2026-03-01

## Branch & Commit

- **Branch:** `claude/suspicious-curran` (worktree off `main` at `9f256e7`)
- **Status:** All changes uncommitted — ready for review and commit.

## What Was Done This Session

### 1. JointPanel UI (Phase 2 completion)

Built the first UI panel system for editing TimberJoint parameters:

- **`ui/param_widgets.py`** — Shared parameter widget factory. `ParameterRow` composite widget with label, typed input, revert button. Derived/override visual styling. Signal blocking during programmatic updates.
- **`ui/panels/__init__.py`** — Package marker for sub-panels.
- **`ui/panels/JointPanel.py`** — Pure QWidget panel for editing joints. Sections: joint type dropdown, connection info (read-only), grouped parameters (scrollable), color-coded validation, structural properties (auto-hidden). All edits transaction-wrapped.
- **`ui/JointTaskPanel.py`** — Minimal adapter: `self.form = JointPanel(obj)`, Close button only.
- **Modified `objects/TimberJoint.py`** — Added `doubleClicked()` (opens task panel), `updateData()` (notifies active panel), `_active_panel` tracking to ViewProvider.
- **Modified `ui/__init__.py`** — Added docstring.

User tested and confirmed fully working.

### 2. Bent Container Object (Phase 3 start)

Built the Bent container — a named transverse frame profile grouping TimberMember objects:

- **`objects/Bent.py`** — `Part::FeaturePython` proxy with:
  - Properties: `Members` (LinkList), `BentName` (String), `BentNumber` (Integer), `BentTemplate` (String, read-only), `MemberCount` (Integer, read-only)
  - `execute()` — bounding-box wireframe with 200mm padding, fallback 200×200×200 cube
  - `assign_member_ids()` — static method, groups by Role, assigns `{Prefix}{BentNum}-{position}`, only writes when changed
  - `add_member()` / `remove_member()` — static methods with single-bent enforcement, MemberID assignment inside caller's transaction
  - `find_parent_bent()` — document-scan utility for reverse lookup
  - `BentViewProvider` — wireframe display, `claimChildren()`, drag-drop support (`canDropObject`/`dropObject`), `doubleClicked()` opens BentPanel
  - `create_bent()` — factory function, sets wireframe display mode after recompute

- **`commands/AddBent.py`** — Toolbar command. Creates Bent, adds any selected TimberMembers, transaction-wrapped.

- **`ui/panels/BentPanel.py`** — Pure QWidget. Sections: Bent header (name, number, template), Members list (count, QListWidget, Add Selected / Remove buttons). Double-click member selects in viewport.

- **`ui/BentTaskPanel.py`** — Minimal adapter matching JointTaskPanel pattern.

- **`resources/icons/bent.svg`** and **`resources/icons/add_bent.svg`** — SVG icons.

- **Modified `TimberFrameWorkbench.py`** — Added `AddBent` import and `TF_AddBent` to toolbar/menu.

### Key design decisions and bug fixes during Bent implementation

1. **`Part::FeaturePython` over `App::DocumentObjectGroupPython`** — Bent needs to be selectable in 3D view via bounding-box wireframe.
2. **Forward-link only** — No `ParentBent` back-link on TimberMember. Use `find_parent_bent()` document scan for reverse lookup.
3. **MemberID writes inside transactions, NOT in `onChanged()`** — `onChanged` fires as a side effect outside undo capture. All `assign_member_ids()` calls happen in explicit methods (`add_member`, `remove_member`, panel handlers) inside open transactions. `onChanged` is a no-op.
4. **Single-bent enforcement** — `add_member()` checks `find_parent_bent()` first and removes from any existing Bent.
5. **DisplayMode "Wireframe" set after first recompute** — Mode enumeration not available until Shape is populated.
6. **200mm bounding-box padding** — Ensures wireframe is visually distinct from member solids.

User tested against 28-point checklist — all items pass including undo for MemberIDs and BentNumber changes.

## Current State of the Codebase

### Phase 1 (complete) — Skeleton and TimberMember
- `TimberMember` FeaturePython object with datum line, section, solid geometry, boolean cuts
- `AddMember` command for toolbar placement
- Workbench registration (Init.py, InitGui.py, TimberFrameWorkbench.py)

### Phase 2 (complete) — Joints + JointPanel UI
- `TimberJoint` FeaturePython object with intersection detection, cut tools, pegs, validation
- `AddJoint` command (select 2 members -> detect intersection -> create joint)
- Joint definition infrastructure: `base.py`, `intersection.py`, `loader.py`
- Three joint definitions: `through_mortise_tenon`, `half_lap`, `dovetail`
- **JointPanel UI** — parameter editing with grouped scroll, type switching, validation display
- **Shared `param_widgets.py`** — reusable ParameterRow for all future panels

### Phase 3 (in progress) — Bent and Frame Composition
- **Bent container object** — complete and tested
- Frame object — not yet started
- Bent Designer 2D panel — not yet started
- MemberID auto-assignment — complete (integrated into Bent)

### Not yet implemented
- **Remaining Phase 3** — Frame object, Bent Designer 2D panel
- **Structural analysis** — `structural/` is empty
- **Remaining objects** — Frame, FrameOpening, WallOpening, GroundPlane, BearingPoint, ChimneyObject, StructuralGraph, BuildingParameters, TimberBrace
- **Remaining joints** — blind_mortise_tenon, birdsmouth, scarf_bladed
- **Remaining commands** — AddBrace, AddGroundPlane, AddWallOpening, AddChimney

## Known Observations

- New members start with MemberID "P" (Post prefix) at creation. This doesn't update when the Role is changed — it only updates when the member is added to a Bent with a non-zero BentNumber. This is existing behavior from `create_timber_member()` in `TimberMember.py` and may warrant a future fix (Role change listener on TimberMember).

## What to Work On Next

Per CLAUDE.md Phase 3:
- **Frame object** (`objects/Frame.py`) — top-level container for Bents + longitudinal members
- **Bent Designer** (`ui/BentDesigner.py`) — 2D elevation editor for bent profiles

Or backfill:
- Remaining joint definitions (blind mortise & tenon, birdsmouth)
- MemberID update on Role change (outside Bent context)

## Key File Notes

| File | Notes |
|------|-------|
| `objects/Bent.py` | `onChanged` is intentionally a no-op. MemberID assignment only in `add_member`/`remove_member`/panel handlers. |
| `objects/Bent.py` | `_BBOX_PADDING = 200.0` — padding on each side of bounding box wireframe. |
| `joints/builtin/housed_dovetail.py` | File still named `housed_dovetail.py` but class is `DovetailDefinition` with `ID = "dovetail"`. |
| `objects/TimberMember.py` | Properties are `A_StartPoint` and `B_EndPoint` (not `StartPoint`/`EndPoint`). |
| `objects/TimberJoint.py` | Fallback joint ID list: `["through_mortise_tenon", "half_lap", "dovetail"]`. |
| `ui/param_widgets.py` | Shared widget factory — use for all future parameter panels. |

## Architectural Reminders

- **Never import FreeCADGui/PySide2/Qt in `objects/`, `joints/`, `structural/`** — headless requirement.
- **Every document change in a transaction** — `openTransaction()` / `commitTransaction()`.
- **`execute()` must never raise** — always try/except with fallback shape.
- **Never modify own properties inside `execute()`** — causes infinite recompute. Exception: write-only display fields like `MemberCount` that have no downstream listeners.
- **MemberID writes must happen inside transactions** — never in `onChanged()`.
- **Parametric graph flows downstream only** — nothing upstream is ever modified by a downstream object.
