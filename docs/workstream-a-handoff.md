# Workstream A handoff: seats and the frame container

**For the local agent.** Workstream A of the flat-frame rebuild
([rebuild-flat-frame-handoff.md](rebuild-flat-frame-handoff.md)) is
**written but never executed**. It was built in a Cowork session that
reaches this repo through a Linux VM, where the bundled FreeCAD
`python.exe` — a Windows binary — cannot run. Nothing here has touched
FreeCAD. pyflakes is clean on every changed file; that is the only
verification it has had.

Branch: **`claude/flat-frame-seats`**, cut from `claude/gui-round-3`
(not `main`, which is 15 commits behind and carries neither the build
brief nor the round-3 fixes `joint_handle` and `duplicate` depend on).
Nothing is committed — the working tree holds the whole change.

## Clear these first

```
del .git\index.lock
git rm --cached freecad\bentwizard\assemble.py tests\test_assemble.py
del freecad\bentwizard\assemble.py tests\test_assemble.py
..\FreeCAD_1.1.3-Windows-x86_64-py311\bin\python.exe -m unittest discover -s tests
```

The lock is stale: the Cowork session's shell cannot delete files, so
git's own cleanup unlink fails and leaves it behind after any command
that writes the index. `assemble.py` is fully unreferenced now and
`test_assemble.py` has been stubbed to a single skipped test so a
lingering copy cannot fail the run; both are staged for removal but
still on disk for the same reason.

## What changed

New `freecad/bentwizard/frame.py` (581 lines), replacing `assemble.py`:

- `frame_group` / `subgroup` / `containing_frame` / `member_bodies` /
  `is_frame_group` — the Std Group container. A frame is structurally "a
  root Std Group holding timbers"; no label matching.
