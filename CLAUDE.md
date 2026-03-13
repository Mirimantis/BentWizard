# Bent Wizard — FreeCAD Timber Frame Workbench

## Project Overview

Bent Wizard is a FreeCAD workbench for designing and building traditional timber frame structures. It provides parametric modeling of timber members and joinery, compositional tools for building bents and frames, structural analysis with load path visualization, and fabrication outputs including cut lists and layout drawings.

The workbench is written entirely in Python and targets FreeCAD's standard workbench architecture using `App::FeaturePython` objects, Qt task panels, and Coin3D viewport overlays.

---

## Repository Structure

```
BentWizard/
├── CLAUDE.md                    # This file
├── Init.py                      # Registers workbench with FreeCAD (no-GUI)
├── InitGui.py                   # Registers GUI workbench, menus, toolbars
├── TimberFrameWorkbench.py      # Workbench class definition
│
├── objects/                     # FeaturePython object definitions
│   ├── __init__.py
│   ├── TimberMember.py          # Core member object
│   ├── TimberJoint.py           # Joint between two members
│   ├── TimberBrace.py           # Specialized brace member
│   ├── Bent.py                  # Named transverse frame profile
│   ├── Frame.py                 # Top-level building frame
│   ├── FrameOpening.py          # Opening in floor/roof plane (dormers, stairwells)
│   ├── WallOpening.py           # Door/window placeholder
│   ├── GroundPlane.py           # Foundation datum plane
│   ├── BearingPoint.py          # Load transfer point to foundation
│   ├── ChimneyObject.py         # Chimney exclusion zone
│   ├── StructuralGraph.py       # First-class structural analysis object
│   └── BuildingParameters.py   # Global load assumptions
│
├── joints/                      # Joint definition system
│   ├── __init__.py
│   ├── base.py                  # TimberJointDefinition base class + data types
│   ├── loader.py                # Discovers and registers joint definitions
│   └── builtin/                 # Built-in joint library (same interface as user joints)
│       ├── __init__.py
│       ├── mortise_tenon.py
│       ├── half_lap.py
│       ├── housed_dovetail.py       # Class is DovetailDefinition, ID is "dovetail"
│       ├── birdsmouth.py
│       └── scarf_bladed.py
│
├── commands/                    # FreeCAD command classes (toolbar/menu actions)
│   ├── __init__.py
│   ├── AddMember.py
│   ├── AddJoint.py
│   ├── AddBent.py
│   ├── AddBrace.py
│   ├── AddGroundPlane.py
│   ├── AddWallOpening.py
│   └── AddChimney.py
│
├── ui/                          # Qt panels and dialogs
│   ├── __init__.py
│   ├── ContextPanel.py          # Persistent right panel, updates on selection
│   ├── BentDesigner.py          # 2D bent profile editor
│   ├── StructuralReport.py      # Bottom structural report panel
│   ├── BuildingParametersPanel.py
│   ├── ReferenceDataEditor.py   # Lookup table editor dialog
│   └── panels/                  # Sub-panels for ContextPanel
│       ├── MemberPanel.py
│       ├── JointPanel.py
│       ├── BentPanel.py
│       └── FramePanel.py
│
├── structural/                  # Structural analysis logic
│   ├── __init__.py
│   ├── graph.py                 # networkx graph construction and traversal
│   ├── load_accumulator.py      # Tributary area load accumulation
│   ├── span_checker.py          # Span table lookups and checks
│   ├── stress_checker.py        # Member stress calculations
│   ├── racking_checker.py       # Lateral stability checks
│   └── color_overlay.py        # Coin3D force flow visualization
│
├── data/                        # Bundled reference tables (READ-ONLY)
│   ├── species_properties.csv   # NDS species/grade Fb, Fv, E values
│   ├── span_tables.csv          # Allowable spans by section and load
│   ├── joint_capacities.csv     # Joint allowable moment, shear, stiffness
│   ├── section_properties.csv   # S, I, A for standard timber sections
│   └── load_presets.csv         # Roofing/flooring material dead load presets
│
├── userdata/                    # User-editable overrides (written at runtime)
│   └── (mirrors data/ structure, takes precedence over base data/)
│
└── resources/
    └── icons/                   # SVG icons for toolbar and joint picker
```

---

## Core Architecture Principles

### 1. Parametric Graph Direction

All geometry flows strictly downstream. Nothing upstream is ever modified by a downstream object.

```
BuildingParameters + ReferenceDataLibrary + GridDatum
        ↓
GroundPlane → BearingPoint
        ↓
Frame → Bent
        ↓
TimberMember (datum line — the primary editable entity)
        ↓
TimberJoint (intersection detection, joint geometry)
        ↓
Member solid geometry + joint boolean cuts
        ↓
StructuralGraph
        ↓
Load accumulation → span/stress/racking checks → color overlay → BOM output
```

### 2. GUI / No-GUI Separation

**Critical:** Never import `FreeCADGui`, `PySide2`, or any Qt module in object files (`objects/`, `joints/`, `structural/`). These modules must work headless. All GUI code lives exclusively in `commands/` and `ui/` and in ViewProvider classes within object files (loaded conditionally).

Pattern for conditional GUI code in object files:
```python
import FreeCAD
if FreeCAD.GuiUp:
    import FreeCADGui
    # ViewProvider class definition here
```

### 3. Transactions for Undo

Every user-initiated document change must be wrapped in a transaction:
```python
FreeCAD.ActiveDocument.openTransaction("Add Timber Member")
# ... make changes ...
FreeCAD.ActiveDocument.commitTransaction()
```
Never modify the document outside a transaction.

### 4. Safe execute() Methods

The `execute()` method of every FeaturePython object must never raise an exception — FreeCAD will put the object in a permanent error state. Always use try/except with a fallback shape:
```python
def execute(self, obj):
    try:
        obj.Shape = self._build_solid(obj)
    except Exception as e:
        FreeCAD.Console.PrintError(f"TimberMember execute failed: {e}\n")
        obj.Shape = Part.makeBox(1, 1, 1)  # fallback
```

### 5. No Property Modification During execute()

Never modify an object's own properties inside `execute()`. This causes infinite recompute loops. Computed outputs should only be written to properties that no other object links to.

---

## Key Object: TimberMember

The fundamental building block. Every timber in the frame is a `TimberMember`.

### Properties

| Property | Type | Category | Notes |
|---|---|---|---|
| StartPoint | Vector | Datum | Start of datum line, snappable |
| EndPoint | Vector | Datum | End of datum line, snappable |
| SupportFractions | FloatList | Datum | Fractional positions of supports along datum (enables cantilevers). Simple beam = [0.0, 1.0] |
| Width | Length | Section | Member width (narrow face) |
| Height | Length | Section | Member height (deep face) |
| ReferenceFace | Enumeration | Section | Top / Bottom / Left / Right |
| Species | Enumeration | Material | Drives structural lookups |
| Grade | Enumeration | Material | Drives structural lookups |
| Role | Enumeration | Structure | Post / Beam / Rafter / Purlin / Girt / TieBeam / Brace / Header / Trimmer / Ridge / Valley / Sill / Plate / FloorJoist / SummerBeam |
| StartCutAngle | Angle | Cuts | Degrees from perpendicular |
| EndCutAngle | Angle | Cuts | Degrees from perpendicular |
| MemberID | String | Identity | Auto-generated (e.g. P2-1), user-overridable |
| FabricationSignature | String | Identity | Hash of normalized joint+section+length, computed |
| InternalUUID | String | Identity | Stable UUID, never changes, used by parametric graph |

