# Spike: parametric bent spacing and the frame assembly

Harnesses: `tests/spike/spike_flat_frame.py` (round 1, solver) and
`tests/spike/spike_expression_seat.py` (round 2, expressions), run with
the bundled python.
Session of 2026-09-18/19, FreeCAD 1.1.3, following Adam's GUI round on
Duplicate Timbers and the first tie between two bents.

```bash
<FreeCAD>/bin/python.exe tests/spike/spike_flat_frame.py tree 3
```

**Status: flat frame adopted (Adam, 2026-09-19)** — one assembly per
frame, bents and bays as Std Groups; see the roadmap's *Flat frame*
entry. Not built yet. Bent spacing is resolved by **seating timbers by
expression** instead of by the solver (round 2, below): exact and
warning-free to 20 bents.

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

## Round 2: the seat as an expression (resolves spacing)

Harness: `tests/spike/spike_expression_seat.py N`. Considered and set
aside: *pre-seat before solve* (BentWizard would do the solver's work
and the Assembly joints would only check it) and literal `Bay` × index
spacing (it would hard-code geometry, e.g. spacing = tie length + post
width). Tested instead: the **seat itself as an expression** — the same
`host · flip · mate⁻¹` that `datums.seat_delta` computes, written where
FreeCAD recomputes it:

- Every timber but the grounded first post is placed by the timber
  joint that first connects it (a **placing joint**). Its `Placement`
  reads `SeatPlacement` on a per-joint `Seat_J-…` VarSet:
  `<<Anchor>>.Placement * <<near datum>>.Placement *
  placement(vector(0; 0; 0); rotation(vector(0; 1; 0); 180)) *
  minvert(<<far datum>>.Placement)`.
- Placing joints form a spanning tree. A joint whose two timbers are
  already placed (the second tie of a bay) places nothing and is only
  checked (Audit Timbers' misfit).
- No Fixed assembly joints and no solve; the one Frame assembly holds
  the timbers and a grounded post.

| Bents | Timbers / joints | Build | `Bay` edit (plain recompute) | Worst misfit, all joints |
|---|---|---|---|---|
| 2 | 8 / 8 | ~4 s | 1.2 s | 1e-12 mm |
| 3 | 13 / 14 | ~8 s | 2.4 s | 4e-12 mm |
| 5 | 23 / 26 | 16 s | 5.0 s | 6e-12 mm |
| 10 | 48 / 56 | 42 s | 10 s | 8e-12 mm |
| 20 | 98 / 116 | 153 s | 24 s | 8e-12 mm |

Bents land at exactly `Bay` + 8 in at every size; loop-closing joints
close to ~1e-11 mm without being enforced; nothing is left
Touched/Invalid. A scripted GUI session (3 bents, `Bay` 12 → 8 → 10 ft)
logged **zero** warnings or errors. Compare the solver: failed at 5
bents loop-free, and at 10 bents moved nothing after a 367 s build.

### Findings

5. **The seat cannot live on the joint VarSet.** FreeCAD's dependency
   graph is per object; each timber's component bodies already read the
   joint VarSet (`HostPlacement`/`MatePlacement`), so the joint VarSet
   reading a timber's `Placement` is `cyclic reference`. A separate seat
   VarSet, read only by the placed timber, is clean. It reads the datums
   directly (a VarSet may link a datum; a Body may not — the scope rule).
6. **Expression names must avoid unit symbols.** `A * B` fails to parse
   (`A` is the ampere); real property and label names are fine.
7. **Cost is linear, ~0.25 s per timber per edit** — predictable, but
   24 s at 98 timbers is slow for one edit. Posts and beams only *move*
   on a `Bay` edit; whether a Placement change also recomputes each
   timber's Booleans is worth measuring before building.

### Decisions (Adam, 2026-09-19)

- **The seat VarSet nests under the timber joint's handle**, beside the
  parameter VarSet (Adam tested this by hand in `ExprFrame02`). Not a
  property *of* the handle, though that also works (tested, no cycle):
  the handle's contract is that deleting it is harmless to geometry, and
  a nested VarSet survives a deleted handle where a handle property
  would not. The handle's `onDelete` must move the seat VarSet out of
  the way too, as it does the parameter VarSet.
- **The placement tree is not the load path.** Which joint places which
  timber follows build order (Bent 2's first post is placed *from the
  tie*), and load paths are redundant graphs, not trees. The structural
  graph (roadmap Phase 4) is derived from **all** timber joints —
  loop-closing ones included — plus timber roles, bearing faces and
  ground supports, all of which the timber joints and timbers already
  carry. Bent and bay Std Groups give the racking checks their per-bent
  membership. A later refinement: Apply could prefer the *supporting*
  side as the anchor (a beam placed from its post, a post from its sill)
  so the placement tree mostly follows gravity and edits feel natural —
  a convenience only; nothing structural may depend on it.

## Round 3: where a Bay edit's time goes (profiled, 5 bents / 1676 objects)

Observer timestamps per recomputed object (`slotRecomputedObject`),
scratchpad harness. A `Bay` edit recomputed **514 objects in 4.5 s** —
117 sketches, 117 pads, 52 Booleans, 75 bodies. Only ~0.7 s of that is
the ties, whose length really changed.

| Change | Objects recomputed | Time |
|---|---|---|
| `Bay` on the shared `ProjectVars` | 514 | 4.5 s |
| `Bay` alone on its own VarSet | 337 | 3.1 s |
| `Span` on the shared `ProjectVars` | 458 | 4.4 s |
| Moving the whole frame (grounded timber 1 mm) | 46 (bodies, seats, handles) | **0.08 s** |
| Nothing changed | 0 | 0.00 s |
| `Bay`, every Boolean `Refine = False` | 514 | 3.9 s |

### Findings

8. **Seats are not the cost.** Moving every timber in the frame
   recomputes no sketch, pad or Boolean — 0.08 s. Expression seating is
   cheap; the cost is the cascade from the *size* change.
9. **FreeCAD's dependency graph is per object, not per value** — the
   same granularity that forces the seat onto its own VarSet (finding
   5) makes one edit recompute everything downstream of the whole
   object. Three levels of it here: (a) `ProjectVars` — changing `Bay`
   recomputes every datum reading `GirtLine`/`PlateLine` and every beam
   reading `Span`; splitting `Bay` out saved 30%; (b) the **joint
   VarSet** — a longer tie moves its end-B datum, the joint VarSet reads
   that datum, so the post's mortise (which needs only the tie's
   *section*) recomputes, and with it every later Boolean in that post's
   chain; (c) the **Dims VarSet** — `LengthZ` sits beside `WidthX/Y`, so
   a length change counts as a change for anything reading the section.
