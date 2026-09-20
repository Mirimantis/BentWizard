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

**Verdict: step 1 answered yes, step 2 is blocked.** Expression edges
*are* property-level, which is what workstream B's premise turned on —
but the frame-scale matrix cannot be run, because 26.3 breaks the
component mechanism itself for any timber that has been moved. B stays
parked; 26.3 compatibility is now the larger question.

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

## Finding 2 — 26.3 breaks the Boolean's local frame (step 2: blocked)

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

Untested: whether a `Cut` (a mortise into a moved host) fails the same
way. Every failure observed was a `Fuse`, because in these frames the
anchored posts do not move and the beams and ties do.

## What this means for workstream B

- **B's premise is gone if 26.3 ships as measured.** Finding 1 says the
  engine removes the false edges by itself, which is all the splits do.
  The grouping Adam wants — layout variables grouped by what they drive —
  costs nothing on a per-property graph.
- **But the measurement that would prove it at frame scale is blocked**
  by finding 2. The decisive cell (L1 with the preference on, against
  215 objects at L5 today) needs a frame that 26.3 cannot currently
  build.
- **26.3 compatibility is now the bigger question**, and it is not a
  performance question: it is whether the component mechanism survives a
  change to how a Boolean frames its operand. Binding components to a
  datum's *global* placement is the obvious repair, but the joint VarSet
  cannot read a timber's `Placement` without a cycle (round 2, finding
  5), so it needs design, not a one-line change.

## Suggested next steps

1. **Report finding 2 upstream** with the three-step repro above. If it
   is a regression it should be fixed before 26.3 releases; if it is
   intentional, BentWizard needs to know the new contract.
2. **Re-run step 2 once the frame builds** — either after an upstream
   fix or against a variant that binds components globally.
3. **Keep B parked.** Do not start the splits on the strength of
   finding 1 alone, and do not abandon them until the frame-scale number
   exists.
4. **Do not adopt 26.3 as a minimum** on the strength of finding 1: as
   measured, the workbench does not work on it.
