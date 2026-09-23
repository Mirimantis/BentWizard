# Spike: do 26.3's fine-grained recomputes replace the value splits?

Implements [spike-fine-grained-recompute-brief.md](spike-fine-grained-recompute-brief.md).
Measurement only; no production code changed.

- Build: **26.3.0**, weekly `2026.09.16`, git `a4ce44d33b`, tag `26.3` below
  (`C:\Users\Admin\projects\FreeCAD_weekly-2026.09.16-Windows-x86_64-experimental`;
  its `python.exe` is under `bin\`, as 1.1.x)
- Baselines: **1.1.3** on the **7010**, from
  [spike-flat-frame-results.md](spike-flat-frame-results.md) round 4
- Branch: `claude/flat-frame-seats` (workstream A). The brief said to run
  from `claude/gui-round-3` because the harness imported `assemble`;
  commit `fd284cc` repointed `spike_expression_seat` at `frame.py`, so
  the harness runs on A. The workbench imports cleanly on 26.3.

**Verdict: workstream B is retired — the engine does it better.** On
26.3 with fine-grained recomputes on, the *unsplit* five-bent frame
recomputes 145 objects in 0.88 s, against 215 / 1.51 s for the fully
split document, and the ladder between them is flat (finding 3). Adam's
decision, 2026-09-20: keep local-frame operands behind
`UseLegacyBodyPlacement` for now, and work toward global binding and
full 26.3 compatibility by release.

**Original verdict, before step 2 was unblocked: step 1 answered yes,
step 2 blocked but not stuck.**
Expression edges *are* property-level, which is what workstream B's
premise turned on. The frame-scale matrix cannot be run as things stand,
because 26.3 deliberately changed the frame a `PartDesign::Boolean`
resolves its operand in — but that change ships with a per-Boolean
compatibility flag that restores the old behaviour exactly, so the
matrix is a short step away rather than blocked on upstream. B stays
parked; adopting 26.3 is now the larger question.

## Finding 1 — expression edges are property-level (step 1: yes)

Two `Part::Box`es, `Length` bound by expression to two properties of one
VarSet; edit one property; count `slotRecomputedObject`.

| `FineGrainedRecompute` | Recomputed on editing `VS.Bay` |
|---|---|
| False | `VS`, `BoxBay`, **`BoxSpan`** — today's behaviour, and the probe works |
| True | `VS`, `BoxBay` |

The PR discussion never said whether expression edges carry
property-level granularity; they do. This is the answer B was parked
for, and on its own it says the five levels of splitting are the same
optimization the engine now performs.

**It ships on by default in this weekly build.** The parameter is absent
from a fresh config and the untouched run behaves property-level — so
Hijma's project page is right and the release note's "experimental,
opt-in" does not describe the weekly. Read the parameter, do not assume.

Note for anyone writing probes: `<<VS>>.A` fails to parse — `A` is the
ampere (round 2, finding 6). Name probe properties `Bay`/`Span`.

## Finding 2 — 26.3 changes the Boolean's operand frame, on purpose, with an escape hatch (step 2: blocked until we take it)

**Corrected 2026-09-20 (Adam).** The first version of this finding
called the change a regression and guessed at OpenCASCADE 8. Both wrong,
and the evidence recorded here already said so — a plain `Part.fuse` is
unaffected and the result is identical with fine-grained recomputes on
and off, which rules the kernel out. The measurements below stand; the
attribution did not.

It is an **intentional** change: upstream issue #30393 ("PartDesign
boolean cut does not respect Transformed position of bodies", reported
against 1.2.0dev, May 2026), fixed by PR #30575. Someone moved a master
body, ran a cut, and objected that the tool snapped back to the
untransformed position — the opposite of what this workbench relies on.
Operands now resolve **globally**, and the old semantics live behind a
per-Boolean compatibility flag, `UseLegacyBodyPlacement`:

```cpp
if (UseLegacyBodyPlacement.getValue()) {
    return getTopoShape(object, Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform);
}
return getTopoShapeInLocalCoordinates(object);
```

Measured on this build: the flag is present on `PartDesign::Boolean`, is
an `App::PropertyBool`, **defaults to False**, is settable from Python,
and setting it True restores the old result exactly (1 solid, 2032000 —
the same number 1.1.3 gives). It is absent on 1.1.3, so code that sets
it must tolerate its absence.

Consequences to carry into the 26.3 work:

- The flag is **per Boolean object**, not a preference: every Boolean
  BentWizard creates would have to set it — `apply.py`, `component.py`
  — and the **shipped library templates carry their own Booleans**, so
  they need it set or rebuilding.
- Documents saved before the flag existed restore it at its default
  (False), so **pre-existing documents adopt the new semantics on open**
  in 26.3 whatever we do to new ones.
- Therefore the real question is not "how do we get unblocked" — the
  flag does that — but **whether to keep local-frame operands behind a
  compatibility flag or move to global binding**, which is where
  upstream is heading. See the compatibility brief.

### The measurements (unchanged)

`spike_recompute_isolation.py` cannot build its frame on 26.3:

```
Fuse.Tenon.HousedMT.002 leaves T-Beam-001 as 2 solids — the adder
does not land inside the stick (severed, or missed it)
```

The full suite on 26.3: **2 failures, 13 errors of 123**, and 13 of the
15 are that same message. Isolated to one behaviour change, with the
same script on both builds:

| Step | 1.1.3 | 26.3 |
|---|---|---|
| Apply a joint (tenon into a beam at the origin) | 1 solid | 1 solid |
| Move the beam, recompute | 1 solid | 1 solid |
| Apply a second joint to the **moved** beam | **1 solid** | **2 solids** — tenon at (0, 0, 3105), beam at (518, 1011, 1767) |

A `PartDesign::Boolean` used to interpret its operand in the **body's
local frame** — the basis of the whole component mechanism, and the
reason a component binds to its datum's *local* `Placement`
(`CLAUDE.md`, Conventions; round 3 T5). On 26.3 the operand no longer
follows the moved body, so every tenon fused into a timber that a seat
has already placed lands outside it. Not caused by fine-grained
recomputes: identical with the preference off and on.

A minimal fuse is unaffected — two boxes meeting on one coincident face
still give one solid on both builds, with and without `Refine` — so this
is about the operand's frame, not the kernel's boolean.

**`Cut` behaves the same way, and quietly.** In a workbench-free repro
(a 100×100×200 stick, a 40³ tool straddling its top face, the Body moved
1000/500 and rotated 30°): `Fuse` gives 2 solids and 2064000 — the stick
plus the *whole* tool, added as a disjoint lump — while `Cut` gives 1
solid and 2000000, the bare stick, having removed nothing and reported
success. Both are correct under the new contract (the tool is simply
somewhere else); both are silent. Every failure in the suite was a
`Fuse` only because the anchored posts do not move and the beams and
ties do.

## Finding 3 — the engine beats the hand-split document (step 2: done)

Taken 2026-09-20 with `UseLegacyBodyPlacement` forced on every Boolean
as it is created (a document observer in the harness wrapper — no
production code changed), which is what unblocked the frame. Five bents,
1666 objects, 26.3, the 7010; the preference toggled **within the same
build**, so nothing else differs.

| Level | Fine-grained OFF | Fine-grained ON |
|---|---|---|
| L1 baseline (unsplit) | 512 obj / 4.92 s | **145 obj / 0.88 s** |
| L2 `Bay` alone | 335 / 3.39 | 145 / 0.89 |
| L3 + `TLength_` split | 327 / 3.35 | 145 / 0.87 |
| L4 + accessors | 307 / 3.30 | 147 / 0.87 |
| L5 + `DepthW` split | **215 / 1.51** | 147 / 0.88 |

- **The unsplit document on the new engine beats the fully-split
  document on the old one** — 145 objects against 215, 0.88 s against
  1.51 s. The decision rule written before the numbers ("L1-on lands at
  or near 215 → the splits are redundant") is met with room to spare.
- **The ladder is flat with the preference on.** Splitting buys nothing,
  and past L3 it costs a little: 147 against 145, because the extra
  VarSets are themselves objects to recompute. Every level Workstream B
  would have built is now dead weight.
- **The OFF column reproduces the 1.1.3 ladder** (512/4.92 → 215/1.51
  against 514/4.60 → 215/1.46), which is the control: the harness
  measured the same thing on both builds, so the ON column is the
  feature and not the release.
- **Geometry verified at every level**, both ways: volumes back to the
  baseline at `Bay` = 10 ft, worst misfit 4.5e-12 mm, one solid each,
  nothing left Touched. An experimental engine feature that silently
  changed a result would be worse than a slow one; it does not.

## What this means for workstream B

- **B is retired**, subject to 26.3 becoming the minimum. Finding 3
  measures the engine doing better than all five levels, so the splits
  would be pure cost: more objects, a scattered tree, Apply's wiring
  rebuilt, the linter and templates following — to land *behind* where
  the unsplit document already sits.
- **The grouping Adam wanted is free.** Layout variables can be grouped
  by what they drive, thematically, the way a framer expects; the
  overlap penalty finding 15 measured (bay width and girt station
  sharing one VarSet cost 75%) is a property of the old engine. Re-run
  that probe on 26.3 to confirm it goes to zero before relying on it.
- **On 1.1.3 the old cost stands.** Until 26.3 is the minimum, a `Bay`
  edit is ~4.9 s at five bents. That is a performance dependency, not a
  correctness one: the document recomputes to identical geometry either
  way, just slowly.
- **Adopting 26.3 is now the bigger question**, and it is not a
  performance question: it is whether to keep local-frame operands
  behind `UseLegacyBodyPlacement` — a flag on every Boolean we create,
  including the ones inside the shipped templates — or to follow
  upstream to global binding. Global binding is where the project is
  heading, but the joint VarSet cannot read a timber's `Placement`
  without the cycle round 2 found (finding 5), so it needs design. The
  `Seat_J-…` VarSet is the precedent that the shape works.

## Suggested next steps

**All four done by 2026-09-22** — the operand contract was decided
(route (a), finding 12 in [spike-26-3-gui-results.md](spike-26-3-gui-results.md)),
26.3 is the minimum, and B is retired for good; the last parked
measurements are findings 13–15 below. Kept as the record of the plan.

1. **Nothing to report upstream.** A draft issue was written here and
   withdrawn: the change is intentional (#30393 → #30575) and already
   carries its compatibility flag. Filing it would have been noise.
2. **Unblock step 2 with the flag**, then re-run the matrix: set
   `UseLegacyBodyPlacement` on the Booleans the harness creates and the
   frame builds again, giving the decisive L1-on cell without waiting on
   anyone.
3. **Keep B parked.** Do not start the splits on the strength of
   finding 1 alone, and do not abandon them until the frame-scale number
   exists.
4. **Decide the operand contract deliberately** (see the compatibility
   brief): the flag is an unblock, not an answer. Upstream's default is
   global, and a compatibility flag set on every Boolean is a debt that
   grows with every template and saved document.

## Findings 13–15 — sharing a VarSet is free, and it scales (brief section 4)

Taken 2026-09-22 on current `main` (`86c1e05`: route (a) in production
code, accessors on their own VarSet), 26.3.0 weekly `2026.09.16`
(git `a4ce44d33b`; the build itself reports its hash as `Unknown`),
the 7010. Harness: `tests/spike/spike_overlap_scale.py N`. Each
fine-grained setting gets a freshly built document, and the harness
restores the user's preference afterwards.

The numbering continues from findings 4–12 in
[spike-26-3-gui-results.md](spike-26-3-gui-results.md). The flat-frame
record has findings 13 and 15 of its own, from its round 4; those are
cited below as **flat-frame finding 13** and **flat-frame finding 15**.

### Finding 13 — the overlap penalty is zero, at every size

A `Bay` edit with `Bay` sharing `ProjectVars` with `GirtLine`,
`PlateLine` and `Span` (L1), against `Bay` alone on a VarSet of its own
(L2). Compared **by set** as well as by count — equal counts could hide
objects trading places, equal sets cannot.

| bents | ON: L1 / L2 objects | ON penalty | OFF: L1 / L2 objects | OFF penalty |
|---|---|---|---|---|
| 2 | 37 / 37 | **0** | 145 / 84 | 61 |
| 5 | 145 / 145 | **0** | 460 / 303 | 157 |
| 10 | 325 / 325 | **0** | 985 / 668 | 317 |

With fine-grained ON the recomputed sets are **identical** shared and
isolated, and none of the objects that read only `GirtLine` / `PlateLine`
/ `Span` recompute on a `Bay` edit — 0 of 10, 0 of 31, 0 of 66. With it
OFF, on the same build, every one of them does, and the penalty grows
with the frame: the control reproduces flat-frame finding 15.

**So flat-frame finding 15 is overturned on 26.3.** Per-variable VarSets
are no longer load-bearing; layout variables can be grouped however a
framer finds natural — thematically, by level, in one place — at no
recompute cost. This is what the layout-variable design rests on, and it
is now measured rather than inferred from finding 1's two boxes.

### Finding 14 — the cost is linear in bays, and the accessor split cost nothing

| bents | bays | ON: objects | per bay | seconds (7010) |
|---|---|---|---|---|
| 2 | 1 | 37 | 37 | 0.22 |
| 5 | 4 | 145 | 36.3 | 0.90 |
| 10 | 9 | 325 | 36.1 | 2.15 |

About **36 objects and 0.23 s per bay**, flat from 2 to 10 bents — which
is exactly the necessary work: every tie that changes length and every
bent that moves past it. At the roadmap's ~12-bent target that projects
to ~400 objects and ~2.5 s on the 7010 (about half that on the i9, by
the flat 1.9x ratio in the flat-frame record). Geometry held throughout:
worst misfit 7.3e-12 mm at ten bents, one solid each, nothing left
Touched or Invalid.

Against the old engine on the same build (the OFF column), ten bents is
**985 → 325 objects and 11.5 → 2.15 s, 5.3x**. For context only — a
different build and older code — 1.1.3's fully hand-split ten-bent frame
took 3.22 s (flat-frame round 4, L5); the unsplit document on 26.3 beats
it, as finding 3 found at five bents.

**The accessor split cost nothing.** Five bents recompute 145 objects on
a `Bay` edit, exactly finding 3's L1, which was measured before the
split. The document grew by 26 objects (1666 → 1692) — one accessor
VarSet per joint, and there are 26 — and a `Bay` edit touches none of
them.

### Finding 15 — a central "master variables" VarSet no longer cascades

Flat-frame finding 13 measured, on 1.1.3, that a central VarSet read by
per-variable mirror VarSets re-created the cascade — editing
`Central.Bay` recomputed a box bound to `Central.Span` through its own
mirror — and concluded that the object a user edits must be the
isolated one, so "the single place to edit everything is the panel,
never a mirror object in the model". The same probe on 26.3:

| fine-grained | editing `Central.Bay` recomputes |
|---|---|
| ON | `Central`, `MirrorBay`, `BoxBay` — `MirrorSpan` and `BoxSpan` untouched |
| OFF | adds `MirrorSpan` and `BoxSpan`: the 1.1.3 cascade, reproduced |

**Overturned on 26.3.** A central variables object is safe. The panel
may still be the better place to *find* a variable, but that is now a
design choice for the front end, not something the engine forces.