10. **`Refine` costs ~15%** of a Bay edit. Keep it on: refined faces are
    what shop drawings dimension.

**Isolation, not micro-optimisation, is the lead** — pursued in round 4.

## Round 4: recompute isolation (3.2x, and it reaches the floor)

Harness: `tests/spike/spike_recompute_isolation.py N`. It rewires the
document round 2 built, one level at a time, profiling a `Bay` edit and
re-verifying the geometry after each (volumes back at `Bay` = 10 ft,
every joint seated, one solid each — all levels passed).

| Level | What moves onto its own object | 5 bents: objects recomputed | Time |
|---|---|---|---|
| L1 | baseline | 514 of 1676 | 4.60 s |
| L2 | `Bay` alone on its own VarSet | 337 | 3.15 s |
| L3 | + `LengthZ` onto `TLen_<timber>`, section stays on `TDim_` | 329 | 3.26 s |
| L4 | + joint VarSet keeps only parameters; `Plc_<side>` (datum placement) and `Sec_<side>` (section, read from Dims, not through the datum) | 309 | 3.04 s |
| L5 | + `DepthW` off `Sec_<side>` | **215** | **1.46 s** |

The ratio holds at every size tested — 3 bents: 2.32 s → 0.65 s
(3.6x); 10 bents: **10.44 s → 3.22 s**, 1099 objects → 480 (3.2x),
geometry verified identical. Object count grows ~11% (1676 → 1856 at
five bents; 3551 → 3936 at ten), all of it small VarSets.

### Findings

11. **L5 is the level that pays, and it reaches the floor.** After it,
    *no post geometry recomputes at all* on a `Bay` edit — only the ties
    and their tenons, which is exactly the work the change requires. The
    earlier "~0.7 s floor" under-counted: it attributed component bodies
    to posts, and the true necessary work is ~1.45 s at five bents.
12. **Why L5 and not L4:** at an **end** datum `DepthW` *is* the
    timber's length. Leaving it beside `WidthU`/`WidthV` on one VarSet
    means a length change touches that object, and every reader of the
    *section* recomputes — the same per-object leak one level down.
    L2–L4 without it only shaved 30%.
13. **A central "master variables" VarSet that others read re-creates
    the cascade.** Probed directly: editing `Central.Bay` recomputed a
    box bound to `Central.Span` through its own mirror VarSet, because
    every mirror reads the same central object. **The object the user
    edits must be the isolated one** — so the single place to edit
    everything is the front end's panel (find the right VarSet, write to
    it), never a mirror object in the model. (Adam's instinct was to
    bind working variables back to a central source; this is the reason
    not to.)
