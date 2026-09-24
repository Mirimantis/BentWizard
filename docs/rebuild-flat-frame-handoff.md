# Rebuild handoff: the flat frame

**Status: built, 2026-09-23.**
- **A** (seats, the frame Std Group): built, with the Assembly object
  dropped altogether.
- **B** (value splits): retired, because FreeCAD 26.3's fine-grained
  recomputes do its job (`spike-fine-grained-recompute-results.md`).
- **C** (handles) and **D** (readers): built (PR #25); each section
  below says which parts were done where.
- **E** (export to Assembly): deferred to Phase 2.

What follows is the brief as written; the numbers in it (118 tests, the
round-4 timings) are from 1.1.3.

**For the coordinator.** This is the build brief for the decisions taken
on 2026-09-19 (PR #18). Everything here is *decided and measured*; none
of it is built. Read this, then the two sources it rests on:

- [spike-flat-frame-results.md](spike-flat-frame-results.md) — rounds 1–4:
  why the two-level assembly failed, seats by expression, dropping the
  assembly, recompute isolation. Every number quoted below comes from it.
- [bentwizard-roadmap.md](bentwizard-roadmap.md) — the *Flat frame* entry
  under Phase 1 is the design of record; `CLAUDE.md` carries the
  conventions the work must not break.

Working harnesses that already do the thing, headless and exact —
**read these before writing the production version**:
`tests/spike/spike_expression_seat.py` (seats, spanning tree),
`tests/spike/spike_recompute_isolation.py` (the five splits),
`tests/spike/spike_flat_frame.py` (round 1, the solver version that
failed — kept as the record of what not to do).

## What changes, in one paragraph

A frame stops being an `Assembly::AssemblyObject` and becomes an ordinary
Std Group holding bent and bay Std Groups. Fixed assembly joints and the
solver are gone. Every timber except the principal one is placed by an
**expression**: the timber joint that first connects it (its *placing
joint*) carries a `Seat_J-…` VarSet computing `host · flip · mate⁻¹`
from the two datums, and the timber's `Placement` reads it. The principal
timber is anchored by binding its `Placement` to a project `FrameOrigin`.
Placing joints form a spanning tree; a joint whose two timbers are both
already placed closes a loop, places nothing, and is verified by the
misfit check instead. Separately, the objects that carry values are
**split along what actually varies**, so one edit no longer recomputes
the whole frame.

## Non-negotiables (do not relitigate)

1. **Tier 1 and Tier 2 hold.** Seats, anchors and splits are all native
   objects and expressions. The model still opens, edits and recomputes without the workbench. No Proxy on anything geometric.
2. **The placement tree is not the load path.** Which joint places which
   timber follows build order. The structural graph (Phase 4) derives
   from *all* timber joints plus roles, bearing faces and supports.
   Nothing structural may read the seat tree.
3. **No central "master variables" object.** Measured: a VarSet others
   read re-creates the cascade the splits remove. The single place to
   edit everything is the front-end panel, which writes to the isolated
   VarSets directly.
4. **A datum is still never read by a Body**, and datums never read each
   other. VarSets read datums; Bodies read VarSets.
5. **Geometry unchanged.** Same cuts, same volumes, same seats as today.
   Every existing geometry assertion must still pass unedited.

## Workstreams

Ordered by dependency. A, B and C can be split across workers if the
contracts in each are agreed first; D and E follow them.

### A. Seats and the frame container (`assemble.py` → `frame.py`)

Retires most of `assemble.py`: container rules, `assimilate_joint`,
`ground`, `new_assembly`, `find_fixed_joints`, `refresh_joint_display`,
`moving_part`, `_placement_for`. Keeps and rehouses: `joint_misfit`,
`is_misfit` (now the loop-closure check), `member_bodies`.

- `frame_group(doc, label)` — find/create the frame Std Group; bent and
  bay groups inside it.
- `seat(varset, anchor_body, mover_body)` — create the `Seat_J-…`
  VarSet, bind `SeatPlacement`, point the mover's `Placement` at it,
  file it under the joint's handle. The expression is in the round-2
  harness; `FLIP` is `placement(vector(0; 0; 0); rotation(vector(0; 1; 0); 180))`.
- `place_on_apply(doc, varset)` — decide which side is unplaced and seat
  it; both placed ⇒ loop closure, no seat, record it as such.
- `anchor(doc, body)` — bind the principal timber to `FrameOrigin`.
- Repair/bulk path replacing **Assemble Timbers**: walk the joints,
  rebuild missing seats, report loop closures and misfits.

**Verification:** port `tests/test_assemble.py` (7 tests). A `Bay` edit
re-spaces exactly (≤1e-9 mm on every joint, loop closers included), the
frame group never moves, nothing is left Touched.

### B. The value splits (`timber.py`, `datums.py`, `apply.py`, `naming.py`)

The five splits, from round 4. **Only those a component reads need to
exist** (three for `Joint_HousedMT`).

| Split | Where | Note |
|---|---|---|
| Project variables | one per variable, or only ever grouped with variables that always change together | the edited object must be the isolated one |
| `TLen_<timber>` | `timber.py` | `LengthZ` leaves `TDim_<timber>`; the section stays |
| `Plc_<side>_<joint>` | `apply.py`/`datums.py` | `= <<datum>>.Placement` |
| `Sec_<side>_<joint>` | same | `WidthU/V` read the **Dims VarSet directly**, not the datum — this is what buys the isolation |
| `Dep_<side>_<joint>` | same | `DepthW` alone; at an end datum it *is* the length. **The split that pays.** |

Consequences to carry:
- `datums.pair()` stops being the thing that binds accessors;
  `datums.host_datum()` must stop inferring the host from the
  `HostWidthU` expression — record the host/mate role explicitly.
- The face→Dims mapping now exists twice (on the datum, and in the `Sec`
  expression). Apply resolves it; a future *re-place* must rewrite it;
  add a linter rule that the binding matches the datum's face row.
- **Templates keep today's single-VarSet form.** Apply expands them,
  reusing the token substitution it already runs over copied components.

**Verification:** `tests/test_apply.py` (12) and `test_datums.py` (13)
pass unedited — the geometry does not change. Add a recompute-budget
test: a `Bay` edit on a 3-bent frame recomputes no post geometry
(assert *zero* pads/Booleans under any post body). Round 4 numbers:
3 bents 2.32 s → 0.65 s; 5 bents 4.60 → 1.46; 10 bents 10.44 → 3.22.

### C. Handles, tree filing, Duplicate (`joint_handle.py`, `duplicate.py`)

> **Done 2026-09-23.** Who did which part:
> - **Workstream A:** filing under the frame (`TimberJoints_<Frame>`),
>   the seat nested under the handle, and Duplicate without the assembly
>   step.
> - **The 26.3 brief, section 2:** the accessor VarSet under the handle.
> - **C's own branch:**
>   - `release_contents`: deleting a handle (`onDelete`,
>     `remove_handle`) moves the parameter VarSet, the accessor VarSet
>     and the seat out beside it. Before, only the parameter VarSet was
>     moved; the other two fell to the document root.
>   - `ensure_handle` re-files the seat, and gives a re-created handle
>     its parameter VarSet back.
>   - Deleting a handle stays allowed (Adam).
>   - Verified by `test_joint_handle.test_deleting_a_handle_is_harmless_and_seat_timbers_restores_it`
>     and a scripted GUI Delete: the timbers stay seated.

- Handles file under the **frame group**, not `TimberJoints_<Assembly>`.
- A handle now holds: the parameter VarSet, the seat VarSet, and the
  accessor VarSets. Its `onDelete` must move **all** of them out of the
  way, as it does the parameter VarSet today — deleting a handle must
  stay harmless to geometry (this is why the seat is *nested under* the
  handle rather than a property of it).
- `duplicate.py` loses its assembly step: copies get seats, and the
  offset goes on the copies (already true since `60b855d`).

**Verification:** `test_joint_handle.py` (5), `test_duplicate.py` (4).
Delete a handle, recompute, confirm every timber still placed.

### D. Readers of the old shape (`linter.py`, `template*.py`, `commands.py`)

> **Done 2026-09-23.** Who did which part:
> - **The 26.3 brief, section 2:** the linter's component rules and
>   `TemplateSpec` resolving through the accessor VarSet
>   (`Model.accessors_of`, `accessor_datum`).
> - **Workstream A:** Seat Timbers as the repair path, and Apply's
>   checkbox as "Seat the entering timber".
> - **Not needed:** the `Sec_` binding rule. It belonged to B, which is
>   retired. Seats get no lint rule either: they never appear in a
>   template, which is what the linter guards.
> - **D's own branch:**
>   - Audit Timbers reports placement, via `frame.placement_report`.
>     Each timber is anchored, seated, provisional (listed, never
>     counted — Adam) or loose.
>   - Each timber joint places, closes a loop, or is unseated, with its
>     misfit. A misfit counts as a problem only where the two sides are
>     meant to meet. More than one anchored timber is a problem.
>   - `undo_repair` already re-armed seats (it re-arms every restored
>     object), but `test_undo_repair` could not show it on 26.3's
>     default. It now forces fine-grained recomputes off and adds the
>     seated case and a tripwire for finding #15.
>   - The library rebuilds clean (the acceptance test).

- Linter: `rule_component_reference_scope` and
  `rule_component_placement_direct` learn the new allowed set (own side's
  `Plc`, parameters, other side's `Sec`/`Dep`). `Model.accessor_datum`
  follows the accessors. New rule for the `Sec` binding (above).
- `TemplateSpec` finds roles through the accessors today — same change.
- `commands.py`: **Assemble Timbers** becomes the repair path (A);
  the Apply dialog's "Assemble now" checkbox becomes seat-or-not, or
  goes away; Audit Timbers reports loop closures and misfits.
- `undo_repair.py`: more expression bindings to re-arm after undo.

**Verification:** `test_linter.py` (22), `test_template*.py` (21),
`test_undo_repair.py` (2). The shipped library rebuilds clean
(`scripts/build_library.py`) — it is the acceptance test for D.

### E. Export to Assembly (Phase 2, do last or defer)

Convert a finished frame into a native Assembly with a Fixed joint per
timber joint, grounded at the principal timber, seats as the starting
pose. One-way: a deliverable, not a second source of truth. Round 1's
harness is the reference for what the Assembly machinery needs — and for
its limits (closed loops break the solver from 4 bents; a moved
sub-assembly mis-draws its markers).

## Coordination notes

- **Do not split A or B across workers mid-contract.** Joint geometry and
  placement logic stays in one session (`CLAUDE.md`, *Subagents*): the
  seat expression and the accessor rewiring are exactly that work. Split
  *between* workstreams, not inside them.
- **Agree the names before anyone writes code**: `Seat_`, `Plc_`, `Sec_`,
  `Dep_`, `TLen_` prefixes, the `FrameOrigin` property, the host/mate
  record. They appear in A, B, C and D simultaneously and are cheap to
  agree and expensive to reconcile.
- **The suite is the contract between workers.** 118 tests pass today;
  run the whole suite with the bundled python before handing work on, and
  say which tests were edited and why — an edited geometry assertion is a
  design change, not a fix.
- **Headless is a filter, not an oracle.** Recompute ordering, tree
  rendering and marker behaviour are GUI-only. Every workstream ends with
  a scripted GUI probe (the pattern is in `CLAUDE.md`, Environment) and
  the whole rebuild ends with Adam's GUI round before anything is
  committed to `main`.
- **Nothing lands untested**: build → headless suite → Adam's GUI test →
  commit. That rule is why the spikes exist.

## Open questions for Adam (answer before or during the build)

> **All three answered:**
> 1. **Project-variable granularity: free.** On 26.3, sharing a VarSet
>    or a Spreadsheet costs nothing (findings 13–16,
>    `spike-fine-grained-recompute-results.md`), so variables can be
>    grouped however a framer finds natural.
> 2. **Migration: no converter.** Pre-rebuild documents are unsupported
>    (`workstream-a-handoff.md`).
> 3. **Panel timing: the panel waits.** The gap is accepted, and the
>    panel is the next priority.

1. **Project-variable granularity.** One VarSet per variable is maximal
   isolation and maximal clutter. Grouping only variables that always
   change together is the compromise — which grouping does a framer
   expect to see in the tree? **Measured 2026-09-20 (finding 15): the
   split is not optional.** Skipping it and keeping L3–L5 gives 1.3x
   (4.75 → 3.71 s) against 3.2x for both halves, because a shared
   `ProjectVars` cascades from upstream of everything the plumbing
   splits protect. What remains open is only *how far* to group:
   variables read by exactly the same objects may share one, anything
   else must not.
2. **Migration.** Existing documents (`scratch/*.FCStd`, and anything
   Adam has saved) carry Fixed joints, a frame assembly and un-split
   VarSets. Build a one-shot converter, or declare pre-rebuild files
   unsupported? The spikes suggest a converter is mostly the same
   rewiring the isolation harness already does.
3. **Panel timing.** The splits make "where does this number live?"
   harder until the panel's expression tracing exists. Build the tracing
   alongside the splits, or accept a gap?
