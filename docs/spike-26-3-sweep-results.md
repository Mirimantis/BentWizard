# 26.3 sweep — expression engine, datums, Assembly (brief section 3)

Taken 2026-09-23 on `main` at `d4a3b8c`, on the 7010. **26.3** is the
weekly `2026.09.16` (26.3.0, git `a4ce44d33b`; it reports itself as
`20260916 (Git shallow)`), with fine-grained recomputes at their default
(on) unless a row says otherwise. **1.1.3** is the comparison build
(git `20260725`). Each harness runs the same checks on both builds. A
result that differs between them is a 26.3 change. A result that is the
same on both is either a guarantee that still holds or an older defect.

Harnesses (bundled python; they print their results):

- `tests/spike/spike_expression_engine.py [on|off]` — E1–E12. The
  argument forces the fine-grained preference for the run and restores
  it afterwards.
- `tests/spike/spike_datums.py` — D1–D3.

Numbering continues from findings 13–16 in
[spike-fine-grained-recompute-results.md](spike-fine-grained-recompute-results.md).

## Summary

| # | Item | 26.3 vs 1.1.3 | Consequence |
|---|---|---|---|
| 17 | Seat arithmetic, `<<Label>>` resolution, relabel, cross-document copy | **unchanged** | none |
| 18 | A quote in a label is stored escaped (`\'`) | same on both: **an existing BentWizard bug** | New Timber refused `'` and `"`; **fixed** |
| 19 | Cycle check | **still per object** | seat VarSet and "datums never read each other" stay |
| 20 | Finding #15 (undo breaks expression dependencies) | **hidden by fine-grained, still there** | `undo_repair` stays |
| 21 | `getGlobalPlacement` | **deprecated 26.3, removed 27.2** | 6 call sites; **migrated** |
| 22 | LCS datums, and child axes filed under the wrong object | **unchanged** | the scope rule stays |
| 23 | Assembly markers drawn offset in a moved assembly | **fixed upstream in the weekly** | Phase 2 export only |

Everything the seats and joints rest on held. Nothing moved under
BentWizard's geometry. What turned up is one real bug (18, older than
26.3), one deadline (21), and one guard that has to stay even though it
looks unneeded (20).

## Finding 17 — the expression contract the seats rest on is unchanged

Every check below is compared against a value computed in Python. An
engine drift therefore cannot pass by agreeing with itself. All checks
give identical results on both builds.

| check | result |
|---|---|
| E1 `minvert(p)` | `== p.inverse()` |
| E2 `a * b * c` on placements | `== a.multiply(b).multiply(c)`, left to right |
| E3 `frame.FLIP_EXPR` | exactly 180° about Y; a bare angle is degrees (`90` == `90 deg`) |
| E4 `<<Datum>>.Placement` inside a moved Body | the datum's **local** placement, not its global one |
| E5 `frame.seat`'s whole expression | seats exactly: misfit 0.0 mm, 0.0° |
| E6 `<<Label>>.Prop` with `. ' " < << Ø 柱 ( ) + # $ = ,` and leading digits | all 14 labels resolve |
| E7 relabel a datum, then the seat | both references are rewritten to the new label, and the seat holds |
| E8 cross-document `copyObject` | a copied VarSet keeps `<<J-Kind-000>>`; an uncopied datum becomes the bare `D_Template_EndB.Wd`, which is the form `apply._substitute` already matches |
| E9 `ExpressionEngine` paths | `Length`, `Placement`, `.Placement.Base.z`: the leading dot is kept exactly as the code expects and strips |
| E10 `App::PropertyLength` | a negative literal clamps to 0, an expression does not (the CLAUDE.md gotcha holds) |

Two things came up while building the harness. Neither is a 26.3 change:

