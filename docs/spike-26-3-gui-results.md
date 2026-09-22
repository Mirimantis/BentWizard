# Sweep: 26.3's GUI surface, and the suite triaged

Section 3 of [freecad-26-3-compatibility-brief.md](freecad-26-3-compatibility-brief.md),
the GUI bullet and the suite bullet. Findings continue the numbering of
[spike-fine-grained-recompute-results.md](spike-fine-grained-recompute-results.md)
(findings 1–3). **Measurement only; no production code changed** — the
flag experiment of finding 8 runs from a document observer in the
scratchpad, not from an edit to `apply.py` or `component.py`.

- Build: **26.3.0**, weekly `2026.09.16`, git `a4ce44d33b`, tag `26.3`
  below; machine **7010**
- Baseline: **1.1.3** on the same machine, where it is quoted
- Branch: `main` (workstream A landed in
  [PR #20](https://github.com/Mirimantis/BentWizard/pull/20))
- Probe: one scripted GUI run (`freecad.exe --log-file <log> <probe.py>`,
  work in a `QTimer.singleShot`, window closed from a timer), in the
  session scratchpad per `CLAUDE.md`

**Verdict, GUI: everything loads; the dimension fields do not work.**
The probe's 47 checks pass with the console silent — the workbench
registers and activates, all 10 commands and the toolbar and menu build,
all 11 Qt widget classes construct, every Coin node in the two view
modules creates and attaches, and the tree hooks and the inline XPM icon
work (findings 4–6). Then Adam typed into those dialogs and found two
real bugs (finding 9) that a probe which only *constructs* widgets was
never going to see. **Loading was the wrong thing to be reassured by.**
One of the two is ours and predates 26.3; the other is a 26.3 input
change with no workaround from our side.

**Verdict, suite: every one of the 15 failures is the Boolean operand
change of finding 2, and nothing else.** 123/123 green on 1.1.3;
2 failures + 13 errors on 26.3; **123/123 green on 26.3 with
`UseLegacyBodyPlacement = True`** forced on all 221 Booleans. The three
numeric `measure`/`duplicate` failures the brief flagged as *confirm
rather than assume* are confirmed to share that root cause — there is no
independent `measure` regression (finding 8).

So the whole 26.3 gap is the one decision in section 1. The caveats at
the bottom are what stays unproven either way — the largest is that
**Apply Timber Joint's GUI path is still unexercised**, because the
operand contract blocks the operation itself.

## Finding 4 — the runtime under the workbench moved a long way; the code did not notice

The versions, side by side. Everything in this table changed, and none
of it broke anything.

| | 1.1.3 | 26.3 weekly |
|---|---|---|
| Python | 3.11 | **3.14.7** |
| PySide6 | 6.8.3 | **6.11.1** (Qt 6.11.1) |
| pivy | 0.6.9, in `bin\Lib\site-packages\pivy` | **0.6.11, relocated to `Mod\pivy`** |
| Coin | 4 (`Coin4.dll`) | 4.0.10 (`Coin4.dll`) |

Three notes for anyone writing a probe or a path against this build:

- **pivy has moved out of `site-packages` into `Mod\pivy`.** `from pivy
  import coin` still resolves, because FreeCAD puts `Mod` on the path —
  but anything that locates pivy by *file path* rather than by import
  will miss it. The bundled `python.exe` finds it the same way.
- **Python is 3.14.** The package imports and the whole suite collects
  under it (see the triage below); nothing in the workbench uses a
  stdlib module 3.14 removed.
- **PySide6 6.11 still accepts the unscoped enum forms** the workbench
  is written in: `Qt.Window`, `Qt.WA_DeleteOnClose`, `Qt.MatchContains`,
  `QDialogButtonBox.Ok | .Cancel`, `QMessageBox.Yes | .No` all resolve
  and OR together. They come back as Python enum members
  (`WidgetAttribute.WA_DeleteOnClose`), so `int()` on one now raises —
  that bites probe code that formats them, not the workbench, which
  never converts them.

## Finding 5 — the workbench registers and every surface builds

`Gui.activateWorkbench("BentWizardWorkbench")` succeeds, all 10 commands
register, `Gui.Command.get(...)` finds each, and `isActive()` raises for
none of them with or without an active document.

The toolbar is built by Qt with all 10 actions, and the menu is present.
Enablement with one plain timber open reads as expected: Apply and
Remove Timber Joint inactive (no paired datums), the other eight active.

**Every action carries `icon=False`.** That is pre-existing and by
design, not a 26.3 regression — no `GetResources` declares a `Pixmap`
and there is no `Pixmap` anywhere in `freecad/`. Worth a look in the new
Qt style, since a text-only toolbar may sit differently than it did.

All 11 Qt widget classes in `commands.py` construct and lay out:

| Dialog | Child widgets |
|---|---|
| `ApplyJointDialog` | 81 |
| `NewTimberDialog` | 42 |
| `_StoreInVarSetDialog` | 34 |
| `AddDatumDialog` | 33 |
| `SeatTimbersDialog` | 28 |
| `DuplicateBentDialog` | 21 |
| `NewJointTemplateDialog` | 20 |
| `SaveJointTemplateDialog` | 11 |
| `_ReportDialog` | 10 |
| `_DimField` | 6 |
| `_ExpressionEdit` | 0 |

`Gui.UiLoader().createWidget("Gui::QuantitySpinBox")` still returns a
live spin box, so the unit-schema fields are intact.

Two commands were run for real, being the two that open no modal dialog:
**Show Face & End Marks** toggles on and off, and **Audit Timbers**
opens its modeless report window.

## Finding 6 — the Coin markers create, attach and track

Every node type the two view modules use creates on Coin 4.0.10 with
pivy 0.6.11: `SoType.fromName("SoShapeScale")` (and `setPart`/
`scaleFactor`), `SoType.fromName("SoFCSelection")` (and its
`documentName`/`objectName`/`subElementName` fields), `SoVRMLBillboard`,
`SoText2` with `SoFont` and `SoText2.CENTER`, both `SoPickStyle` enums
(`SHAPE_ON_TOP` and `UNPICKABLE`), `SoCoordinate3`/`SoFaceSet`, and
`SoAnnotation.setName`.

On live objects:

- a timber's `ViewObject.RootNode` is still a reachable `SoSeparator`,
  which is what `view_face_marks` hangs its labels on
- face marks attach, are found again by node name, refresh, and hide
- the joint handle's ViewProvider attaches, reports its `Marker` display
  mode, and takes `Transient` Proxy status
- `Gui::ViewProviderGroupExtension` is added, and the handle draws its
  VarSet as a child — the tree nesting of the 1.1.x GUI rounds
- `marker_position` resolves to `Vector (0, 0, 2438.4)` for an end-B
  datum on a 96 in post — **identical on 1.1.3 and 26.3**, checked on
  both builds

The tree hooks work too: `setupContextMenu` builds all three registered
actions and connects them, `doubleClicked` selects the joint's VarSet,
and the inline XPM in `view_joint_handle` parses to a 16×16 pixmap.

The FreeCAD log for the whole run contains no error, warning, traceback
or deprecation from the workbench — console silent, per rev 2 §5.

## Finding 7 — the suite's 15 failures are two symptom shapes, one cause

Controls first: **1.1.3 on the 7010 runs 123/123 green** on `main` at
`5540942`, in 85.7 s. 26.3 runs the same 123 in 83.9 s with 2 failures
and 13 errors — the brief's count exactly. Every failure below is
therefore 26.3-specific, not pre-existing.

**Shape A — 12 tests die at Apply, with the same `JointError`.**

| Test file | Tests | Message |
|---|---|---|
| `test_frame.FlatFrameTest` | 11 | `Fuse.Tenon.HousedMT.102 leaves T-Beam-101 as 2 solids — the adder does not land inside the stick` |
| `test_apply.ApplyTest` | 1 | `Fuse.Tenon.HousedMT.001 leaves T-Girt-001 as 2 solids` (`test_matrix_every_face_and_end`) |

This is the one-solid assertion in `apply.py` doing its job: the adder
is fused in a frame it no longer shares with the timber, so the timber
comes out as two solids and Apply refuses. Note what this hides — **the
11 `test_frame` tests never reach their own subject**. Seats, bay
respacing, tie-in and the handle nesting are all untested on 26.3, not
failing; they die in fixture setup. Their state is unknown, not bad.

**Shape B — 3 tests survive Apply and measure short.**

| Test | Expected | Got | Short by |
|---|---|---|---|
| `test_measure.test_tenon_past_end_b_and_a` | 100 in | 96 in | 4 in |
| `test_duplicate.test_copies_match_and_are_independent` | 154 | 152 | 2 |
| `test_measure.test_angled_end_long_and_short_point` | — | `TypeError: unsupported operand type(s) for /: 'NoneType' and 'float'` | — |

The first is legible on its own: a 96 in stick with a tenon box spanning
z = 95 → 100 in measures **96 in — the bare design length**. The Fuse
contributed nothing at all, which is finding 2's "`Fuse` gives two
solids, `Cut` silently removes nothing" seen from the measuring end. The
third is the same event one step later: `order_length` returns `None`
where the timber is no longer one solid, and the test divides by it.

## Finding 8 — the flag clears all 15, so there is no second cause

The brief asked for the `measure` failures to be confirmed rather than
assumed. They are confirmed.

A document observer sets `UseLegacyBodyPlacement = True` on every
`PartDesign::Boolean` as it is created, and sweeps restored documents
for the ones the shipped templates carry. No production source changed.

| Run | Result |
|---|---|
| 1.1.3, unmodified | **123/123 OK**, 85.7 s |
| 26.3, unmodified | 2 failures + 13 errors, 83.9 s |
| 26.3, flag forced `True` | **123/123 OK**, 89.4 s |

**221 Booleans were flipped during the run** — that count is also the
measurement of the debt route (a) takes on, since every one of them
would carry the flag permanently. All 221 read `False` before the flip,
confirming the default the brief quotes.

Two facts worth keeping for section 1:

- The property is **present and settable from Python on a freshly
  created `PartDesign::Boolean`**, so route (a) needs nothing more than
  a `hasattr` guard for 1.1.3.
- Nothing else in the suite is 26.3-sensitive. Whatever route section 1
  takes, no other compatibility work is hiding behind these failures.

## Finding 9 — the quantity fields were configured wrongly all along, and 26.3 changed bare-number input

Adam's GUI round on 26.3, 2026-09-21, found two bugs in the dimension
fields. Neither was caught by findings 4–6, which **constructed** every
dialog but never typed into one — caveat 3 below, exactly.

Both live in `_quantity_field`, which drives a `Gui::QuantitySpinBox`
through Qt properties. The widget's own units are inconsistent by
design: **`rawValue` is the raw internal unit (mm), while
`minimum`/`maximum` are doubles read in the *displayed* unit.**

**(a) `minimum`/`maximum` have no correct unit — so we stopped setting
them.** This is ours, and predates 26.3. `ApplyJointDialog` passed a
template's `TenonLengthMin` (50.8 mm) straight into `minimum`; the
widget read it as 50.8 **inches**, so a 4" default sat below that
"minimum" and the first step clamped it up to 50.8 in = **4' 2¾"**,
where it stayed. Adam's number, reproduced exactly.

The fix was not what it first looked like. Converting to the display
unit *does* fix stepping — and then breaks focus-out, because the widget
reads the same property in a different unit there:

| `minimum`/`maximum` passed as | stepping a 4" value | focus-out |
|---|---|---|
| bare float in mm (as shipped) | **`4' 2" + 3/4"`** — read as inches | — |
| a `Base::Quantity` | `5"` ✓ | bound reads back ±DBL_MAX: silently *not applied* |
| float converted to the display unit | `5"` ✓ | **clamps 4" down to 6 mm** — read as raw |
| **not set at all** | `5"` ✓ | untouched ✓ |

So the widget reads the bound in the **displayed** unit when stepping
and as a **raw** value on focus-out; no number is right for both. Both
misreads are on 1.1.3 too. `_set_range` therefore sets nothing, and the
range moved to `ApplyJointDialog._check_ranges`, where the unit is
unambiguous — the guard loses nothing, because it never worked.

**(b) The stepper never commits — a clean 26.3 regression.** This is the
one Adam actually hit in New Timber: the up/down buttons (and Up/Down,
and the wheel) move the *displayed text* but never write it to the
widget's value, so the next focus-out redraws from the stale value. That
is why it "resets to the default" — and why, after he edited a timber's
Dims and copied from it, it reset to *that timber's* dims instead: both
are just the last value `set_literal` wrote.

Stepping 8" up twice, then clicking away, in all seven configurations
(`unit` mm / display unit / unset, `value` as a Quantity,
`quantityString`, `setValue()`, `keyboardTracking` off, `autoNormalize`
off):

| Build | Result |
|---|---|
| 1.1.3 | **holds** in all seven — `rawValue` 203.2 → 254.0 |
| 26.3 | **reverts** in all seven — text says `10"`, `rawValue` never leaves 203.2 |

`interpretText()` and `editingFinished` do not commit it either. Two
things do: re-setting `value` from the shown text, and `userInput()`.
`_StepCommit` (an event filter on the field) takes the first, after
Qt has handled the step. **It tests the value, not the version**, so it
does nothing once the widget agrees with its own text — it retires
itself when upstream fixes this.

**(c) Bare-number input, also 26.3.** Typing `10` into a field showing
`8"` gives 254 mm (10") on 1.1.3 and **10 mm** (redrawn as `3/8"`) on
26.3 — the internal unit, regardless of what is displayed. The same
seven configurations all give 10 mm. Typing `10"` or `10 in` works on
both. Unfixed, and the only one of the three still open.

**(b) and (c) were both already reported, and both are fixed by one
upstream PR** (Adam, 2026-09-21). They were indeed one defect seen from
two sides:

| | upstream | state |
|---|---|---|
| (b) steppers do not commit | [#32717](https://github.com/FreeCAD/FreeCAD/issues/32717) "changing value in quantity spinboxes with arrow buttons broken" | closed by **PR #32707**, Blocker / Regression |
| (c) unitless input read as mm | [#32700](https://github.com/FreeCAD/FreeCAD/issues/32700) "Document units not respected in spinboxes" | closed by the same **PR #32707** |

#32700 names the cause: a regression from PR #30139, "if you type in a
unit in a spin box with no units, it evaluates it to a metric value.
This didn't use to be the case, it would stay the document units."

**A drafted issue for (c) was written and withdrawn** — both defects
were already on file before we got there. Nothing to report; the lesson
is to search upstream before drafting, which cost a round here.

**So `_StepCommit` has an expiry date.** It stays only while the
2026.09.16 weekly is the test environment; it is keyed to the value
rather than the FreeCAD version, so it goes quiet by itself on a fixed
build. **Delete the class, its install in `_quantity_field`, and this
paragraph once Adam is on a weekly carrying #32707** — which also
resolves (c) with no work from us.

The `minimum`/`maximum` inconsistency in (a) is **not** covered by
either, and is not a 26.3 regression at all: it behaves the same on
1.1.3. `_set_range` sidesteps it permanently by not setting bounds, so
there is nothing to wait for and probably nothing worth reporting.

## Finding 10 — Adam's issues 3 and 4 are both finding 2

Neither is new. `Scratch/26.3DevGuiTest.FCStd` shows why:

- `Component001.Placement = <<J-HousedMT-001>>.MatePlacement`, which
  resolves to `<<D_T-Beam-001_B>>.Placement` — the datum's placement
  **local to the beam** — while `Component001` is a Body at the document
  root. That is the whole point of the old operand contract.
- `Body002` (the beam) is placed by `<<Seat_J-HousedMT-001>>.SeatPlacement`,
  and `D_T-Beam-001_B.Station = <<TDim_T-Beam-001>>.LengthZ`.

So editing the beam's `LengthZ` moves the beam (its seat anchors End B
at the post, so it grows the other way) while the adder stays in the
beam-local frame 26.3 no longer resolves it in. The adder is left
"floating a few feet away in the wrong orientation" — Adam's words for
finding 2's "a moved Body no longer intersects its own operand".

It explains the ordering too: **the joint applied cleanly and broke
later**. Apply's one-solid check passed while the beam still sat at
identity, where local and global coincide; the divergence appeared the
moment the beam moved. Issue 3 (End A failing outright) is the same
cause where the timber was already placed.

Nothing to fix here separately. Both close with section 1.

## Finding 11 — on 26.3, `import FreeCAD` deletes names imported before it

`scripts/build_library.py` died on 26.3 with `NameError: name 'Path' is
not defined` — from a function, after `from pathlib import Path` had run
cleanly at module level. It is not a clearing part-way through: the name
never survives the FreeCAD import.

```python
import sys
from pathlib import Path
import FreeCAD as App
print("Path" in globals())     # 26.3: False.  1.1.3: True
```

`import FreeCAD` removes from `__main__`'s globals any name that
collides with one of FreeCAD's own modules — `Path` is FreeCAD's old CAM
workbench — **without raising**. Import FreeCAD *first* and everything
survives, including `Path`. 1.1.3 does not do this.

The failure mode is nasty: no error at import, a `NameError` much later
from whatever function first uses the name. **Rule: in any script that
runs under 26.3, `import FreeCAD` comes before every other import.**
`build_library.py` is fixed that way. Note several test modules still
import `pathlib` before FreeCAD; they are safe today only because they
use `Path` before the FreeCAD import, and are worth reordering.

## Finding 12 — route (a) taken: the suite is green on both builds

Adam's decision, 2026-09-21 (brief section 1): **route (a)**, pin the
operand frame with `UseLegacyBodyPlacement`. Route (b) was measured
first and the brief's sketch of it does not work — see below.

`component.set_legacy_placement` sets the flag on every Boolean the
workbench creates (`apply.py` and `component.apply_boolean`), guarded by
`hasattr` so 1.1.x, where the property does not exist and the old
behaviour is simply what happens, is untouched. One binding choice, not
two mechanisms. `ensure_legacy_placement(doc)` brings an older document
up to the contract and is called at the top of `apply_joint`; it writes
the flag INTO the file rather than fixing it on open, so the document
still opens correctly without the workbench (Tier 1).

| | 1.1.3 | 26.3 |
|---|---|---|
| before | 123/123 | 2 failures + 13 errors |
| after | **123/123** | **123/123** |

Two `test_measure` cases needed the contract in their own Boolean
helper — that test deliberately moves its timber off the origin and
places operands "in the BODY's local frame", so it *is* the contract
under test.

On Adam's `Scratch/26.3DevGuiTest.FCStd`: T-Beam-001 opens as **2
solids** (his issue 4, the detached tenon adder), migrates to **1**, and
stays whole when the beam is lengthened by 2 ft — the edit that broke it.
Issue 3 is the same fix at apply time, covered by
`test_apply.test_matrix_every_face_and_end`, which passes on 26.3 now.

### Why route (b) was not taken

Measured before deciding, so the choice rests on numbers rather than the
brief's expectation. Binding a component **to its own host timber's
`Placement`** — the brief's sketch — is a dependency cycle:
`timber.Shape → Boolean → Component → timber.Placement`. It is a cycle
on **both** builds (`getOutListRecursive(): cyclic dependency
detected!`), with the Body left invalid on 26.3 and the accessor frozen.
Finding 1's property-level expression edges do **not** rescue it. The
brief's "`Seat_J-…` is the existing proof it works" does not carry: a
seat places a *different* timber, not the one the component is
booleaned into.

Binding instead to whatever **drives** the timber's placement (the
anchor or the seat, never the timber) does work — no cycle, one solid,
zero errors, and the cut follows the timber — so route (b) has a viable
shape when it is wanted. But the cut volume differs between builds at
the same position, i.e. the geometry is version-specific, so route (b)
means making 26.3 the minimum. That is a decision for after the GUI
round, not before it.

## What this does not prove

1. **Rendering is unverified.** The scene graphs *build and attach*;
   whether the billboard faces the camera, screen-scales, and stays
   legible through timber is visual and needs Adam's GUI round. A probe
   cannot see a marker.
2. **Apply Timber Joint's GUI path is unexercised.** Its dialog
   constructs (81 widgets), but the command is inactive without paired
   datums and the operation is blocked by the Boolean operand change of
   finding 2. This is the largest remaining GUI unknown, and it unblocks
   with section 1's decision, not with more probing.
3. **Only two commands were actually run.** The other eight open modal
   dialogs, which a scripted probe cannot drive without blocking.
   Construction is proven; the accept path through each is not.
4. **The 11 `test_frame` behaviours are untested on 26.3, not passing.**
   They die in fixture setup (finding 7). They pass under the forced
   flag, which is good evidence, but the flat frame's seats have not
   been exercised against 26.3's *own* operand semantics.
5. **The flag experiment is not a decision.** It measures route (a)'s
   cost (221 objects) and proves the failures have one cause. Route (b)
   — binding components globally through a `Seat_J-…`-shaped placement
   object — is untouched here and remains section 1's call.
