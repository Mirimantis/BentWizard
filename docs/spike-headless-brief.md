# Brief: headless variant-link spike harness

**For:** Claude Code, working in the BentWizard repo.
**Deliverable:** `tests/spike/spike_variant_link.py` (plus helpers), runnable under `FreeCADCmd`, producing a written results table and a go / partial-go / no-go recommendation in `docs/spike-variant-link-results.md`.

## Background

BentWizard currently applies joints with a hand-rolled rebuild engine (`apply_joint.py`, ~1400 lines) that reads a template as a spec and reconstructs its geometry on the target timber. We are evaluating whether FreeCAD's native instancing — `App::Link` with copy-on-change, plus a boolean bridge — can replace it.

Manual GUI testing so far established:

1. Custom properties on a `PartDesign::Body` can drive that body's own sketches, but only via `href()`, which severs the dependency edge and disables expression autocomplete.
2. An alternative structure (an `App::Part` container holding a VarSet and the Body as siblings) avoids `href()` — but a Link exposes only the linked object's *own* properties, so a link to the Part cannot reach a child VarSet. Parameters must live on the linked object itself.
3. Making a plain link and then setting `LinkCopyOnChange` to Enabled **or** Owned did not materialize a copy: `LinkCopyOnChangeGroup` stayed None and edits wrote back into the source document.
4. The likely cause, from upstream docs: the source property must carry the **`CopyOnChange` property status**, and the override must be made on the **Link's** dynamic property, not by drilling into the linked object.

Relevant upstream issues to be aware of (do not assume they are fixed; detect their symptoms):
- FreeCAD #24715 — confirmed: SubShapeBinder copy-on-change variant not updating with changed custom properties, in a Part+VarSet+href configuration very close to ours.
- FreeCAD #13481 — links set to Owned inside an `App::Part` raise CopyOnChangeGroup scope errors.
- FreeCAD #30124 — CopyOnChange properties disappear permanently if a binder is switched to Detached.
- FreeCAD #19182 — invalid edge-link exceptions after switching configurations on variant links.
- FEP-0010 (Variant Parts) states that copy-on-change links maintain a hidden copy, rely on hidden references, and cannot propagate a change to all instances without first converting to regular links, which discards per-instance parameterization.

## Environment

Portable FreeCAD 1.1.1 lives adjacent to the repo (path from local config; do not commit the FreeCAD folder). Run scripts as `FreeCADCmd.exe path/to/script.py`. Build all fixtures programmatically — do not depend on the manually authored spike FCStd files, though `tests/fixtures/` copies may be used for cross-checking.

## Required tests

Each test: construct fixtures from scratch, run, assert, record PASS/FAIL plus the observed values. Catch exceptions and record them as data rather than aborting the run. Recompute explicitly (`doc.recompute()`) and, where relevant, record whether a result required a forced recompute — that distinction matters.

### T1 — CopyOnChange materialization
Build a cutter Body with eight Length properties in group `Joint`, UpperCamelCase names, driving two pads via `href()`. Mark every property `CopyOnChange` with `setPropertyStatus`. In a second document, build a plain 8x8x96 timber, create an `App::Link` to the cutter, set `LinkCopyOnChange`, override a parameter **on the Link**.

Assert: the Link gains dynamic properties for the flagged parameters; `LinkCopyOnChangeGroup` is populated after the override; the source document's property is unchanged; the link's shape reflects the override. Record which `LinkCopyOnChange` value (Enabled / Owned / Tracking) produces which behavior — test all three.

**T1 is the gate. If it fails in all modes, record the failure precisely and skip to the report.**

### T2 — Expression-driven group propagation
This decides whether the layered-parameter-groups architecture survives. In the target document create a `Group_Test` VarSet. Bind a Link's dynamic property to `<<Group_Test>>.MortiseThickness` by expression. Create a second link bound the same way. Change the group value, recompute.

Assert: both links' geometry updates. Record whether the copies re-materialize, whether the binding survives save/reload, and whether a forced recompute was needed.

### T3 — Boolean bridge
With a working link from T1, attempt all three bridges against a `PartDesign::Body` timber. Try **C2 first**.
- C2: `PartDesign::SubShapeBinder` referencing the link, then a subtractive `PartDesign::Boolean`.
- C1: `PartDesign::Boolean` referencing the Link directly (expected to fail — Boolean takes Bodies; confirm and record).
- C3: `Part::Cut` of timber minus link.

For each: does it construct; is the resulting volume correct (compute expected volume analytically and compare with tolerance); after changing a link parameter and recomputing, does the cut update; is the timber Body still independently editable (change a sketch constraint, recompute, assert the shape changed); what is the resulting top-level object type and `TypeId`.

### T4 — Persistence and round trip
Save, close, reopen in a fresh session. Assert overrides persist, geometry recomputes identically (compare volumes), links resolve. Then relocate both files to a different directory and reopen the target — record whether links resolve by relative path, absolute path, or fail.

### T5 — Scale
Instantiate 10, 50, and 150 links with the winning bridge. Record full-recompute wall time at each count, saved file size, and whether time grows non-linearly. Also record parameter-change recompute time (change one group value, time the recompute) at 150.

### T6 — Downstream (best effort, headless)
Create a TechDraw page with a projection group of a cut timber and one dimension; change a link parameter; assert the view and dimension still compute without error. Record any exception text. Note in the report that visual correctness and Assembly behavior require GUI confirmation and are out of scope here.

## Report

Write `docs/spike-variant-link-results.md`:
- A results table: test, PASS/FAIL/PARTIAL, observed values, exceptions.
- Which `LinkCopyOnChange` mode and which boolean bridge won, if any.
- An explicit recommendation:
  - **Go** — T1 and T2 pass, a bridge preserves both the cut and native editability, T4 passes, T5 acceptable at 150.
  - **Partial go** — mechanism works but a downstream layer needs adapting (e.g. C3 wins and the object type changes, requiring updates to the linter, cut-list walker, and TechDraw batch). Name the affected modules.
  - **No go** — no bridge preserves both properties, or T2 fails. If T2 fails, state plainly that layered parameter groups cannot be built on this mechanism and the rebuild engine stays.
- A short section on which findings need GUI confirmation before acting.

Keep the harness in the repo as a regression test regardless of outcome — three of the upstream issues above are open, and behavior may change under a FreeCAD update.

## Constraints

- Do not modify `apply_joint.py` or any production module during this spike. It is an evaluation only; the decision comes after the report.
- Headless recompute triggers differ from GUI ones. A headless PASS is a candidate, not a proof; say so in the report.
- Report negative results as findings, not failures to work around. A documented no-go retires the question and is a successful outcome.