14. **Splitting the accessors breaks structural lookup.**
    `datums.host_datum` resolves which datum is the host by reading the
    joint VarSet's `HostPlacement` expression. Move the accessors and
    that resolution must follow them (the spike cached the pairs before
    L4 to keep verifying). Anything else resolving through the
    accessors — the linter's `component-reference-scope`, the template
    bar, `TemplateSpec` — has to move with it.

### What happens to the accessors

The eight accessors do not disappear; they move off the joint VarSet
onto small objects, same values, same bindings:

```
before  J-HousedMT-003  parameters + Host/Mate {Placement, WidthU, WidthV, DepthW}
                        each reading its datum:  <<D_T-Post-003_XNeg_001>>.WidthU
after   J-HousedMT-003  parameters only (+ Ranges, Template)
        Plc_<side>_J-…  .Placement = <<datum>>.Placement
        Sec_<side>_J-…  .WidthU/V  = <<TDim_<timber>>>.WidthX / .WidthY
        Dep_<side>_J-…  .DepthW    = <<TDim_…>>.WidthY or <<TLen_…>>.LengthZ
```

- **The one change of meaning:** the section accessor reads the timber's
  **Dims VarSet directly instead of through the datum** — that is what
  buys the isolation, since the datum object moves on every station or
  length change. The price is that the face→Dims mapping (`WidthU` is
  `WidthX` on a ±Y face, `WidthY` on a ±X face) now lives both on the
  datum and in the accessor's expression: Apply resolves it at apply
  time, a later *re-place* must rewrite it, and the linter should check
  the binding still matches the datum's face row.
- **Up to six accessor objects per joint, but only those a component
  reads need to exist.** `Joint_HousedMT` needs three — `Plc_Host`,
  `Plc_Mate`, `Sec_Mate`; its tenon reads its own datum directly for
  widths and nothing reads a depth. Per timber: 2 (`TDim_` section,
  `TLen_` length).
- **Pairing comes loose from the accessors.** `datums.pair()` records
  the pairing as strings on both datums *and* binds the accessors;
  `host_datum()` then infers which datum is the host by reading the
  `HostWidthU` expression. That inference must become an explicit record
  (e.g. a `HostDatum` string on the joint VarSet). The pairing data
  itself is safe — the datums carry `MateDatum` and `Joint`.
- **Templates need not change:** keep a template's joint VarSet in
  today's single-object form (simpler to author) and let Apply expand it
  into the split form, using the same token substitution it already runs
  over copied component expressions.
- The new objects nest under the timber joint's handle beside the
  parameter VarSet and the seat — four to six small items per handle.
- **Apply's wiring, the linter rules, the template bar and the
  conventions in CLAUDE.md all change** — a component's contract becomes
  "reads its own side's placement, the parameters, and the other side's
  section", which is more precise than today's "its own datum and its
  joint VarSet".
- **Findability gets worse before the panel makes it better** — which is
  the argument for building the panel's expression tracing alongside,
  not after (finding 13).

### Decided after round 3 (Adam, 2026-09-19)

- **No Assembly object.** Its only remaining job was grounding the
  principal timber for a solver that no longer runs, and a grounded
  joint does not lock anything without it. The frame is a Std Group; the
  principal timber is anchored by binding its `Placement` to a project
  `FrameOrigin` (an expression-driven value cannot be dragged or typed
  over, and moving the frame is then one edit). Converting a frame to a
  native Assembly with Fixed joints becomes an **export** (Phase 2).
- **Dragging is not wanted**: a timber is positioned by its joints and
  its variables. Visual editing comes from the layout sketch, whose
  dimensions carry the same expressions the timbers do (roadmap, front
  end, item 2).

## Artifacts for GUI inspection (gitignored, machine-local)

- `scratch/FlatFrame01.FCStd`, `FlatFrame02.FCStd` — solver-driven
  flat frames, 3 bents (02: after the `Handed` change, no mirrorings).
- `scratch/ExprFrame01.FCStd` — expression-seated, 3 bents, seats at
  root; `ExprFrame02.FCStd` — the same with the seats nested under the
  handles by hand (Adam). `ProjectVars` (`Bay`, `Span`, `GirtLine`,
  `PlateLine`) drives each.

## Fixes landed alongside (branch `claude/per-machine-freecad-path`)

- Joint handle markers draw in their container's frame
  (`joint_handle.marker_position`).
- Duplicate Timbers offsets the copied timbers, never the new bent
  assembly's Placement.
- Apply dialog keeps a chosen face when the role's timber changes.
  **Still open:** switching the template rebuilds every row and resets
  all timber and face choices (Adam hit this switching Butt → HousedMT).