- `seat(varset, anchor_body, mover_body)` — creates or rewrites the
  joint's `Seat_J-…` VarSet, binds `SeatPlacement` to
  `anchor.Placement * near.Placement * FLIP * minvert(far.Placement)`
  (the round-2 harness's expression, unchanged), points the mover's
  `Placement` at it, files it under the joint's handle.
- `unseat` — drops a seat and freezes the timber it placed where it
  stands. `reverse_seat` / `re_root` — turn "J places X from Y" into "J
  places Y from X" along a path, so a component can be re-rooted.
- `anchor` / `anchored_timber` / `project_varset` — the `FrameOrigin`
  root.
- `place_on_apply` — the Apply path. Returns a `Seating`
  (seat, mover, anchored, closing, merged).
- `rebuild_seats` — the repair/bulk path. Returns a `Rebuild`
  (frame, seated, closures, misfits, skipped, adopted).
- `joint_misfit` / `is_misfit` / `member_bodies` — rehoused.

Placement state is never tracked, only read: `seat_driving`,
`is_anchored`, `places`, `anchor_timber`, `root_of` and `seat_path` all
walk live `ExpressionEngine` entries, so a document reloaded without the
workbench is still fully legible to it.

Rewired: `apply.py` (`remove_joint` unseats instead of deleting a Fixed
joint), `joint_handle.py` (`joint_container` is the common frame group;
`handle_group` no longer calls `newObject` on a container), `duplicate.py`
(no assembly step; `assembly_label` is gone, `seat=True` added),
`commands.py` (Apply's checkbox is seat-or-not; **Assemble Timbers** is
now **Seat Timbers** over `rebuild_seats`, command ID unchanged;
Duplicate's dialog offers a bent Std Group, not an assembly),
`view_joint_handle.py` (one docstring reference).

Tests: new `tests/test_frame.py`, 11 tests — the 7 ported from
`test_assemble.py` plus the seat nesting under its handle, the loop
closer, repair rebuilding only what is missing, and
`test_bay_edit_respaces_exactly` (a two-bent frame with a bay and one
loop closer; `Bay` 10 → 12 → 8 ft; every joint inside 1e-9 mm, the
anchored post unmoved, nothing left Touched). `test_apply.py`,
`test_duplicate.py` and `test_joint_handle.py` had their `assemble`
references swapped; `test_duplicate`'s assembly test became
`test_copies_seat_in_an_offset_bent_group`.

## Decisions taken in this session

**One anchored timber per document, and the brief's loop-closure rule is
incomplete.** The build brief says "both placed ⇒ loop closure, place
nothing". That holds only when joints are applied outward from the
principal, which is how the spike harness built its frames and is not
how anyone works. `test_second_bent_joins_under_a_frame` builds two π
bents *separately* and then ties them: under the brief as written, both
bents anchor to the same `FrameOrigin` (landing on top of each other)
and the tie is then declared a loop closure, so bent 2 never moves and
the misfit check reports metres of error. Duplicate-plus-tie is the same
shape. Adam chose **re-rooting** (2026-09-20): a joint spanning two
placement components reverses the seats between the joined timber and
its own root, then seats it from the other side, and the component
swings in rigidly.

Implementing it showed the cheaper half does most of the work:
`FrameOrigin` is claimed by **exactly one** timber, and every other
placement root is *provisional* — a literal placement, no expression. A
second component's root therefore reads as unplaced, so the ordinary
"one side is loose, seat it" branch handles the common case (tying a
bent at its own principal, tying a duplicate at its copy of the
principal) with no reversal at all. `re_root` is reserved for a joint
landing on a timber that is **not** its component's root, and the merge
branch keeps whichever component holds the frame's anchor fixed.

**`FrameOrigin` lives on a `ProjectVars` VarSet**, found or created, per
the naming Adam signed off. Workstream B may re-home it once project-
variable grouping is settled; it is one expression to re-point.

**Remove Timber Joint freezes.** Dropping a placing joint leaves its
timber exactly where it stood, loose, for the repair path to re-seat.

**A took two bites of C's work**, the minimum to keep the tree coherent:
`joint_container` resolves to the frame group, and `place_on_apply`
collects loose timbers into the frame and re-files the handle. What a
handle *holds* and what its `onDelete` must move out of the way —
including the seat — is still C.

**"Seat Timbers"** replaced "Assemble Timbers" in the menu text and
dialog (ID `BentWizard_AssembleTimbers` unchanged). Terminology is
Adam's call; renaming is two strings.

## Where it will break first

Ranked by my estimate, for whoever runs the suite:

1. **`test_output_lints_clean`.** The linter has never seen a seat: a
   VarSet linking two datums and a timber Body whose `Placement` reads a
   VarSet property. `rule_component_placement_direct` and
   `rule_component_reference_scope` are written about component bodies,
   so they *should* pass it, but this is the assertion most likely to
   trip and it is the one that tells you what D owes.
2. **Handles left Touched.** `test_bay_edit_respaces_exactly` asserts
   nothing is Touched after a plain recompute. The spike saw a clean
   document, but it had no handles in it. If handles settle only on the
   next recompute, loosen the assertion to exclude them — do not loosen
   it for geometry.
3. **Handle re-filing.** `place_on_apply` calls `ensure_handle` after
   moving timbers into the frame, so the handle's group label changes
   from `TimberJoints` to `TimberJoints_<Frame>`; `handle_group` creates
   the new group and `prune_root_group` should remove the emptied root
   one. Untested end to end.
4. **`re_root` ordering.** `seat_path` is computed before any reversal,
   then `_freeze(body)`, then each seat is reversed root-ward, each
   rebinding the timber above it; the caller must seat `body` straight
   afterwards (`place_on_apply` does). If a reversal leaves a timber
   reading a seat that now computes someone else's pose, this is why.
   `test_second_bent_ties_into_the_frame` exercises the *simple* path,
   not this one — a test that ties bent 2 at `post4` rather than `post3`
   would hit `re_root` properly and is worth adding.
5. **`undo_repair`.** A seat is one more expression binding to re-arm
   after undo. Listed under D in the build brief; undoing an Apply now
   leaves a seat behind, so it may want doing sooner.

Headless is a filter, not an oracle: recompute ordering, tree rendering
and marker behaviour are GUI-only, so A still owes a scripted GUI probe
(`CLAUDE.md`, Environment) before it is handed on, and the rebuild as a
whole still owes Adam's GUI round before anything reaches `main`.

## The rest of the plan, as agreed 2026-09-19/20

> **Paused 2026-09-20 — read
> [freecad-26-3-compatibility-brief.md](freecad-26-3-compatibility-brief.md)
> first.** A is built and its PR is open. B is parked: FreeCAD 26.3's
> fine-grained recomputes cover expression edges and are on by default,
> which probably retires the splits entirely. **C is not to start**,
> Adam's call — 26.3 also breaks the PartDesign Boolean's operand frame,
> so the component mechanism itself may change shape, and there is no
> point building C on ground that is about to move. The plan below
> resumes once the 26.3 session reports.

- **Order A → B → C → D**, one branch and one PR each, each verified by
  a scripted GUI probe; Adam's interactive GUI round happens once, before
  D merges. **E (export to Assembly) is out of scope** for the rebuild.
- **No migration converter** — everything predating the rebuild is
  scratch and spike files, so pre-rebuild documents are unsupported.
- **The panel's expression tracing waits.** The splits make "where does
  this number live?" harder until it exists; that gap is accepted, and
  the panel is the priority once the rebuild lands.
- **Project-variable grouping is B's opening discussion, not a rule set
  now.** Adam wants the tree organised — grouped thematically, not one
  VarSet per variable — but spike finding 15 measures that any two
  variables that do not always change together must not share an object
  (leaving `Bay` on a shared `ProjectVars` capped the whole isolation
  effort at 1.3x against 3.2x). The reconciliation to open B with:
  single-variable VarSets **nested in thematically named Std Groups**,
  which are pure tree containers and carry no dependency edge — the same
  reason bents and bays can be groups inside the frame. Finding 16 rules
  out a Spreadsheet as the home for variables.
