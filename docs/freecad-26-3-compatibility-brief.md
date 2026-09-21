# Brief: make BentWizard work on FreeCAD 26.3

**For a fresh session — this is the next piece of work.** Adam's
decision, 2026-09-20: BentWizard moves to 26.3 and takes the
fine-grained recomputes, and the weekly dev build becomes the primary
test environment once the workbench runs there. The rest of the rebuild
waits: **workstream C is not to start** beyond what section 2 needs,
because another 26.3 change could move the ground again.

Read first:
- [spike-fine-grained-recompute-results.md](spike-fine-grained-recompute-results.md)
  — everything measured on 26.3, findings 1–3. Finding 3 is why
  workstream B no longer exists.
- [spike-26-3-gui-results.md](spike-26-3-gui-results.md) — findings 4–8,
  section 3's GUI and suite bullets. The GUI loads clean, and all 15
  suite failures are finding 2 and nothing else: 123/123 green on 26.3
  with `UseLegacyBodyPlacement` forced on 221 Booleans. **The whole 26.3
  gap is now the section 1 decision.**
- [rebuild-flat-frame-handoff.md](rebuild-flat-frame-handoff.md) and
  [workstream-a-handoff.md](workstream-a-handoff.md) — the rebuild this
  interrupts, and the conventions it established.
- `CLAUDE.md` — conventions, the environment, and the weekly-build rules.
  An upstream issue draft was written here and withdrawn: the Boolean
  change is intentional and already carries its compatibility flag.

## What is already known

1. **Fine-grained recomputes cover expression edges**, which is what
   BentWizard is built from, and they are **on by default** in the
   weekly. Editing one property of a VarSet recomputes only the readers
   of that property. This is why Adam wants the move: it retires
   workstream B's five levels of hand-splitting and lets layout
   variables be grouped the way a framer expects.
2. **A `PartDesign::Boolean` resolves its operand globally now, by
   design, with an escape hatch.** A moved Body no longer intersects its
   own operand: `Fuse` gives two solids, `Cut` silently removes nothing.
   That is upstream #30393 → #30575, and the old behaviour lives behind
   a per-Boolean `UseLegacyBodyPlacement` (App::PropertyBool, default
   False, settable from Python, absent on 1.1.3; setting it True
   restores the old result exactly). It is why the suite on 26.3 is 2
   failures + 13 errors of 123 — every joint is a component Body
   booleaned into a timber, bound to its datum's *local* placement
   precisely because of the old contract. Not caused by fine-grained
   recomputes (identical with the preference off).

The remaining non-Boolean failures are in `measure`: `order_length`
short by exactly a tenon, and a `None` where a timber is no longer one
solid. Consistent with the same root cause, but confirm rather than
assume.

## Where things stand when you start

