# Spike brief: do FreeCAD 26.3's fine-grained recomputes replace the value splits?

**For a fresh session.** This is a measurement, not a build. Change no
production code. Everything here is self-contained — you need nothing
from the workstream-B session, which is parked pending this result.

## The question

BentWizard's Phase 1 performance problem is that FreeCAD's dependency
graph is per **object**: editing one property of a VarSet touches the
whole VarSet, so every object reading *any* of its properties
recomputes. On a five-bent frame a `Bay` edit recomputed 514 of 1676
objects in 4.6 s — nearly all of it posts whose cuts had not changed
(`spike-flat-frame-results.md`, rounds 3–4).

Workstream B exists to work around that by hand: split the objects along
what actually varies — one VarSet per project variable, `LengthZ` off
the section, the joint VarSet down to parameters with per-side `Plc_`,
`Sec_` and `Dep_` accessors — five levels, measured at 3.2x. Adam's
objection is that it scatters single variables across the tree and
fights what a VarSet is for. He is right that it is a workaround.

**FreeCAD 26.3 introduces the real fix.** From its release notes:
"Fine-grained recomputes were introduced. These are recomputes based on
dependencies between properties instead of objects. This is an
experimental feature that can be toggled with a preference." That is
PR #25603 by Pieter Hijma, phase 1 of FEP-0010 (Variant Parts), which
computes `InListProp`/`OutListProp` from (object, property) dependency
edge tuples while keeping topological ordering at the object level.

The limit to keep in mind: the *target* object still recomputes whole —
there is no partial execution of a Pad. What disappears is the **false
edge**, and false edges are the entirety of what B's splits exist to
break. So per-property granularity and B's five levels are plausibly the
same optimization, one done by the engine.

**The unknown that decides everything:** BentWizard's dependencies are
almost all **expressions**, not `PropertyLink`s. The PR discussion does
not explicitly say whether expression edges carry property-level
granularity. The information exists — `ExpressionEngine` knows the
identifiers on both sides — and the FEP's framing implies it, but that
is inference, not measurement.

Two caveats on the sourcing: the release-note text above is from a
documentation mirror, and Hijma's own project page says the feature is
*enabled by default in weekly builds* while the notes call it
experimental and opt-in. Do not assume which state your build ships in —
read the parameter.

## Step 1: the five-minute probe. Do this first

If expression edges are not covered, everything below is moot. This
mirrors the two-box probe that ruled out the Spreadsheet (finding 16).

Build: a VarSet with two length properties `A` and `B`; two boxes, one
with `Length` bound by expression to `<<VS>>.A`, the other to
`<<VS>>.B`. Attach a document observer counting `slotRecomputedObject`.
Change `A` alone, recompute, and record which objects recomputed.

- Preference **off**: both boxes recompute. This is today's behaviour and
  confirms the probe works.
- Preference **on**: only the box bound to `A` recomputes → expression
  edges are property-level. Proceed to step 2.
- Preference **on** and both still recompute → expression edges are not
  covered. **Stop.** Record it, and report it upstream: BentWizard's
  frame harness is an unusually good real-world case for this feature,
  and the FEP author will want it.

Toggle:

```python
FreeCAD.ParamGet('User parameter:BaseApp/Preferences/General').SetBool(
    'FineGrainedRecompute', True)
```

## Step 2: the frame-scale matrix

Run the existing harness — it builds the frame, then rewires it one
level at a time, printing objects recomputed and seconds for a `Bay`
edit at every level from the unsplit baseline through L5:

```
<26.3>\bin\python.exe tests\spike\spike_recompute_isolation.py 5
<26.3>\bin\python.exe tests\spike\spike_recompute_isolation.py 10
```

Run each **twice on the same build**, once with the preference off and
once on. That is the whole design: toggling within one build isolates
fine-grained recomputes from 26.3's other big change — the OpenCASCADE 8
adaptation — which would otherwise confound any comparison against the
1.1.x numbers.

Recorded baselines to compare against, all on the **7010** (Dell
OptiPlex 7010, FreeCAD 1.1.3), five bents, 1676 objects:

| Level | Objects | Time |
|---|---|---|
| L1 baseline (unsplit) | 514 | 4.60 s |
| L2 `Bay` on its own VarSet | 337 | 3.15 s |
| L3 + `TLen_` split | 329 | 3.26 s |
| L4 + `Plc_`/`Sec_` accessors | 309 | 3.04 s |
| L5 + `DepthW` split | **215** | **1.46 s** |

Ten bents: 1099 → 480 objects, 10.44 s → 3.22 s. The i9 ran 1.9x faster
at every level with **identical object counts** — the counts are a
property of the dependency graph, the times are not.

**The decisive cell is L1 with the preference ON, against L5 with it
OFF** (215 objects at five bents). If the engine gets the *unsplit*
document to roughly where the fully-split document sits today, B's
splits are dead and Adam keeps the VarSets he wants.

Also worth having: L5 with the preference on. If splitting still buys
something on top of fine-grained recomputes, the ladder says which
levels.

## Guardrails

- **Object counts are the measure; seconds are context.** You are
  comparing across a FreeCAD major version and possibly a kernel change.
  Counts survive that; times do not.
- **Correctness first.** The harness already re-verifies geometry after
  every level — volumes back at `Bay` = 10 ft, every joint seated, one
  solid each. An experimental engine feature that silently changes a
  result is worse than a slow one. Also check nothing is left `Touched`
  and the console is silent; both were clean in the 1.1.x runs.
- **Record the build hash** beside the machine tag, per the project's
  existing convention of quoting a tag with any timing.

## Practical setup

- **Run from branch `claude/gui-round-3`.** The harness imports
  `freecad.bentwizard.assemble` (through `spike_expression_seat`), and
  workstream A removes that module on `claude/flat-frame-seats`. Do not
  run this on A's branch.
- Use the **26.3 build's own bundled `python.exe`**, not the 1.1.x one.
- **The workbench junction will not carry over.** 1.1.x shares the
  `%APPDATA%\FreeCAD\v1-1` config folder; a calendar-versioned build
  uses its own. `scripts\dev-install.ps1` must point the new install's
  `Mod` folder at the repo, and it has to be run **from a normal shell
  outside the Claude desktop app** — that app is an MSIX package and
  silently redirects `%APPDATA%` writes into its own LocalCache, so the
  junction looks right from inside and is invisible to FreeCAD. Hand
  Adam the command rather than running it; an in-app `Test-Path` is not
  proof.

## The decision rule, written before the numbers

- **L1 with the preference on lands at or near 215 objects** → the
  splits are redundant. B collapses to whatever it needs for reasons
  other than recompute isolation, project variables stay grouped the way
  a framer would expect, and BentWizard's minimum FreeCAD becomes 26.3
  (a performance dependency, not a Tier 1 one: with the preference off
  the document still recomputes to identical geometry, just slowly).
- **It lands partway — near L2 or L3** → keep only the levels that still
  pay, and say which, from the measured ladder rather than from the
  original plan.
- **No effect on expression edges** → B proceeds as originally designed,
  and the result goes upstream.

## What to write back

`docs/spike-fine-grained-recompute-results.md`, in the house pattern:
numbered findings, the tables, machine and build tags, and a one-line
verdict on workstream B. If the verdict changes B's shape, also update
the closing section of `docs/workstream-a-handoff.md`, which currently
still describes B's original plan.