### MemberID Convention

`[TypePrefix][BentNumber]-[PositionWithinBent]`

Type prefixes: P (post), B (beam/tie beam), R (rafter), PL (plate), PU (purlin), BR (brace), G (girt), S (sill), RD (ridge), H (header)

Examples: `P2-1` (first post in bent 2), `PU-B2-3` (third purlin in bay 2), `BR2-1` (first brace in bent 2)

Longitudinal members use bay reference (between bent N and bent N+1 = bay N).

**Important:** `MemberID` is a display label only. Internal links always use `InternalUUID`. When a new bent is inserted, MemberIDs renumber but UUIDs never change. Warn the user when renumbering occurs.

### FabricationSignature

A normalized hash comparing: species, grade, section dimensions, finished length (after end cuts), end cut angles, and joint layout in local member coordinate space (joint type + position as fraction of length + face). Two members with identical signatures can be fabricated together. Mirror images have different signatures.

---

## Key Object: TimberJoint

Created automatically when two datum lines intersect or come within a tolerance (default 0.5"). Not placed manually.

### Properties

| Property | Type | Notes |
|---|---|---|
| PrimaryMember | Link | The housing member (larger/primary) |
| SecondaryMember | Link | The tenoned/secondary member |
| IntersectionPoint | Vector | World-space origin of joint CS, derived |
| IntersectionAngle | Float | Angle between datum lines in degrees |
| IntersectionType | Enumeration | EndpointToMidpoint / MidpointToMidpoint / EndpointToEndpoint |
| JointType | String | ID string from joint registry (e.g. "mortise_tenon") |
| Parameters | String | JSON-serialized ParameterSet values |
| AllowableMoment | Float | From reference data, computed |
| AllowableShear | Float | From reference data, computed |
| RotationalStiffness | Float | From reference data, computed |
| AcceptsLateralPointLoad | Bool | Flag for stair/guardrail connections |
| ValidationResults | String | JSON list of current validation messages |

### Joint Coordinate System

Every joint has a local coordinate system derived purely from datum geometry:
- **Origin:** intersection point in world space
- **Primary axis:** direction of primary member datum
- **Secondary axis:** direction of secondary member datum  
- **Normal:** cross product of primary and secondary axes
- **Angle:** intersection angle in degrees

All joint cut geometry is defined in this local space and transformed to world space. This makes joint definitions position-independent.

### Intersection Type → Joint Family Suggestions

| Intersection Type | Suggested Joint Families |
|---|---|
| EndpointToMidpoint | Mortise & Tenon, Housed Dovetail |
| MidpointToMidpoint | Half Lap, Cross Lap |
| EndpointToEndpoint | Scarf joints |

---

## Joint Definition Interface

All joints — built-in and user-defined — implement the same interface. Built-in joints in `joints/builtin/` are just pre-installed plugins.

```python
class TimberJointDefinition:
    NAME = ""           # "Mortise & Tenon"
    ID = ""             # "mortise_tenon" — stable, unique
    CATEGORY = ""       # "Mortise and Tenon"
    DESCRIPTION = ""
    ICON = ""           # path relative to definition file
    DIAGRAM = ""        # path relative to definition file
    PRIMARY_ROLES = []  # compatible primary member roles
    SECONDARY_ROLES = []
    MIN_ANGLE = 45.0
    MAX_ANGLE = 135.0

    def get_parameters(self, primary, secondary, joint_cs) -> ParameterSet
    def build_primary_tool(self, params, primary, secondary, joint_cs) -> Part.Shape
    def build_secondary_profile(self, params, primary, secondary, joint_cs) -> SecondaryProfile
    def build_pegs(self, params, primary, secondary, joint_cs) -> list[PegDefinition]
    def validate(self, params, primary, secondary, joint_cs) -> list[ValidationResult]
    def fabrication_signature(self, params, primary, secondary, joint_cs) -> dict
    def structural_properties(self, params, primary, secondary) -> JointStructuralProperties
```

### ParameterSet

Parameters have types (`length`, `angle`, `integer`, `boolean`, `enumeration`), auto-derived defaults based on member geometry, user-override capability, min/max bounds, and group labels for UI organization. Derived parameters are shown visually distinct in the UI. Clicking a derived value activates an override input.

### User-Defined Joints

Drop a `.py` file containing a `TimberJointDefinition` subclass into `%APPDATA%/TimberFrame/joints/`. The loader discovers it on next launch. No registration required. User joints have identical capabilities to built-in joints.

---

## Structural Graph

A first-class document object (`StructuralGraph`) that recomputes whenever any upstream member or joint changes. Uses `networkx` (bundled with workbench) for graph operations.

### Load Path

```
Roof surface loads (from BuildingParameters + tributary area)
    → Rafters
    → Purlins
    → Bent girts / tie beams
    → Posts
    → Sill beams
    → BearingPoints on GroundPlane
```

Cantilevers invert this — load flows back inward to the root joint, producing uplift at the interior connection. The graph handles this via the `SupportFractions` property on `TimberMember`.

### Checks Performed

1. **Load path continuity** — every member has a complete path to a BearingPoint. Disconnected members flagged immediately.
2. **Span checks** — actual span vs. allowable span from `span_tables.csv` for this section, species, and load.
3. **Member stress checks** — bending: `M ≤ Fb × S`, shear: `V ≤ Fv × A × (2/3)`, deflection: `Δ ≤ L/360`.
4. **Racking checks** — lateral demand per bent vs. sum of brace contributions. Uses semi-rigid joint model with rotational stiffness from joint capacity tables.
5. **Bearing point loads** — vertical and horizontal reactions at each foundation bearing point.

### Color Overlay

When structural mode is active, member display colors shift to a heat map of load / capacity ratio:
- Blue: < 30% capacity
- Green: 30–70%
- Yellow: 70–90%
- Orange: 90–100%
- Red: > 100% (over limit)
- Grey: not in load path / unchecked

Force flow direction shown as animated chevrons along member axis moving from load source toward bearing points (Coin3D SoLineSet with shader). Toggle with structural mode button.

---

## Ground Plane and Foundation

One or more `GroundPlane` objects at defined Z elevations. Default: single plane at Z=0, created automatically, requires no user interaction for simple buildings.

Post datum lines project downward (vertical ray) to the first GroundPlane below them. The intersection becomes a `BearingPoint` with computed vertical load and horizontal shear.

Sill beams between adjacent BearingPoints on the same GroundPlane are parametrically derived — never drawn manually.

**Split-level:** Add a second GroundPlane at a different Z. The step transition edge is exported as geometry for the foundation designer but not structurally modeled. Sill beams that would span a vertical step are flagged as errors.

**ChimneyObject** creates its own `ChimneyBearingPoint` excluded from the frame's bearing schedule. Generates `FrameOpening` instances at each floor/roof plane it penetrates. Enforces a 2" clearance zone around its footprint (code-based, editable).

---

## Special Member and Opening Types

### Cantilevered Members
`SupportFractions` on `TimberMember` lists fractional positions of supports. A cantilever is a member where the last support is not at the endpoint. Load path traversal uses this to calculate root moment and uplift correctly.

### FrameOpening
Lives in a specific plane (roof or floor). Has a polygonal boundary (supports non-rectangular for stair rake). Knows which member datums it interrupts. Generates header and trimmer `TimberMember` objects at its edges. Handles load redistribution from interrupted members to headers.

Created as a side effect of placing: `ChimneyObject`, dormer structures, stairwell definitions.

### WallOpening
Lives in a wall bay between two posts. Properties: type (Door / Window / GarageDoor), unit width and height, sill height, rough opening dimensions (auto-derived = unit + 1.5" each side), bay reference. No structural participation. Generates a placeholder solid for visualization. No header required (timber frame is structurally complete independent of wall openings).

### TimberBrace
Subtype of `TimberMember`. References two `TimberJoint` objects of compatible topology (not arbitrary points). Enforces angle constraint: 30°–60° from post axis. Performs clearance check against all neighboring members within both referenced joints. Contributes racking resistance value to its bent's lateral check.

---

## Building Parameters

Top-level document object feeding the structural graph:

- **Roof:** material (with dead load psf preset), snow load zone or manual psf, calculated roof snow load
- **Floors:** occupancy type (Residential 40psf / Storage 125psf / etc.), dead load
- **Wind:** basic wind speed zone or manual entry
- **Advanced:** manual overrides for any value

All presets stored in `data/load_presets.csv`, user-editable via same Reference Data Editor.

---

## Reference Data System

Four table families, all CSV format:

| File | Content | Source |
|---|---|---|
| `species_properties.csv` | Fb, Fv, E by species and grade | NDS 2018 |
| `span_tables.csv` | Allowable spans by section, species, load | AWC span tables |
| `joint_capacities.csv` | Allowable moment, shear, rotational stiffness by joint type / section / species / peg config | TFEC 1-2007 + FEA-derived |
| `section_properties.csv` | S, I, A for standard timber sections | Computed |
| `load_presets.csv` | Dead load psf by roofing/flooring material | ASCE 7 |

**User override pattern:** Base tables in `data/` are read-only. User additions and edits go to `userdata/` (same filenames). At lookup time, user table is checked first; if no match, base table is used. User rows are visually distinct in the Reference Data Editor. Base rows can be duplicated to user table for override but never edited in place.

---

## Member Naming and Fabrication Identity

### MemberID Assignment
Auto-generated when a member is added to a Bent or Frame. Based on role prefix + bent/bay number + position within that bent/bay. Stored as a property, user-overridable. Regenerated if frame structure changes (with warning to user).

### InternalUUID
A stable UUID assigned at creation, never changes regardless of renumbering. All parametric links use UUID. MemberID is display only.

### FabricationSignature
Normalized hash of: species, grade, section (W×H), finished length, start cut angle, end cut angle, and for each joint: type, position as fraction of length, face, and key parameters — all expressed in local member coordinate space.

Members with identical signatures = fabrication-identical = can be cut as a group from a single layout.

Braces: signature includes section, species, length, and both end cut angles. Symmetric braces of same type are identical regardless of which bent or face.

### Cut List Output Format
```
FABRICATION GROUP 7 — Qty: 4
  Species:  Douglas Fir, Select Structural
  Section:  6" × 8"
  Length:   14'-6"
  End cuts: Square both ends
  Joints:   Mortise @ 12" from start — 2"W × 5.25"H × 6" deep, N face, 1×1" peg
             Mortise @ 13'-2" from start — 2"W × 5.25"H × 6" deep, N face, 1×1" peg
  Members:  P2-1, P3-1, P4-1, P5-1
```

---

## UI Architecture

### Layout
- **Left:** Model tree (FreeCAD native) + Properties panel
- **Center:** 3D viewport (primary workspace)
- **Right:** Contextual panel (persistent, updates on selection)
- **Bottom:** Structural Report panel (persistent, collapsible)
- **Top:** Toolbar with primary actions

### Interaction Modes
- **Browse:** default, click to select
- **Place:** active command, snap indicators in viewport, Escape cancels
- **Edit:** double-click object, datum handles appear, task panel shows full editing UI
- **Joint:** two members selected + Add Joint, or double-click existing joint
- **Structural:** toggle, activates color overlay and expands report panel

### Contextual Right Panel
Updates based on current selection. Shows editable properties for selected object with derived values visually distinct (dimmer, with indicator). Clicking a derived value activates an override input. Inline validation — no modal error dialogs.

### Viewport Handles
Selected `TimberMember` shows draggable sphere handles at datum endpoints (Coin3D SoDragger). Snap system activates on drag: priority order = existing datum endpoint > datum intersection > grid point > free. Shift key suppresses snapping. Connected members at shared endpoint follow the drag.

### Member Placement Flow
1. Click Add Member toolbar button
2. Right panel shows mini-form: Role, Species, Section (pre-populated from last used)
3. Click first point in viewport (snaps)
4. Preview line extends to cursor
5. Click second point
6. Member created, joint detection runs, joints form automatically
7. Right panel immediately shows new member properties
8. Can place next member immediately or Escape to exit

### Structural Report Panel
Shows errors (blocking), warnings (non-blocking), passed checks. Each row is clickable — selects the implicated object. `[Apply]` on suggestions triggers auto-fix as an undoable transaction. `[Export]` generates PDF report.

### Bent Designer
Opens from Bent context panel. 2D elevation view. Members shown as rectangles. Datum endpoint handles draggable. Snap grid configurable. Templates: King Post, Queen Post, Hammer Beam, Scissors Truss (stored as bent definition files, user can save own templates).

---

## Development Phases

### Phase 1 (complete) — Skeleton and TimberMember
- Register workbench with FreeCAD
- Init.py, InitGui.py, workbench class
- TimberMember FeatureObject: datum line, section, solid geometry, properties panel
- Basic 3D grid and datum endpoint snapping
- Workbench installable and member placeable

### Phase 2 (complete) — Joints
- Datum intersection detection
- JointCoordinateSystem
- Joint definition base class and loader
- Through mortise & tenon, half lap, dovetail
- Boolean cuts parametrically updating

### Phase 3 (in progress) — Bent and Frame Composition
- Bent container object
- Frame object with bent instancing and longitudinal members
- Bent Designer 2D panel
- MemberID auto-assignment

### Phase 4 — Structural Graph
- networkx graph construction
- Load path tracing
- BuildingParameters object
- Span and stress checks
- Color overlay

### Phase 5 — Foundation
- GroundPlane object
- BearingPoint projection
- Sill beam auto-generation
- Bearing point schedule export
- Split-level support

### Phase 6 — Advanced Structural
- Full stress checks (bending, shear, deflection)
- Racking checks
- Joint capacity table lookups
- Suggestion engine

### Phase 7 — Openings and Special Members
- FrameOpening (dormers, stairwells)
- WallOpening (doors, windows)
- ChimneyObject
- Cantilever load path support
- TimberBrace with clearance checking

### Phase 8 — Outputs
- Cut list / BOM generation
- FabricationSignature grouping
- Layout drawing output
- PDF structural report export

### Phase 9 — Visual Design and User Preferences
- Polish all UI panels, dialogs, and editors for visual consistency
- Custom icons for toolbar actions, joint picker, and model tree items
- Timber material textures and grain direction visualization in 3D viewport
- Color theme support (respect FreeCAD's light/dark preferences throughout)
- User preferences panel: default grid spacing, snap tolerances, member colors, datum line styles, label visibility
- Bent Designer visual refinements: improved handle styling, selection highlights, hover effects
- Structural overlay color scheme customization
- Splash/about dialog with workbench branding
- Tooltip and status bar polish for all interactive elements

---

## Dependencies

- **FreeCAD** — host application, provides Part workbench (OpenCASCADE), Coin3D rendering, Qt UI
- **networkx** — graph operations for StructuralGraph. Bundle with workbench or install via FreeCAD's pip.
- **Python standard library** — json, csv, hashlib, uuid, pathlib, importlib, inspect

No other external dependencies. All reference data is bundled as CSV.

---

## FreeCAD-Specific Notes

- FreeCAD's embedded Python version may differ from system Python. Always test in FreeCAD's console.
- Install the workbench by symlinking or copying the `BentWizard/` folder to FreeCAD's `Mod/` directory.
- FreeCAD Mod directory on Windows: `%APPDATA%\FreeCAD\Mod\`
- Use `FreeCAD.Console.PrintMessage()`, `.PrintWarning()`, `.PrintError()` for logging — not print().
- `App::PropertyFloatList` stores lists of floats; use JSON string properties for complex structured data.
- ViewProvider classes must implement `getIcon()`, `attach()`, `updateData()`, `onChanged()`, `getDisplayModes()`, `getDefaultDisplayMode()`, `setDisplayMode()`, `onDelete()`.
- Coin3D scene graph is accessed via `vobj.RootNode` in the ViewProvider.

---

## Decisions Log

Record any non-obvious direction choices made during development — what was decided, why, and what alternatives were considered. Most recent first.

<!--
Template:
### YYYY-MM-DD — Short title
**Decision:** What was chosen.
**Reason:** Why this direction was taken.
**Alternatives considered:** What else was on the table and why it was rejected.
-->

### 2026-03-12 — Face-referenced joint toolkit replaces vector-based geometry
**Decision:** New `joints/toolkit.py` module with `MemberFaceContext` dataclass and face-referenced helper functions (`face_pocket`, `shoulder_cut`, `tenon_block`, `tapered_tenon`, `lap_notch`, etc.). All three built-in joints rewritten to use the toolkit. The toolkit identifies the actual approach face of the primary member via ray-casting, then builds all cut geometry referenced to that face: pockets go straight into the face (perpendicular to face normal), shoulders sit in the face plane, tenons align with the pocket direction. `common()` with the raw member solid clips pockets to face boundaries at any angle.
**Reason:** The previous implementation built cut geometry using direction vectors computed from datum lines (`_approach_depth_dir`, `sec_x`, etc.) and extruded 2D profiles along those vectors. At 90 degrees, these vectors happened to align with face normals, producing correct geometry. At other angles, three bugs emerged: (1) tenon extrusion along `sec_x` didn't match mortise direction along `depth_dir`, (2) shoulder cuts perpendicular to `sec_x` didn't sit flat against the primary's face, (3) half-lap hardcoded top/bottom faces by local Z. The face-referenced approach fixes all three by deriving all geometry from the actual approach face rather than from abstract direction vectors.
**Alternatives considered:** (1) Fix direction vectors to compute exact face normals analytically — rejected, each joint would need its own angle-correction math, not composable. (2) Keep direction vectors but use smarter extrusion clipping — rejected, `common()` is simpler and automatically correct. (3) Required toolkit (all joints must use it) — rejected, toolkit is optional so advanced users can build raw Part.Shapes.

### 2026-03-11 — Member-joint awareness: utility function over back-reference property
**Decision:** TimberMember does NOT get back-reference properties (JointLinks, JointFractions) pointing to its joints. The existing document-scan pattern (`_collect_joint_cuts()`, `_collect_extensions()`) is kept. The Bent Designer reads from the Bent's existing `Joints` property list to correlate joints with members.
**Reason:** Adding member → joint Link properties would create a circular dependency in FreeCAD's recompute graph (member → joint → member), violating the "parametric graph flows downstream only" rule. Writing computed `JointFractions` in `execute()` would violate "no property modification during execute" or require a separate sync mechanism. The document scan handles 20-50 objects in microseconds — negligible vs. OCC boolean operations. `SupportFractions` is reserved for structural load path (Phase 4), not joint positions.
**Alternatives considered:** (1) `App::PropertyLinkList` back-reference — circular dependency risk. (2) Computed JointFractions property — sync complexity. (3) Cached utility module — considered but YAGNI; the scan is fast enough as-is and the Bent's Joints list suffices for the Bent Designer.

### 2026-03-11 — IsBroken as explicit property, not ValidationResults parse
**Decision:** Added `IsBroken` (read-only Bool), `LastValidPoint`, `LastValidPrimaryPoint`, `LastValidSecondaryPoint` (hidden Vectors) to TimberJoint. `IsBroken` is set to True in both broken paths (OUT_OF_TOLERANCE, NO_INTERSECTION) and False in the valid path. The LastValid* properties store the last-good intersection geometry and are NOT overwritten when the joint breaks.
**Reason:** Consumers (ViewProvider, Bent Designer, future StructuralGraph) need a fast boolean check, not JSON parsing of `ValidationResults`. The per-member last-valid points (`LastValidPrimaryPoint`, `LastValidSecondaryPoint`) enable showing broken-joint markers at the correct position on each member's datum. Safe to write in execute() under the same rationale as IntersectionAngle — display-only, no downstream links.
**Alternatives considered:** Parsing ValidationResults JSON for "OUT_OF_TOLERANCE" code — too slow for paint callbacks. A single LastValidPoint midpoint — insufficient, need per-member positions to show where each timber was connected.

### 2026-03-11 — Unknown joint type: error + Placeholder fallback, not backward-compat aliases
**Decision:** When `_recompute_joint()` encounters an unknown `JointType` ID (definition lookup returns None), it prints an error message and resets `obj.JointType = "placeholder"`. The previous alias system (`_ALIASES` dict in `joints/loader.py` mapping old IDs like `"through_mortise_tenon"` → `"mortise_tenon"`) was removed entirely. The migration block that checked `definition.ID != joint_type_id` was also removed.
**Reason:** The user explicitly rejected silent backward compatibility. Unknown joint types should be surfaced as errors so the user knows something is wrong and can reassign the joint. The Placeholder state is the correct recovery — it shows the joint exists but needs assignment, matching the same state as a newly created joint.
**Alternatives considered:** (1) `_ALIASES` dict for backward-compat migration — rejected by user, masks errors. (2) Return with invisible 1x1x1mm box — rejected, leaves joint in limbo with no cuts and no visual feedback.

### 2026-03-11 — Broken joint 3D visual: octahedra at timber faces + gap cylinder
**Decision:** When `IsBroken` is True, the joint's Shape becomes a compound of: (1) octahedron markers at where the gap cylinder exits each timber's face, (2) a single thin gap cylinder between current closest points. ViewProvider colors these red via `_update_color()`. The octahedron offset from datum center is scaled by `(1 - alignment)` where `alignment = abs(gap_dir · member_axis)` — so endpoint exits (gap along member axis) get near-zero offset while midpoint exits (gap perpendicular to axis) get the full `max(W,H)/2` offset.
**Reason:** The datum point is at the member center for midpoint intersections but at the endpoint for endpoint intersections. A fixed `half_dim` offset along gap direction works for midpoints (side face exit) but overshoots for endpoints (end face exit), placing the marker in the gap. The alignment-scaled offset handles both cases correctly.
**Alternatives considered:** (1) Fixed spheres at datum center — hidden inside timber. (2) Three cylinders (two displacement + gap) — confusing. (3) Uniform half_dim offset for all members — secondary marker floated in gap for endpoint connections.

### 2026-03-11 — JointItem in Bent Designer: 250% markers behind handles, scene coords for broken
**Decision:** `JointItem` uses `ItemIgnoresTransformations` for non-broken joints (fixed screen-size diamond/circle markers at z=4) but NOT for broken joints. Broken joints paint in scene coordinates with cosmetic pens. Marker size is 25px half-size (250% of original 10px). Z-ordering: members z=1, joints z=4, translate handles z=9, endpoint handles z=10 — so joint markers are visible around handle edges but don't block handle interaction.
**Reason:** Non-broken joint markers should stay a fixed pixel size. But broken-joint visualization connects two potentially distant scene positions — screen-space coordinates would clip or mis-position the connecting line. The 250% size increase ensures markers are clearly visible and distinguishable from endpoint handles. Z=4 (behind handles at z=10) allows clicking the marker edges while keeping handles interactive.
**Alternatives considered:** (1) z=5 with original 10px size — markers hidden behind endpoint handles. (2) All scene coords — markers would shrink to invisible at wide zoom. (3) Separate scene-level line items for broken visualization — more items to manage.

### 2026-03-10 — Datum snap uses perpendicular distance, not total distance to tick
**Decision:** The datum-aligned grid snap ranks candidates by perpendicular distance to the datum line, not the total Euclidean distance from cursor to the grid-ticked snap point. A separate `DATUM_SNAP_TOLERANCE = 30.0` (50% wider than `SNAP_TOLERANCE`) is used for activation.
**Reason:** The original implementation compared the diagonal distance from cursor to the snapped grid tick on the datum. When the cursor was between two ticks, the along-datum offset dominated the total distance, easily exceeding the 20-unit tolerance — especially on vertical datums where the entire offset was in one axis. Using perpendicular distance (closeness to the datum *line*) correctly captures user intent: if you're near the line, you want to snap along it.
**Alternatives considered:** (1) A single larger tolerance for the total distance — would over-activate the datum snap when the cursor is far from the line but near a tick. (2) Removing the distance check entirely — rejected, needs a sanity bound to avoid snapping when the cursor is nowhere near any datum.

### 2026-03-10 — Live drag preview via MemberItem endpoint update, not FreeCAD recompute
**Decision:** During endpoint drags in the Bent Designer, the member rectangles update live by calling `MemberItem.update_endpoint_2d()` from `HandleItem.itemChange()`. FreeCAD objects are not modified until mouse release. The scene `_member_items` dict maps `member.Name` → `MemberItem` for O(1) lookup.
**Reason:** Updating FreeCAD objects on every mouse move would trigger full recompute cycles (member → joints → boolean cuts → structural graph) at 60+ Hz, which would be unusably slow. The Qt scene update is trivial math (hypot, atan2, setRect, setPos, setRotation) with no FreeCAD calls. The full rebuild on release corrects any drift from the cosmetic preview.
**Alternatives considered:** (1) Datum line preview only — simpler but loses cross-section width visualization. (2) Ghost/transparent copies — more items to manage and clean up. (3) Throttled FreeCAD updates — still too slow for smooth interaction.

### 2026-03-10 — Datum centerlines as MemberItem child items
**Decision:** Each MemberItem creates a `QGraphicsLineItem` child for the datum centerline, drawn in local coordinates at y=0 from `-length/2 - overshoot` to `+length/2 + overshoot`. The line inherits the parent's position and rotation transform, so it follows drag updates automatically.
**Reason:** Making the datum a child item means zero additional work for live drag updates — `_update_geometry()` already sets position/rotation on the parent, and the child follows. A scene-level datum item would require separate tracking and synchronization.
**Alternatives considered:** Scene-level line items with manual position updates — more code, no benefit, would need explicit drag synchronization.

### 2026-03-09 — Half-channel shoulder trim matches housing boundary, not centerline
**Decision:** The trim slab that cuts back the non-tail half of the secondary in half-channel mode now starts at the housing pocket's non-tail edge instead of at the secondary centerline. The housing boundary is computed by replicating the primary's `chan_half` and `hous_chan` logic: `housing_non_tail = chan_half/2 - hous_chan/2` in open_dir from approach face. Only material outside the housing footprint is trimmed.
**Reason:** The housing pocket in the primary is wider than the half-tail (it accommodates the full secondary cross-section + clearance) and offset toward the open side. The original trim at the centerline over-trimmed — it removed material that should seat into the housing pocket on the non-tail side of center.
**Alternatives considered:** (1) Building the shoulder cut from the approach face and keeping a housing-shaped block — more complex boolean chain for the same result. (2) Using the approach face for both halves (no housing on the secondary) — would leave the tail side unsupported in the housing.

### 2026-03-09 — _cuts_changed() also compares Parameters JSON
**Decision:** `TimberJoint._cuts_changed()` now stores and compares the Parameters JSON string alongside bounding boxes. Members are touched when either the BB or the parameters change.
**Reason:** Bounding-box-only comparison missed interior geometry changes where the cut shape changed but its outer envelope didn't. Specifically, increasing `housing_depth` in half-channel dovetail mode changed the housing pocket depth and shoulder face position, but neither the primary nor secondary cut tool's bounding box changed (the socket extends deeper than the housing, dominating the BB). Adding the Parameters JSON as a comparison key catches all parameter-driven changes without complicating the BB logic.
**Alternatives considered:** (1) Making the boolean overshoot scale with housing_depth to force BB changes — hacky, only fixes one specific case. (2) Shape hashing — potentially expensive and not readily available in OCC. (3) Always touching members — would reintroduce the infinite-recompute-loop problem that `_cuts_changed()` was created to solve.

### 2026-03-09 — Socket depth max 50% in Through mode, 75% in Half mode
**Decision:** `socket_depth.max_value` is dynamically set in `update_dependent_defaults()` based on `channel_mode`: Through = 50% of `primary_depth`, Half = 75%. Added `primary_depth` as a read-only reference parameter (= `through_extent`) so the max can be recomputed after deserialization.
**Reason:** In Through mode, the socket passes through the full primary width, so exceeding 50% compromises the remaining material on both sides. In Half mode, the untouched half preserves structural integrity, allowing a deeper socket.
**Alternatives considered:** A single fixed max (75%) for both modes — rejected, Through mode at 75% leaves only 25% of the primary's depth on the back side, which is structurally inadequate.

### 2026-03-09 — Dovetail half-channel tail and flare clamping
**Decision:** Two fixes to the dovetail joint: (1) Half-channel mode now reduces the tail (secondary tenon) to half-width and offsets it to match the half-channel socket. `build_secondary_profile()` computes `tail_extent_w = sec_extent_w / 2.0` and offsets `tail_center` by `sec_extent_w / 4.0` in the open direction. Both the tenon and the keep zone use the offset center and reduced extent. (2) Added `sec_extent_h` as a read-only reference parameter storing the secondary member's extent along primary grain. `update_dependent_defaults()` now dynamically clamps `dovetail_height.max_value` and `dovetail_angle.max_value` so that `flare_height` (the wide end of the tail) never exceeds `sec_extent_h`. The formula: `max_dh = sec_ext_h - 2 * effective_depth * tan(angle)` and `max_angle = atan((sec_ext_h - dh) / (2 * effective_depth))`. Current values are clamped if they exceed the new maxima. Flare is recomputed after clamping.
**Reason:** (1) The half-channel socket correctly cut only half the primary, but the tenon remained full-width, leaving half the tail protruding outside the socket. (2) Large `dovetail_height` or `dovetail_angle` values could produce a flare wider than the secondary member, creating empty gaps at the corners of the tenon. Clamping the UI controls prevents the user from reaching these invalid configurations.
**Alternatives considered:** (1) For the flare limit: validation-only (warning/error) without clamping — rejected, the user specifically requested that the controls stop at the limit. (2) Storing `sec_extent_h` as a custom attribute on ParameterSet — rejected, wouldn't survive JSON round-trip in the deserialization pipeline.

### 2026-03-08 — Dovetail joint rewrite: simplified parameters and working housing
**Decision:** Complete rewrite of `housed_dovetail.py`. New parameter set: `socket_depth`, `dovetail_angle` (14° default), `dovetail_height` (half secondary extent along primary grain), `housing_depth`, `clearance`, `channel_mode`, `flip_channel`, and `flare_height` (read-only derived). Removed `tail_width`, `tail_base_width`, `tail_end_width`. Dovetail is always full secondary member width. Added `_dovetail_axes()` helper (same pattern as M&T's `_mortise_axes()`). Housing pocket implemented as a rectangular cut from approach face to `housing_depth`, fused with the dovetail socket. Shoulder face offset by `housing_depth` into primary (M&T pattern). `flare_height = dovetail_height + 2 * (socket_depth - housing_depth) * tan(angle)`.
**Reason:** The previous implementation had multiple interrelated bugs: (1) `housing_depth` parameter existed but was never used in geometry building. (2) `tail_width` changes updated the secondary profile but not the primary socket — the `_cuts_changed()` bounding box comparison didn't detect interior-only changes because the shoulder cut's BB was always the full cross-section. (3) `dovetail_angle`, `tail_base_width`, and `tail_end_width` were over-determined — given any two plus socket depth, the third is fixed. (4) Axes were inconsistent, mixing `sec_y`/`sec_z` with `pri_x`/`taper_dir`.
**Alternatives considered:** (1) Keeping `tail_width` as a parameter — rejected, it was the source of the boolean propagation bug, and in traditional timber framing the dovetail is always full width of the secondary member. (2) Making `flare_height` editable instead of `dovetail_height` — rejected, the craftsman thinks in terms of the narrow end (neck) height, the flare follows from the angle. (3) Fixing `_cuts_changed()` to detect interior changes — rejected, the bounding box approach is fundamentally limited for this case, and removing the problematic parameter is cleaner than complicating the recompute pipeline.

### 2026-03-08 — Mortise orientation derived from primary grain direction
**Decision:** The mortise/tenon rectangle orientation is now computed from the primary member's grain axis (length direction), projected into the cross-section plane perpendicular to the approach direction. A new `_mortise_axes()` helper returns `(width_dir, height_dir)` where height always runs along the primary grain. The secondary member's cross-section extents are projected onto these axes for tenon dimension defaults and limits.
**Reason:** The previous implementation used the secondary member's local axes (`sec_y`, `sec_z`) to orient the mortise. This produced correct results for orthogonal connections (beam into post) by coincidence, but for angled connections (braces, rafters) the mortise could cut across the primary's grain rather than along it. In real timber framing, the mortise height always runs with the primary grain to preserve structural integrity.
**Alternatives considered:** (1) Keeping secondary-based orientation — rejected, physically incorrect for angled connections and would cut across the primary grain. (2) Using a fixed world-axis alignment — rejected, wouldn't work for non-vertical/non-horizontal primary members.

### 2026-03-08 — Renamed through_mortise_tenon to mortise_tenon
**Decision:** Class `ThroughMortiseTenonDefinition` renamed to `MortiseTenonDefinition`, ID `"through_mortise_tenon"` changed to `"mortise_tenon"`, file renamed from `through_mortise_tenon.py` to `mortise_tenon.py`.
**Reason:** The joint already handled blind and housed mortise configurations via the `tenon_length` and `housing_depth` parameters. The "Through" prefix was misleading since the joint wasn't limited to through mortise configurations.
**Alternatives considered:** Keeping the old name for backwards compatibility — rejected, no saved documents rely on the ID yet (Phase 3 still in progress).

### 2026-03-08 — Bent Designer grid as scene items, not drawBackground
**Decision:** Grid lines are added as `QGraphicsLineItem` objects during `rebuild()` instead of being painted in `QGraphicsScene.drawBackground()`.
**Reason:** `drawBackground()` receives the exposed rect in scene coordinates. With a large scene rect (-50000 to 50000) needed for panning, the exposed rect on initial display was enormous, triggering the "too many lines" safety check and skipping the grid entirely. Even after `fitInView` zoomed in, the grid did not reliably appear. Scene items are a guaranteed rendering path.
**Alternatives considered:** (1) `drawBackground` with invalidation calls — tried, grid still did not render. (2) Drawing grid in `QGraphicsView.drawForeground()` — rejected, would draw on top of members. (3) `ViewportUpdateMode.FullViewportUpdate` — would hurt performance for the entire view just to fix the grid.

### 2026-03-08 — Bent Designer hosted as MDI tab (TechDraw-style)
**Decision:** The Bent Designer opens as a QMdiArea subwindow (maximized tab) in FreeCAD's central area, matching TechDraw's hosting pattern.
**Reason:** The designer needs the full viewport area for the 2D canvas. A dock widget or task panel would be too small. An MDI tab provides full space, coexists with the 3D view (user can switch tabs), and follows established FreeCAD precedent. The user confirmed this approach.
**Alternatives considered:** (1) Sketcher-style Coin3D overlay in the 3D view — rejected, would require Coin3D scene graph work and wouldn't provide a clean 2D canvas. (2) Separate FreeCAD workbench — rejected, too heavyweight for a single panel; MDI tab achieves the same viewport space without workbench switching overhead. (3) Dock widget — rejected, too small.

### 2026-03-08 — Bent Designer background colour from FreeCAD preferences
**Decision:** The 2D canvas background reads FreeCAD's viewport colour from `User parameter:BaseApp/Preferences/View`. Uses `BackgroundColor3` (bottom gradient colour) when gradient is active, or `BackgroundColor` for solid mode. Grid line colours are computed dynamically to contrast with the background.
**Reason:** A hardcoded dark background (45, 45, 50) clashed with FreeCAD's default warm gray gradient and made grid lines invisible regardless of alpha. Matching the 3D viewport colour gives a consistent visual experience and allows grid colours to be computed with known contrast ratios.
**Alternatives considered:** Fixed dark background with high-alpha grid lines — rejected, looked inconsistent with FreeCAD's theme and the grid contrast problem depended on the user's chosen background.

### 2026-03-08 — Placeholder joint fins replace star cones
**Decision:** The unassigned `TimberJoint` placeholder shape was changed from six cones (star) to three perpendicular rectangular fins. Two fins lie in the joint plane (one along each member's datum), and a third fin runs perpendicular along the secondary member's datum. Fins protrude 1.5× the largest timber half-dimension along the joint normal, and span 2× the max cross-section dimension along the datum.
**Reason:** The cone-star was not visible enough — cones were obscured by the timber solids from most viewing angles. Thin rectangular planes ("fins") extend beyond the timber surface and are visible from all angles without obscuring the timber geometry. The third fin follows the secondary datum so it tracks correctly for non-90° intersections.
**Alternatives considered:** (1) Larger cones — still obscured by timbers from many angles. (2) Two fins only — user requested a third for better visibility. (3) Third fin along primary datum — rejected, secondary datum provides better visual tracking at non-orthogonal angles.

### 2026-03-08 — M&T validation: mortise width ≤ 75%, housing depth ≤ 50%
**Decision:** Added tiered validation to mortise_tenon: warning when mortise/housing exceeds 35% of the associated primary dimension, error when mortise width exceeds 75% of the primary's perpendicular extent, error when housing depth exceeds 50% of the primary's through-dimension. `tenon_width` max_value is clamped to enforce the 75% limit.
**Reason:** Without validation, a user could enlarge the mortise until it severed the primary timber entirely. The 35% warning threshold catches cases where the mortise is getting large relative to the primary. The 75%/50% hard limits prevent structurally dangerous cuts. Dot-product projection is used to compute the primary's extent in the mortise direction, handling arbitrary intersection angles correctly.
**Alternatives considered:** (1) Simple percentage of primary width/height — doesn't work for angled intersections where the mortise direction doesn't align with the primary's local axes. (2) No validation, rely on structural checks later — rejected, geometry destruction is more immediate than structural failure and should be caught at the joint level.

### 2026-03-05 — Shoulder-anchored mortise & tenon geometry
**Decision:** The M&T shoulder is anchored at the primary member's approach face. `tenon_length` is measured from the shoulder to the tenon tip. `shoulder_depth` (default 0) recesses the shoulder into the primary, creating a housing pocket. Changing `tenon_length` only moves the tenon tip; the shoulder stays fixed. This unifies through and blind mortise into one joint type — a shorter `tenon_length` naturally creates a blind mortise.
**Reason:** The previous implementation centered the tenon on the datum endpoint (primary centerline). When the user edited `tenon_length`, both the shoulder and tenon tip moved equally — this was incorrect. The shoulder must always sit against the primary's face (or housing bottom). The approach-face-anchored model matches how the joint is physically constructed and makes parameter editing intuitive.
**Alternatives considered:** (1) Keep centered-on-endpoint model with asymmetric scaling — rejected, doesn't match physical reality and confuses the extension calculation. (2) Separate blind mortise joint type — rejected, the geometry is identical except for tenon length; a single parameterized joint is simpler and more flexible.

### 2026-03-04 — Joint-driven member extensions for tenon/dovetail geometry
**Decision:** Joints declare how much extra length they need at the secondary member's endpoint via `secondary_extension()`. The member queries all connected joints and extends its solid by the max requested amount. The joint's shoulder cut then shapes the extension into the correct profile.
**Reason:** The datum endpoint snaps to the primary member's centerline, but through mortise & tenon tenons must protrude past the centerline to reach the far face. A dual-datum system (snap datum + cut datum) was considered but rejected — it would add complexity to every member and confuse the snap system. Joint-driven extensions keep the datum as the single source of truth while letting joints parametrically control the solid length.
**Alternatives considered:** (1) Dual-datum with separate snap and cut datums per member — rejected, too much complexity for a problem that only affects certain joint types. (2) Additive boolean (fuse tenon onto member) — rejected, doesn't interact cleanly with the shoulder cut subtraction pipeline.

### 2026-03-04 — BoundBox comparison replaces _skip_touch alternating flag
**Decision:** The `_skip_touch` boolean flag in `TimberJoint._recompute_joint()` was replaced with `_cuts_changed()`, which compares the bounding box of the current cut tools against the previous recompute. Members are only touched when cuts actually change.
**Reason:** The alternating flag worked for a single joint but failed when multiple joints shared a member — each joint independently touched the member, causing cascading "still touched after recompute" warnings. The BoundBox approach is idempotent: same geometry in → no touch → stable, regardless of how many joints share a member.
**Alternatives considered:** (1) Checking `'Touched' in obj.State` before touching — doesn't help because the issue is touching objects that were already processed in the current recompute cycle, not double-touching. (2) Moving touch() out of execute() into a document observer — too complex and fragile for a cosmetic warning.

### 2026-03-04 — Dovetail tail_height renamed to tail_width
**Decision:** The `tail_height` parameter was renamed to `tail_width` with default changed from `sec_h * 0.5` to `sec_w` (full secondary member width).
**Reason:** The parameter controls the dovetail's extent along `taper_dir`, which runs along the secondary member's width direction — not its height. The old name was misleading and the old default (half the height) was dimensionally wrong. Defaulting to full width eliminates the inset in Through channel mode.
**Alternatives considered:** Keeping `tail_height` name with corrected default — rejected, the name was actively confusing given the geometric reality.

### 2026-03-01 — Datum properties renamed with alphabetical prefixes
**Decision:** `StartPoint` → `A_StartPoint`, `EndPoint` → `B_EndPoint`. Merged Datum 1/2/3 groups into single "Datum" group.
**Reason:** FreeCAD's property panel sorts properties alphabetically within each group. Without prefixes, "End Point" sorted above "Start Point", confusing users. Prefixing with `A_`/`B_` forces correct visual order. Underscores instead of colons/spaces because FreeCAD property names are Python identifiers accessed via dot notation.
**Alternatives considered:** `"A: Start Point"` / `"B: End Point"` — would require `getattr()` everywhere instead of dot notation, rejected. Separate numbered groups (Datum 1, Datum 2, Datum 3) — too many groups for three properties.

### 2026-03-01 — Housed Dovetail renamed to Dovetail
**Decision:** Class renamed `HousedDovetailDefinition` → `DovetailDefinition`, ID `"housed_dovetail"` → `"dovetail"`. File remains `housed_dovetail.py` on disk.
**Reason:** The current joint geometry is a simple dovetail (trapezoidal slot + tenon), not a housed dovetail (which additionally has a rectangular housing pocket around the dovetail). Renaming avoids implying functionality that doesn't exist yet. File not renamed because the loader discovers by class inspection, not filename, and renaming files mid-development creates unnecessary merge friction.
**Alternatives considered:** Adding housing geometry now — deferred, the basic dovetail is the correct starting point and housing can be added as a parameter later.

### 2026-03-01 — Dovetail slot runs perpendicular to approach face, not along primary axis
**Decision:** The dovetail slot in the primary member runs along `taper_dir` (perpendicular to both the primary axis and the approach direction), not along the primary member's length.
**Reason:** A dovetail slides in from the side of the primary member, perpendicular to the approach face. Running the channel along the primary axis would require the secondary to slide lengthwise along the primary, which is not how dovetail joints are assembled.
**Alternatives considered:** Channel along primary axis (original implementation) — incorrect assembly direction, rejected after user testing.

### 2026-02-26 — Collinear endpoint-to-endpoint datums rejected by intersection detector
**Decision:** `compute_joint_cs` returns `None` (no joint formed) when two datum lines are co-linear (angle < 5°), even if their endpoints touch. This means a straight splice — two timbers laid end-to-end along the same axis — does not auto-create a joint.
**Reason:** A co-linear pair produces a degenerate joint coordinate system (zero cross product → no well-defined normal or secondary axis). All joint geometry is defined in the local JCS, so without a valid JCS the joint definition machinery cannot function. The 5° floor (`MIN_ANGLE_DEGREES`) guards against this.
**Alternatives considered:** Special-casing the scarf/splice scenario with a hard-coded "along-axis" JCS. Deferred: `scarf_bladed` is not yet implemented, and the correct UX for a straight splice (select two members + explicit Scarf command) is cleaner than relying on auto-detection for a joint family that needs explicit user intent anyway.

---

## Handoff Notes (2026-03-12)

### What was just completed

**Face-referenced joint toolkit and joint rewrites** (`joints/toolkit.py`, `joints/builtin/mortise_tenon.py`, `joints/builtin/housed_dovetail.py`, `joints/builtin/half_lap.py`):

1. **`joints/toolkit.py`** — New module with `MemberFaceContext` dataclass and face-referenced geometry helpers. `build_face_context()` constructs a raw un-cut member solid, ray-casts to find the approach face, and extracts the face normal, pierce point, and member axes. Helper functions: `face_pocket()` (rectangular mortise), `face_tapered_pocket()` (dovetail socket), `tenon_block()` (rectangular tenon), `tapered_tenon()` (dovetail tail), `shoulder_cut()` (angled shoulder removal), `lap_notch()` (face-identified lap notch), `mortise_axes()` (grain-aligned rectangle orientation), `shoulder_plane()`, `approach_face_distance()`, `extent_along()`. Also consolidates `member_local_cs()` as the single source of truth (previously duplicated in each joint file).

2. **Mortise & Tenon rewrite** — `build_primary_tool()` now uses `face_pocket()` to cut the mortise straight into the approach face. `build_secondary_profile()` uses `shoulder_plane()` to derive the shoulder position from the primary's face, `tenon_block()` to align the tenon with the mortise direction (face normal, not secondary axis), and `shoulder_cut()` to produce an angled shoulder that sits flat against the primary's face. All parameters, validation, fabrication signature, and peg logic unchanged.

3. **Dovetail rewrite** — Same pattern: `face_tapered_pocket()` for the socket, `tapered_tenon()` for the tail, `shoulder_cut()` for the shoulder. Channel mode and half-channel trim logic preserved. Dependent defaults unchanged.

4. **Half-lap rewrite** — Uses `lap_notch()` with a `face_dir` parameter instead of hardcoded top/bottom. Primary notch is on the face closest to the secondary; secondary notch is on the opposite face. Works regardless of member orientation.

5. **Key fixes for angle bugs:**
   - Bug 1 (tenon direction): Tenon now extrudes along `sh_normal` (face normal into primary), matching the mortise direction, instead of along `sec_x`.
   - Bug 2 (shoulder angle): Shoulder plane derived from primary's approach face via `shoulder_plane()`, not perpendicular to secondary axis.
   - Bug 3 (half-lap face): `lap_notch()` finds the correct face dynamically via `face_dir`, not by `+/- pri_z`.

### Known issues and edge cases to watch

- **Needs testing in FreeCAD**: All three joints need testing at 90, 60, and 45 degree intersections to verify the face-referenced geometry produces correct results.
- **`_find_approach_face()` ray-casting**: Uses `face.Surface.parameter()` and `face.isPartOfDomain()` with a `distToShape()` fallback. May need tuning of the 1mm tolerance for edge cases where the ray grazes a face corner.
- **`common()` clipping**: `face_pocket()` and `face_tapered_pocket()` use `shape.common(raw_solid)` to clip pockets to face boundaries. If the OCC boolean fails (rare for box-on-box), the unclipped pocket is returned as fallback.
- **Raw solid includes extensions**: `_build_raw_solid()` in the toolkit queries joint-driven extensions from the document, matching `TimberMember._build_solid()`. This means the raw solid envelope may extend past datum endpoints. This is correct — the approach face must be identified on the actual timber, not the datum-only geometry.
- **Dovetail half-channel offset**: The `face_tapered_pocket()` is centered on `face_point` but half-channel mode needs an offset. The current implementation uses the offset parameter for housing but the tapered pocket itself may need adjustment. Verify with half-channel mode testing.
- **TimberJoint visualization offset**: Previously reported — the TimberJoint's visual shape (tenon + pegs) is offset from the actual cut geometry. Cuts work correctly but the visualization sticks out of the primary. Not yet fixed.
- **Broken joint visualization**: Still works as before (unchanged `TimberJoint.py`).

### Previous session work (2026-03-11)

- Broken joint properties (`IsBroken`, `LastValid*` vectors)
- 3D broken joint visual (octahedra + gap cylinder)
- Bent Designer `JointItem` with three visual states
- Live joint drag update during endpoint drag
- Unknown joint type handling (error + placeholder reset)

### Current phase status

**Phase 2 (Joints)** — complete. Joint toolkit added as architectural foundation.

**Phase 3 (Bent and Frame Composition)** — in progress. Completed:
- Bent container object with add/remove members, drag-drop, MemberID auto-assignment
- BentPanel UI with member list
- Bent Designer 2D editor with joint visualization
- Bent templates
- Bent Designer drag improvements (live preview, datum snap, datum lines)
- Broken joint visualization
- Bent Designer joint display and interaction

Remaining Phase 3 work:
- Frame object with bent instancing and longitudinal members

### Key files to read first

For the next session, the most important files to understand are:
- `CLAUDE.md` — architecture, conventions, decisions log (this file)
- `joints/toolkit.py` — the new face-referenced geometry toolkit
- `joints/builtin/mortise_tenon.py` — M&T rewritten with toolkit
- `joints/builtin/housed_dovetail.py` — dovetail rewritten with toolkit
- `joints/builtin/half_lap.py` — half-lap rewritten with toolkit
- `objects/TimberJoint.py` — recompute pipeline (unchanged, calls joint definitions)
- `objects/TimberMember.py` — `_build_solid()` with extensions, `_collect_joint_cuts()` boolean pipeline