- **A property or object named with a unit symbol cannot be
  referenced.** `PV.A` and `<<Src>>.A` fail to parse (`A` is the ampere).
  So do `J` (joule) and `W` (watt), and presumably every other symbol:
  `m`, `N`, `V`, `C`, `K`, `T`, `H`, `F`, `s`, `h`, `g`. BentWizard's own
  names are safe: all are several letters, and objects are referenced
  by `<<Label>>`. But a single capital letter passes the template bar's
  UpperCamelCase rule, so a template author could name a parameter `W`
  and get an unreadable parameter. **Suggested:** the template bar
  should reject parameter names that parse as a unit.
  **Done 2026-09-23.** The exact set was taken from the lexer's tokens
  (`src/App/Expression.l`) and confirmed on both builds: 37 names. They
  are 34 unit symbols, `M` and `AS` (arcminute and arcsecond), and
  `True`/`False`/`None`. `Nmm` is a lexer token but resolves as a
  property, so it is not in the set. Cell-like names (`A1`) are fine.
  - The set is `naming.EXPRESSION_WORDS`.
  - The strict lint rule `property-expression-word` flags any VarSet or
    datum property with one of these names. The template bar reports it
    and, by design, does not block the save.
  - Store in Variable Set refuses such a name.
  - `test_linter.ExpressionWordsAgainstTheEngine` re-checks the whole
    set against the build in hand, so a lexer change in a weekly shows
    up there.
- `,` is accepted as an argument separator as well as `;`.
  `FLIP_EXPR`'s `;` is the locale-proof spelling, so nothing changes.

## Finding 18 — a quote in a label breaks every textual match (both builds)

FreeCAD evaluates `<<T-Post'1'>>.L` correctly (E6), but **stores** it as
`<<T-Post\'1\'>>.L`, and likewise escapes `"`. BentWizard finds its
bindings by matching text. It does this in `timber._DIMS_BINDING`, in
the `f"<<{label}>>" in expr` tests in `datums.host_datum`,
`frame.seat_driving`, `apply` and `duplicate`, in `fcstd._LABEL_REF`,
and in the linter. None of these finds an escaped label. The first to
bite is `timber.dims_varset`, so **New Timber refuses any label with a
quote**, and its error message is misleading:

    "T-Tie 'x'-001" is not a timber (no Dims VarSet drives its base pad)

The behaviour is identical on 1.1.3, so the bug is BentWizard's, not a
26.3 regression. `naming.py`'s note that quotes "survive the
`<<Label>>.Prop` expression round trip" is true for evaluation but
false for the stored text. A framer is likely to write one: `8"x8"`, or
`12'` for a length.

Two ways to fix it; this sweep builds neither:

- **(a)** Add `'` and `"` to `RESERVED_LABEL_CHARS`. This is one line,
  but it blocks the inch and foot marks.
- **(b)** Add one `naming.label_ref(label)` that returns the stored
  (escaped) form, and route every place that builds or matches a
  reference through it. `\` is already reserved, so escaping is only
  `'` → `\'` and `"` → `\"`.

(b) is the right fix. It touches every module listed above, so it
belongs in its own change with its own tests.

