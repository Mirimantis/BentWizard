# Handoff Notes — 2026-03-01

## Branch & Commit

- **Branch:** `main` at `1e7c6db`
- **Last PR:** #8 — "Fix joint geometry and rename datum properties"
- **All changes merged and synced.** No pending work.

## What Was Done This Session

### Bug fixes (from previous session's handoff)
1. **Peg axis in through mortise & tenon** — Drawbore pegs now run perpendicular to the through-direction (cross product of primary grain and secondary approach), not parallel. Fixed in `joints/builtin/through_mortise_tenon.py` `build_pegs()`.
2. **Housed dovetail mortise origin** — Housing cut starts at the entry face of the primary member, not centered on the datum intersection. Fixed by computing `through_extent` and offsetting from center.

### Datum property rename
- Merged `Datum 1`, `Datum 2`, `Datum 3` property groups into single `Datum` group.
- Renamed `StartPoint` → `A_StartPoint`, `EndPoint` → `B_EndPoint` for alphabetical sort order in FreeCAD's property panel.
- Updated all references across 6 files: `TimberMember.py`, `TimberJoint.py`, `intersection.py`, `through_mortise_tenon.py`, `half_lap.py`, `housed_dovetail.py`.

### Dovetail joint rewrite
- Renamed from "Housed Dovetail" to "Dovetail" (class, ID, NAME). File remains `housed_dovetail.py`.
- **Fixed approach face bug** — Added `_approach_depth_dir()` helper that correctly determines the INTO direction based on which end of the secondary member is at the joint. Previously the mortise appeared on the wrong face.
- **Fixed slot orientation** — Slot now runs perpendicular to the approach face (along `taper_dir`) instead of along the primary member's length. Correct assembly direction for a slide-in dovetail.
- **Added channel mode parameters** — `channel_mode` ("Through" / "Half") controls whether slot is open on both sides or one side. `flip_channel` (boolean) reverses which side opens in Half mode.
- **No UI yet for channel_mode/flip_channel** — Parameters are stored in the JSON `Parameters` property and fully wired into geometry, but the JointPanel UI doesn't exist yet. User confirmed this is fine — will test after JointPanel is built.

## Current State of the Codebase

### Phase 1 (complete) — Skeleton and TimberMember
- `TimberMember` FeaturePython object with datum line, section, solid geometry, boolean cuts
- `AddMember` command for toolbar placement
- Workbench registration (Init.py, InitGui.py, TimberFrameWorkbench.py)

### Phase 2 (complete) — Joints
- `TimberJoint` FeaturePython object with intersection detection, cut tools, pegs, validation
- `AddJoint` command (select 2 members → detect intersection → create joint)
- Joint definition infrastructure: `base.py` (interface + data types), `intersection.py` (datum detection + JCS), `loader.py` (registry + discovery)
- Three joint definitions implemented:
  - `through_mortise_tenon` — rectangular mortise, tenon with shoulder, drawbore pegs
  - `half_lap` — symmetric notched crossing
  - `dovetail` — trapezoidal slot + tenon, Through/Half channel modes (file: `housed_dovetail.py`)

### Not yet implemented
- **UI panels** — `ui/` is empty. No ContextPanel, JointPanel, BentDesigner, StructuralReport.
- **Structural analysis** — `structural/` is empty. No graph, load accumulation, span/stress checks.
- **Remaining objects** — Bent, Frame, FrameOpening, WallOpening, GroundPlane, BearingPoint, ChimneyObject, StructuralGraph, BuildingParameters, TimberBrace.
- **Remaining joints** — blind_mortise_tenon, birdsmouth, scarf_bladed.
- **Remaining commands** — AddBent, AddBrace, AddGroundPlane, AddWallOpening, AddChimney.

## What to Work On Next

Per CLAUDE.md, the next phase is **Phase 3 — Bent and Frame Composition**:
- Bent container object (`objects/Bent.py`)
- Frame object with bent instancing and longitudinal members (`objects/Frame.py`)
- Bent Designer 2D panel (`ui/BentDesigner.py`)
- MemberID auto-assignment

Alternatively, the user may want to:
- Build the **JointPanel UI** first (needed to test channel_mode/flip_channel and to override any joint parameter)
- Add the remaining **joint definitions** (blind mortise & tenon, birdsmouth)
- Refine the **dovetail** by adding housing geometry around the dovetail pocket

## Key File Notes

| File | Notes |
|------|-------|
| `joints/builtin/housed_dovetail.py` | File still named `housed_dovetail.py` but class is `DovetailDefinition` with `ID = "dovetail"`. Loader discovers by class, not filename. |
| `joints/base.py` | `JointParameter` dataclass uses `enum_options` field (not `enum_values`). Supports types: `length`, `angle`, `integer`, `boolean`, `enumeration`. |
| `objects/TimberMember.py` | Properties are `A_StartPoint` and `B_EndPoint` (not `StartPoint`/`EndPoint`). All files use these names. |
| `objects/TimberJoint.py` | Fallback joint ID list: `["through_mortise_tenon", "half_lap", "dovetail"]`. The `_skip_touch` flag prevents infinite recompute loops. |

## Architectural Reminders

- **Never import FreeCADGui/PySide2/Qt in `objects/`, `joints/`, `structural/`** — headless requirement.
- **Every document change in a transaction** — `openTransaction()` / `commitTransaction()`.
- **`execute()` must never raise** — always try/except with fallback shape.
- **Never modify own properties inside `execute()`** — causes infinite recompute.
- **Parametric graph flows downstream only** — nothing upstream is ever modified by a downstream object.
