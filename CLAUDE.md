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
│       ├── through_mortise_tenon.py
│       ├── blind_mortise_tenon.py
│       ├── half_lap.py
│       ├── housed_dovetail.py
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
| JointType | String | ID string from joint registry (e.g. "through_mortise_tenon") |
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
    NAME = ""           # "Through Mortise and Tenon"
    ID = ""             # "through_mortise_tenon" — stable, unique
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

### Phase 1 (current) — Skeleton and TimberMember
- Register workbench with FreeCAD
- Init.py, InitGui.py, workbench class
- TimberMember FeatureObject: datum line, section, solid geometry, properties panel
- Basic 3D grid and datum endpoint snapping
- Workbench installable and member placeable

### Phase 2 — Joints
- Datum intersection detection
- JointCoordinateSystem
- Joint definition base class and loader
- Through mortise & tenon, half lap, housed dovetail
- Boolean cuts parametrically updating

### Phase 3 — Bent and Frame Composition
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

### 2026-02-26 — Collinear endpoint-to-endpoint datums rejected by intersection detector
**Decision:** `compute_joint_cs` returns `None` (no joint formed) when two datum lines are co-linear (angle < 5°), even if their endpoints touch. This means a straight splice — two timbers laid end-to-end along the same axis — does not auto-create a joint.
**Reason:** A co-linear pair produces a degenerate joint coordinate system (zero cross product → no well-defined normal or secondary axis). All joint geometry is defined in the local JCS, so without a valid JCS the joint definition machinery cannot function. The 5° floor (`MIN_ANGLE_DEGREES`) guards against this.
**Alternatives considered:** Special-casing the scarf/splice scenario with a hard-coded "along-axis" JCS. Deferred: `scarf_bladed` is not yet implemented, and the correct UX for a straight splice (select two members + explicit Scarf command) is cleaner than relying on auto-detection for a joint family that needs explicit user intent anyway.
