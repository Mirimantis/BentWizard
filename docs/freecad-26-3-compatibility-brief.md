# Brief: make BentWizard work on FreeCAD 26.3

**For a fresh session.** Adam's decision, 2026-09-20: BentWizard moves
to 26.3 and takes the fine-grained recomputes. Everything else is
paused until this session reports — **workstream C is explicitly not to
start**, because another 26.3 change could move the ground again.

Read first:
- [spike-fine-grained-recompute-results.md](spike-fine-grained-recompute-results.md)
  — what is already measured on 26.3, and the two findings below.
- [upstream-issue-boolean-operand-frame.md](upstream-issue-boolean-operand-frame.md)
  — the repro for the blocking defect, for Adam to file.
- [rebuild-flat-frame-handoff.md](rebuild-flat-frame-handoff.md) and
  [workstream-a-handoff.md](workstream-a-handoff.md) — the rebuild this
  interrupts. A is built and merged-pending; B is parked; C is paused.

## What is already known

1. **Fine-grained recomputes cover expression edges**, which is what
   BentWizard is built from, and they are **on by default** in the
   weekly. Editing one property of a VarSet recomputes only the readers
   of that property. This is why Adam wants the move: it retires
   workstream B's five levels of hand-splitting and lets layout
   variables be grouped the way a framer expects.
2. **A `PartDesign::Boolean` no longer resolves its operand in the
   target Body's local frame.** A moved Body no longer intersects its
   own operand: `Fuse` gives two solids, `Cut` silently removes nothing.
   This breaks the component mechanism — every joint is a component Body
   booleaned into a timber, bound to its datum's *local* placement
   precisely because of the old contract — and it is why the suite on
   26.3 is 2 failures + 13 errors of 123. Not caused by fine-grained
   recomputes (identical with the preference off).

The remaining non-Boolean failures are in `measure`: `order_length`
short by exactly a tenon, and a `None` where a timber is no longer one
solid. Consistent with the same root cause, but confirm rather than
assume.

## The work

### 1. Settle the Boolean contract (blocks everything else)

Adam files the upstream issue. Meanwhile, assume it is intentional and
design for it, because a release is weeks away and waiting is not a
plan. The obvious repair — bind a component to its datum's **global**
placement — is not a one-line change: the joint VarSet cannot read a
timber's `Placement` without the cycle round 2 found (a timber's own
components already read that VarSet). Options worth prototyping in a
scratch harness, not production:

- A per-side placement object that reads the timber *and* the datum, the
  way `Seat_J-…` already does (a seat VarSet reads the anchor timber's
  `Placement` and both datums without a cycle — **this is the existing
  proof that the shape works**).
- Leaving components in local space and giving the Boolean a target
  whose placement is identity — i.e. moving the seat off the timber Body
  and onto a container. Probably worse: it reintroduces a moved
  container, which is what the flat frame exists to avoid.

Whatever is chosen has to keep: no Body reads a datum directly (the
scope rule), datums never read each other, and the mirror/parity rule.

### 2. Sweep for the rest of 26.3's changes

The point of this session is to find the *other* surprises before more
is built on sand. At minimum:

- **The suite**, triaged failure by failure, cause by cause — not just
  a count.
- **The GUI**: does the workbench load at all (`InitGui`, toolbar,
  commands, the Coin3D markers in `view_joint_handle` and
  `view_face_marks`)? Qt and Coin versions move between releases. Use
  the scripted GUI probe pattern in `CLAUDE.md`; the junction for 26.3
  is a *different* config folder, `%APPDATA%\FreeCAD\v26-3\Mod`, so
  `scripts\dev-install.ps1 -FreeCadVersion v26-3 main` must be run **by
  Adam from a shell outside the Claude desktop app** (MSIX redirects
  `%APPDATA%` writes; an in-app `Test-Path` is not proof).
- **Expression engine**: `minvert`, placement multiplication and the
  `<<Label>>` forms the seats depend on.
- **Datums**: `Part::LocalCoordinateSystem` placement and the
  child-axis scope behaviour recorded in `CLAUDE.md`.
- **VarSets and the Spreadsheet**: re-run the finding-16 probe — per-cell
  tracking may now exist, which would change the "spreadsheets are for
  reading" guidance.
- **Assembly**: only needed for the Phase 2 export now, but confirm
  whether the marker bug that started all of this still exists.

### 3. Re-run the parked measurements, once the frame builds again

- `tests/spike/spike_recompute_isolation.py 5` and `10`, with the
  preference **off** and **on**. The decisive cell is L1-on against
  L5-off (215 objects / 1.46 s at five bents on the 7010). If the engine
  gets the unsplit document to roughly L5, workstream B is dead.
- The shared-vs-apart overlap run (`BayWidth` + `GirtHeight` on one
  VarSet): it cost 75% on 1.1.3. If that goes to zero, Adam's thematic
  grouping is free and B collapses to naming and tree work.

## Decision rules

- **26.3 becomes the minimum FreeCAD** only when the suite is green on
  it *and* the GUI round passes. Until then 1.1.3 remains the target and
  `main` must keep working there.
- **Supporting both** is acceptable only if it costs a binding choice,
  not two mechanisms. If the Boolean contract differs by version, say so
  plainly and pick one — a workbench that builds geometry two ways is
  the failure mode this project has twice rebuilt to escape.
- **Nothing lands untested**: headless suite, scripted GUI probe, then
  Adam's GUI round, as always.

## Practical

- Build: `C:\Users\Admin\projects\FreeCAD_weekly-2026.09.16-Windows-x86_64-experimental`,
  26.3.0, git `a4ce44d33b`, `bin\python.exe` as usual. Tag it `26.3`
  beside the `7010` / `i9` machine tags in any timing.
- Branch from `claude/flat-frame-seats` (workstream A: the seats and the
  frame container this all now rests on), not from `main`.
- The harnesses run on A's branch since `fd284cc`; the older
  `spike_flat_frame.py` is historical and exits with an explanation.