- **Workstream A is built and merged** (or in PR #20 if not yet):
  `frame.py`, seats by expression, the Std Group frame, no Assembly
  object. 123 tests green on 1.1.3, GUI probe clean, Adam's GUI round
  passed. **Branch from `main`** if A has landed; from
  `claude/flat-frame-seats` if it has not.
- **Workstream B is retired** (finding 3). Nothing to build.
- **Workstream C has not started** and is not yours unless the migration
  needs it: what a handle holds and what its `onDelete` moves out of the
  way. Note the accessor VarSet below lands *under the handle*, so the
  two touch — say which parts you did.
- **Workstream D is untouched.** One item bites today: `undo_repair`
  does not re-arm a seat, so undoing an Apply leaves one behind.
- The 26.3 measurements are all in
  `spike-fine-grained-recompute-results.md`; the harnesses run on A's
  branch (`fd284cc`).

## The work

### 1. Decide the operand contract (blocks everything else)

Nothing to report upstream and nothing to wait for: the change is
intentional and the flag is the escape hatch. Two routes, and this is
the session's first decision:

**(a) Keep local-frame operands behind the flag.** Set
`UseLegacyBodyPlacement = True` on every Boolean BentWizard creates
(`apply.py`, `component.py`) and on the ones inside the shipped
templates, which carry their own. Cheap, unblocks the suite immediately,
and nothing else in the mechanism moves. The debt: a compatibility flag
on a growing number of objects, pinned against upstream's chosen
direction, and it must tolerate the property's absence on 1.1.3.
**Documents saved before the flag existed restore it at its default —
so pre-rebuild documents adopt the new semantics on open regardless.**

**(b) Follow upstream: bind components globally.** The joint VarSet
cannot read a timber's `Placement` without the cycle round 2 found (a
timber's own components already read that VarSet), so this needs a
placement object that reads the timber *and* the datum — exactly the
shape `Seat_J-…` already has, which is **the existing proof it works**.
More design, but it ends the divergence.

Rejected before it is proposed: leaving components local and giving the
Boolean a target whose placement is identity, by moving the seat onto a
container. That reintroduces a moved container, which is what the flat
frame exists to avoid.

Whatever is chosen has to keep: no Body reads a datum directly (the
scope rule), datums never read each other, and the mirror/parity rule.
Route (a) is also the quickest way to unblock the parked measurements in
section 4, whichever route is chosen for the long run.

### 2. Move the accessors to their own VarSet (part of this migration, Adam 2026-09-20)

Today the joint VarSet `J-<Kind>-<serial>` carries both what a framer
edits (the parameters) and eight tool-written accessors
(`HostPlacement` … `MateDepthW`) that exist only because **a Body may
never read a datum's `Placement`** — the scope rule behind the
`XZ_Plane005` failure of Adam's second GUI round. Split them: **one**
accessor VarSet per joint, filed under the handle in the `Accessors`
group Adam picked, leaving the joint VarSet holding only parameters.
Not B's three-to-six per-side objects — B is dead; this is tidiness.

What resolves *through* the accessors today and must follow them:

- `datums.host_datum` — works out which datum is the host by reading the
  `HostWidthU` expression. Replace the inference with an explicit
  record (a `HostDatum` string on the joint VarSet) rather than moving
  the sniff.
- `datums.pair`/`unpair`/`ensure_accessors`, `apply.py`'s copy step
  (it clears and re-binds accessor expressions), `TemplateSpec`'s role
  resolution, the template bar's pairing rule, the linter's
  `component-reference-scope` and `component-placement-direct`,
  `duplicate.py`'s expression rewriting, and the accessor names in
  `naming.py`.
- Templates keep today's single-VarSet shape; Apply expands on
  application, reusing the token substitution it already runs over
  copied component expressions.

`TDim_<timber>` **stays whole** — no section/length split, and future
dimension drivers (rafter pitch, brace slope) go in beside
`WidthX`/`WidthY`/`LengthZ`.

### 3. Sweep for the rest of 26.3's changes

The point of this session is to find the *other* surprises before more
is built on sand. At minimum:

- ~~**The suite**, triaged failure by failure, cause by cause — not just
  a count.~~ **Done 2026-09-20 (findings 7–8):** 12 tests die at Apply
  on the one-solid assertion, 3 measure short past it, and all 15 clear
  under the flag. No independent `measure` regression — the section's
  own suspicion, confirmed rather than assumed. Note the 11 `test_frame`
  behaviours are *untested* on 26.3, not failing: they die in fixture
  setup.
- ~~**The GUI**: does the workbench load at all~~ **Done 2026-09-20
  (findings 4–6):** yes — 47 checks, 0 failures, console silent. The
  runtime under it moved a long way (Python 3.11 → **3.14**, PySide6
  6.8 → **6.11**, pivy relocated to `Mod\pivy`) and none of it bit.
  Still unproven: **rendering** (visual, needs Adam's GUI round) and
  **Apply Timber Joint's GUI path**, which the section 1 decision
  unblocks rather than more probing. The junction for 26.3 is a
  *different* config folder, `%APPDATA%\FreeCAD\v26-3\Mod` — already in
  place on the 7010, and `scripts\dev-install.ps1 -FreeCadVersion v26-3
  main` must be run **by Adam from a shell outside the Claude desktop
  app** (MSIX redirects `%APPDATA%` writes; an in-app `Test-Path` is
  not proof).
- **Expression engine**: `minvert`, placement multiplication and the
  `<<Label>>` forms the seats depend on.
- **Datums**: `Part::LocalCoordinateSystem` placement and the
  child-axis scope behaviour recorded in `CLAUDE.md`.
- **VarSets and the Spreadsheet**: re-run the finding-16 probe — per-cell
  tracking may now exist, which would change the "spreadsheets are for
  reading" guidance.
- **Assembly**: only needed for the Phase 2 export now, but confirm
  whether the marker bug that started all of this still exists.

### 4. The parked measurements — the main one is taken

**Done 2026-09-20 (finding 3): workstream B is retired.** At five bents
on 26.3 with the flag forced on, the *unsplit* document recomputes 145
objects in 0.88 s against 215 / 1.51 s fully split, and the ladder
between is flat. The engine beats every level B would have built.

Still worth taking in this session:

- **The overlap probe on 26.3** (`BayWidth` + `GirtHeight` sharing one
  VarSet cost 75% on 1.1.3). Expected to go to zero, which is what makes
  thematic grouping free — confirm rather than assume, because the whole
  layout-variable design now rests on it.
- **Ten bents**, to check the flat ladder holds with scale.
### What survives of workstream B (Adam, 2026-09-20)

The splits are gone; the readability decisions carry forward, minus the
ones that only existed to serve the splits.

- **`TDim_<timber>` stays whole.** No `TSection_`/`TLength_` split: a
  timber's dimensions belong in one VarSet, and that is where future
  ones go too — pitch or slope for rafters and braces was the example.
  The split existed only for recompute isolation, which the engine now
  does.
- **Accessors are still needed, and move to their own VarSet.** Not for
  performance — because of the scope rule: a Body may never read a
  datum's `Placement` (the `XZ_Plane005` out-of-scope failure of Adam's
  second GUI round), so a VarSet reads the datums and components read
  the VarSet. What changes is tidiness: **one** accessor VarSet per
  joint rather than B's three-to-six per-side objects, filed away from
  the user, leaving the joint VarSet holding only what a framer edits.
  Carry with it: `datums.host_datum` resolves the pairing by reading the
  `HostWidthU` expression, so that lookup follows the accessors wherever
  they go, as does `TemplateSpec`'s role resolution and the linter's
  `component-reference-scope`.
- **Naming carries forward**: Layout Variables rather than project
  variables, labels descriptive of what they drive
  (`<<SecondFloorBeam>>.Height`), spelled-out accessor names, and
  single-letter abbreviations only for the two central objects, T and J.
- **Layout variables may be grouped thematically** — the reason the
  splits were resisted, now free (confirm with the overlap probe).

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

- **The weekly dev build becomes the primary test environment** once the
  workbench runs on it (Adam, 2026-09-20); he installs a fresh weekly
  each week until 26.3 releases. So: expect the install folder to change
  name every week, quote the build's git hash with any measurement, and
  **do not hard-code the path** — find it as
  `..\FreeCAD_weekly-*-Windows-x86_64-experimental\` beside the
  checkout, the same rule as the 1.1.x installs.
- One junction serves every weekly: all 26.3 builds share the
  `%APPDATA%\FreeCAD\v26-3` config folder, so
  `scripts\dev-install.ps1 -FreeCadVersion v26-3 main` is a one-time
  setup that survives each new install — Adam runs it from a shell
  outside the Claude desktop app.
- Current build: `FreeCAD_weekly-2026.09.16-Windows-x86_64-experimental`,
  26.3.0, git `a4ce44d33b`, `bin\python.exe` as usual. Tag it `26.3`
  beside the `7010` / `i9` machine tags in any timing.
- **1.1.3 stays the compatibility target** until the suite is green and
  a GUI round passes on 26.3 — `main` must keep working there.
- Branch from `claude/flat-frame-seats` (workstream A: the seats and the
  frame container this all now rests on), not from `main`.
- The harnesses run on A's branch since `fd284cc`; the older
  `spike_flat_frame.py` is historical and exits with an explanation.