**Fixed 2026-09-23, route (b).** `naming` now has `label_ref` (the
stored form), `quote_label` (the same, without the brackets, for
`facetable`'s row templates), `LABEL_REF`, `unquote_label` and
`referenced_labels`, all mirroring `App::quote`. Every site that
*matches* stored text goes through them: `timber.dims_varset`,
`fcstd.expression_refs` (which also missed labels containing `<`),
`facetable`'s expected datum expressions (`verify_datum` and the
linter's `datum-declaration` compare against them),
`datums.host_datum`, `frame.seat_driving`, `apply`'s
`joint_members`/`_substitute`/`_redirect_accessors`, `duplicate`'s
renames and `commands._portable`.

Sites that only *build* an expression still write the plain label. The
parser accepts both forms and stores the escaped one; verified that the
escaped form round-trips unchanged.

`tests/test_label_quoting.py` covers the whole path with `T-Post
8"x8"-001` and `T-Girt 6'-001`: New Timber, Apply, seating, the linter
on the saved file, Duplicate re-pointing a parameter bound to the girt's
Dims, Remove, and a joint and seat renamed with quotes. Each fixed module
was reverted in turn to confirm a test fails without its fix; the
exception is `commands.py`, which is GUI-only. E6 now asserts the stored
text equals `naming.label_ref`, so it is the tripwire if FreeCAD ever
changes its quoting.

`;` also resolves in a reference (E6). Its reservation is for Tier-2
record strings, not expressions, so that stays as it is.

## Finding 19 — the cycle check is still per object

26.3 recomputes per property (finding 1), but it still **refuses** any
link that would close a cycle between two objects, even when the
properties involved are disjoint:

| E12 | 26.3 (on) | 26.3 (off) and 1.1.3 |
|---|---|---|
| `VsOne.PropX ← VsTwo.PropY`, `VsTwo.PropX ← VsOne.PropY` | refused: `cyclic reference to E12a#VsOne.PropY` | refused: `…#VsOne` |
| a joint VarSet's seat reads a timber whose pad reads that VarSet | refused: `…#Body.Placement` | refused: `…#Body` |
| two datums read each other's `WidthU` | refused: `…#D_T_A_001_B.WidthU` | refused |

Only the message changed: 26.3 now names the property. This design
still depends on the per-object check:
- **The seat stays on its own VarSet** (`frame.py`'s module docstring).
- **A joint's accessors stay off its datums.**
- **"Datums never read each other" stays a rule.**

Fine-grained recomputes change what gets *recomputed*. They do not
change what is *allowed*.

## Finding 20 — finding #15 is hidden by fine-grained recomputes, not fixed

Finding #15: undoing a deletion restores an object's expressions but
not the dependencies behind them, which leaves a "fossil". Tested
without `undo_repair` installed:

| E11 | 26.3 on | 26.3 off | 1.1.3 |
|---|---|---|---|
| a Follower box bound to a Driver box; delete both, undo (#15's own repro) | live | live | live |
| delete the Follower only, undo | live | live | live |
| **undo Remove Timber Joint, then edit `HousingDepth`** | **live** | **fossil** | **fossil** |

With fine-grained recomputes on, an undone Remove Timber Joint comes
back parametric by itself. Turn the preference off and the fossil
returns, on the same build. The preference is the user's to change, so
**`undo_repair` stays.** It is keyed to behaviour: re-arming a live
binding writes back the same expression, and costs one recompute. It
can be deleted when E11's last row is live with fine-grained **off**,
or when 26.3 drops the preference.

Two corrections to the record:
- **#15's two-box repro no longer reproduces on either build.** Only
  the real Remove-and-undo case does. `tests/test_undo_repair.py` pins
  the repair on the Remove case, which does reproduce (1.1.3, and 26.3
  with the preference off).
- **There is no test asserting the defect**, although
  `phase0-friction-findings.md` #15 says "the test asserting the defect
  is the tripwire". E11 is now that tripwire. It lives in a spike,
  because the answer depends on a user preference.

## Finding 21 — `getGlobalPlacement` is deprecated, and it is the only deprecated API BentWizard uses

26.3 deprecates `App.GeoFeature.getGlobalPlacement` ("does not handle
Links correctly") and **removes it in 27.2**. Its replacement is
`getGlobalPlacementOf(target, root, subname)`. Python hides a
`DeprecationWarning` raised inside a module by default, which is why the
suite never showed it.

The sweep checked two ways that nothing else is affected:
1. **The suite on 26.3 with all deprecation warnings on**
   (`-W always::DeprecationWarning`): 128 tests OK, and the only warning
   is this one.
2. **Every `@deprecated` and `@deprecated_attributes` in upstream's
   `.pyi` stubs** (all tagged 26.3 → 27.2), grepped against the repo.
   The list covers the Gui workbench `Append*`/`Remove*`/`List*`
   capitalised forms, `Gui.show`/`hide`, `SendMsgToActiveView`,
   `MDIView.message`, `add/removeEventCallbackSWIG`, Sketcher's
   `ExposeInternalGeometry`/`DeleteUnusedInternalGeometry`, Part's
   `open`/`insert`/`multiFuse`/`makeOffset`/`Face.Wire`/`Conic.Center`,
   and Material's property dictionaries. BentWizard uses none of them.
   This check covers the GUI code, which the suite does not reach.

Call sites: `datums.seat_target`, `seat_delta` and `misfit` (3),
`duplicate.py:189` (1) and `joint_handle.marker_position` (2), plus
tests. For a datum, D3 shows that
`getGlobalPlacementOf(d, body, d.Name + ".")` equals the old product of
GeoFeatureGroup placements. So does
`getGlobalPlacementOf(d, frame, "Bent.Body.D.")`: a subname path through
Std Groups resolves. And for a datum it all equals
`body.Placement * d.Placement`. `getGlobalPlacementOf(d, d, "")` returns
the *local* placement, so a one-argument rename would be wrong.
**Suggested:** one `global_placement(obj)` helper that walks
`getParentGeoFeatureGroup()`, used at all six sites. There is time
before 27.2, but the change is small.

**Migrated 2026-09-23.** `datums.global_placement(obj)` builds the root
and subname from the GeoFeatureGroup chain and calls
`getGlobalPlacementOf`. It replaces the method at all six sites, in the
tests, and in `spike_expression_seat.py`. (`spike_flat_frame.py` is
historical and does not run, so it is left alone.) New tests cover:
- a datum in a moved timber inside the frame's Std Groups;
- a two-level App::Part → Body → LCS chain;
- `joint_handle.marker_position`, which the suite did not reach before.

The suite passes with `-W error::DeprecationWarning`, so no call
remains in anything it reaches.

## Finding 22 — datums are unchanged, including the child-axis scope hazard

D1: `Part::LocalCoordinateSystem`, `MapMode` `Deactivated`, the same
property list, and the same seven children (`App::Line` ×3,
`App::Plane` ×3, `App::Point`, each with its `Role`) on both builds.
`verify_datum` is clean.

D2 rebuilds the setup behind Adam's second GUI round. A component Body
whose `Placement` reads `<<D_…>>.Placement` directly:

| component | datum `InList` | datum's children filed under |
|---|---|---|
| free, direct binding | `Body, Comp` | `Body` |
| **claimed by a Cut in the timber, direct binding** | `Comp, Body` | **`Comp`** — the wrong object |
| claimed by a Cut, through an accessor VarSet (production) | `Acc, Body` | `Body` |

Creation order makes no difference. On both builds, the Boolean claim
puts the component first in the datum's `InList`, and FreeCAD files the
children under the first GeoFeatureGroup it finds there. That is the
mechanism CLAUDE.md records. Headless, nothing goes Invalid. The
out-of-scope *message* appeared only in the GUI, but the misfiling that
causes it reproduces exactly. **The scope rule and the accessor VarSet
stay.**

## Finding 23 — the Assembly marker bug is fixed upstream, in the weekly

This is the bug that started the flat frame: a Fixed-joint marker drawn
at twice a moved sub-assembly's shift (flat-frame finding 1, same class
as #17398). Upstream filed it as
[#27345](https://github.com/FreeCAD/FreeCAD/issues/27345), "JCSs
displayed with offset if assembly has non-default placement". It was
fixed by [#28089](https://github.com/FreeCAD/FreeCAD/pull/28089)
(merged to `main` 2026-03-06). The fix adds `setJCSPosition` to
`JointObject.py`, which draws the marker relative to its assembly's own
global placement. That method is in the weekly and absent from 1.1.3.
`SoSwitchMarker.set_marker_placement` itself is unchanged.

**Established from the source, not measured.** A marker is Coin
rendering, and this sweep did not draw one. It matters only for the
Phase 2 export to a native Assembly. That export should check the
marker in the GUI when it is built, not before.
[#31083](https://github.com/FreeCAD/FreeCAD/issues/31083) (dragging
under a non-identity assembly Placement) is still open. That does not
matter here: timbers are never dragged.

## What this does not prove

- **GUI rendering and GUI-only recompute ordering.** Headless is a
  filter, not an oracle (CLAUDE.md). Adam's GUI round covers these.
- **The fixes for findings 18 and 21 are built.** The rest of the
  brief's list (the unit-symbol lint) is not.
