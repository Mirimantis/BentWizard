# Spike: parametric bent spacing and the frame assembly

Harness: `tests/spike/spike_flat_frame.py`, run with the bundled python.
Session of 2026-09-18/19, FreeCAD 1.1.3, following Adam's GUI round on
Duplicate Timbers and the first tie between two bents.

```bash
<FreeCAD>/bin/python.exe tests/spike/spike_flat_frame.py tree 3
```

**Status: open.** No production code follows from this yet; the design
decision is pending (see *Options still open*).

## The problem

Parametric bent spacing is a core feature: edit the tie length (or a
`Bay` variable it reads) and the bents re-space. In the two-level
design (bents are sub-assemblies inside a frame assembly, PR #4), the
solver re-spaces by moving the bent **assembly's own Placement**. Two
things break:

1. **FreeCAD's Fixed-joint markers draw at twice the bent's shift.**
   `SoSwitchMarker.set_marker_placement` (Mod/Assembly) computes the
   joint's *global* placement, then draws it under the joint's container,
   whose Coin transform applies the container's placement again. Measured
   in `scratch/HBent02.FCStd`: `Bent.002` at (812.8, 1828.8) inside
   `Frame.001`; J-HousedMT-002's marker drawn at (4673.6, 3759.2) instead
   of (3860.8, 1930.4). This is FreeCAD's code, not ours; the same class
   of bug as upstream [#17398](https://github.com/FreeCAD/FreeCAD/issues/17398)
   (joints mis-placed in a moved assembly) and
   [#31083](https://github.com/FreeCAD/FreeCAD/issues/31083) (drag goes
   the wrong way under a non-identity assembly Placement).
2. Our own joint handles had the identical mistake — fixed (see *Fixes
   landed*). They now draw correctly under any moved container.

A flexible sub-assembly would sidestep this, but FreeCAD 1.1 offers
`Rigid = False` only on `Assembly::AssemblyLink` (a linked, inserted
sub-assembly), not on a directly nested `AssemblyObject`.

## Options considered

1. **Hide FreeCAD's Fixed-joint markers**; our handles are the visible
   markers. Cheap, view-only, but the moved-assembly bugs in FreeCAD's
   other tools (drag, joint creation) remain.
2. **Monkeypatch FreeCAD's marker code.** Fixes every marker, but couples
   BentWizard to another workbench's internals. Better as an upstream PR.
3. **Flat frame**: one Frame assembly, every timber a direct member,
   bents as Std Groups. No assembly ever moves. *Tested below.*
4. **Bent spacing by expression**: bent placement bound to `Bay` × index;
   spacing is a plain recompute, not a solve. Rule 3 ("placement is an
   expression") argues for it. On the two-level design the assembly
   still moves (needs 1 as well); on the flat frame it does not.

## Flat-frame results

Frame per bent: two 8×8 posts (10 ft), a 6×8 beam (`Span`) at
`PlateLine`; per bay two 6×8 ties (`Bay`) at `GirtLine`; all joints
`Joint_HousedMT`, applied with `assimilate_joint` into the one Frame
assembly. Edit: `Bay` 10 ft → 12 ft, recompute, `frame.solve()`.

| Bents | Timbers / joints | Loops | Build | Bay edit | Result |
|---|---|---|---|---|---|
| 2 | 8 / 8 | yes | 4 s | 1.1 s | ✅ bents at 0, 152 in; misfit 1e-12 mm |
| 3 | 13 / 14 | yes | ~8 s | ~2 s | ✅ |
| 4 | 18 / 20 | yes | — | — | ❌ `solve()` = 0 but bays 151.918 in (should be 152) |
| 5 | 23 / 26 | yes | 24 s | 4.6 s | ❌ `solve()` = −1, nothing moved; misfit 610 mm |
| 4, 5 | 18–23 / 20–26 | **no** | ~25 s | ~5 s | ✅ exactly 152 in; misfit ~1e-12 mm on every joint |
| 10 | 48 / 56 | **no** | **367 s** | 13 s | ❌ solve failed, nothing moved; misfit 610 mm |

(20 bents was started and stopped: too slow to be informative.)

### Findings

1. **Flat solves the marker problem.** The only assembly stays at
   identity; everything FreeCAD draws is in the right place.
2. **Closed loops of Fixed joints break the solver.** Every bay is a loop
   (post → tie → post → beam → post → tie → post). With a few loops MbD
   copes; at 4 it returns a wrong answer while reporting success, at 5 it
   fails. The two-level design has the same exposure as soon as a bay has
   two ties (HBent02 had one). Fix: build a **spanning tree** — a joint
   whose two timbers are already connected gets its timber joint (cuts,
   handle) but **no Fixed assembly joint**; the audit misfit check verifies
   it still closes. Measured: loop-closing joints still meet to 1e-12 mm.
3. **Solver-driven spacing does not scale, even loop-free.** At 10 bents a
   24 in `Bay` change moves the 10th bent 18 ft from where the solver
   starts; it gives up and moves nothing. Parametric spacing cannot rest
   on the solver alone.
4. **Build cost grows super-linearly**: ~0.5 s per joint at 8 timbers,
   ~6.5 s per joint at 48 (each `assimilate_joint` recomputes and solves
   the whole frame). A separate problem, but real for full buildings.

## Options still open

- **Expression-driven spacing on a flat frame** (option 4 + 3): each
  bent's timbers placed from `Bay` × index, so re-spacing is a plain
  recompute; the solver only keeps timbers within a bent seated, or is
  not needed for spacing at all. Open question: how ties' Fixed joints
  coexist with expression-placed bents (likely: ties are loop-closing,
  so no Fixed joint — finding 2 already requires that).
- **Pre-seat before solve**: after a parameter edit, walk the spanning
  tree out from the ground and re-seat each timber exactly (as
  `assimilate_joint` already does for a new joint), leaving the solver
  a verification. Keeps Assembly joints authoritative, but BentWizard
  does most of the solver's work.

## Artifact for GUI inspection

- `scratch/FlatFrame01.FCStd` (gitignored, machine-local) — loop-free
  flat frame, 3 bents, built in a scripted GUI session so every Tip is
  visible. `ProjectVars` (`Bay`, `Span`, `GirtLine`, `PlateLine`) drives
  it; `Bay` edits solved correctly at this size.

## Fixes landed alongside (branch `claude/per-machine-freecad-path`)

- Joint handle markers draw in their container's frame
  (`joint_handle.marker_position`).
- Duplicate Timbers offsets the copied timbers, never the new bent
  assembly's Placement.
- Apply dialog keeps a chosen face when the role's timber changes.
  **Still open:** switching the template rebuilds every row and resets
  all timber and face choices (Adam hit this switching Butt → HousedMT).
