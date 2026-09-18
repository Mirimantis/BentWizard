# Brief: headless spike round 2 — `copyObject` as the instancing mechanism

**For:** Claude Code, working in the BentWizard repo.
**Deliverable:** `tests/spike/spike_copyobject.py` (reusing helpers from round 1 where sensible), producing `docs/spike-copyobject-results.md` **and** leaving inspectable `.FCStd` fixtures in `scratch/` (see *Artifacts*).

## Why round 2

Round 1 (`docs/spike-variant-link-results.md`) established that `App::Link` copy-on-change works: parameters materialize a local copy, expression-bound parameter groups propagate, `PartDesign::Boolean` accepts a Link directly (C1), and 150 instances recompute in ~2.6 s.

But every ergonomic cost in that report traces to the link machinery rather than to instancing itself:

- parameters must live on the linked object, so a cutter's sketches reach them through `href()` — dependency edge severed, expression autocomplete disabled;
- the `CopyOnChange` property status cannot be set from the Add-property dialog, so hand-authoring a template requires the Python console, which breaks the "no programming to add a joint" requirement;
- three open upstream issues sit in the path (#24715, #13481, #30124);
- and the one thing a link buys over a copy — a live connection to the template — is exactly what FEP-0010 says cannot be used, since template revision cannot be pushed into instances without discarding their per-instance parameters.

If instances are independent anyway, a **deep copy** may deliver the same result with none of that. `doc.copyObject(source, True)` duplicates an object and its dependencies, remapping internal expressions to the copies. This is the API form of the manual duplication ritual proven in Phase 0.

**The question this spike answers:** does `copyObject` produce a clean, independent, fully parametric joint instance — and does it remap expressions correctly?

That last clause is the crux. Phase 0 findings #2 and #12 record the GUI's duplicate command auto-including dependencies and leaving expressions pointed at the source (a duplicated timber whose sketch still referenced the original's VarSet; phantom features carried into a copy and invisible because they cut nothing). **Assume nothing about the API version's behaviour; measure it.**

## Environment

Portable FreeCAD 1.1.1 adjacent to the repo. Run as `freecadcmd.exe tests/spike/spike_copyobject.py`. Build all fixtures programmatically. Support `BW_SPIKE_WORKDIR` and `BW_SPIKE_SCALE` as in round 1.

## Template under test

Use the **A-bis structure** — the one round 1 had to set aside because links cannot reach a child VarSet:

- an `App::Part` container, holding as siblings:
  - a VarSet labelled `JointParams` with the eight Length properties in group `Joint`, UpperCamelCase (`MortiseThickness`, `MortiseWidth`, `MortiseDepth`, `HousingDepth`, `HousingWidth`, `HousingHeight`, `SetbackFace1`, `SetbackFace2`), each with a tooltip;
  - a `PartDesign::Body` labelled `Cutter` whose two pads are driven by plain `<<JointParams>>.X` expressions — **no `href()` anywhere**.

Assert as a precondition that the built template contains zero `href(` in any expression. If `href` is needed, that is a finding and the premise of round 2 is wrong.

## Required tests

Record PASS/FAIL plus observed values for each. Catch exceptions and record them as data. Note explicitly wherever a forced recompute (`doc.recompute(None, True, True)`) was needed — round 1 found inconsistent recompute behaviour and it is a live concern.

### T1 — Copy fidelity and expression remapping (the gate)

`copyObject` the template Part into a target document. Then:

- Enumerate every object in the copy and every expression in each. Assert **no expression references the source document or any source object**. Report the full expression list in the results file — this is the finding Phase 0 was burned by.
- Assert the copy's VarSet is a distinct object from the source's.
- Change a parameter on the **copy's** VarSet: geometry updates, source document untouched.
- Change a parameter on the **source's** VarSet: the copy does not move.
- Report the object count per instance and compare against round 1's ~29 objects per variant-link instance.
- Report whether `copyObject` brings the App::Part's Origin, and whether the copied Body sits at zero placement inside its Part (a hidden offset here is the Phase 0 stray-8-inches failure mode).

**T1 is the gate.** If expressions do not remap cleanly, record exactly how they fail and what post-processing would be required, then continue — a copy needing deterministic fixup is still a viable mechanism and the cost should be quantified.

### T2 — Two instances, independence, and expression-driven groups

Copy the template twice into one target document. Give each a different `MortiseThickness`. Assert independence in both directions.

Then create a `Group_Test` VarSet in the target and bind both copies' `MortiseThickness` to `<<Group_Test>>.MortiseThickness`. Change the group value, recompute.

Assert: both instances follow the group; per-instance override (replace one binding with a literal) leaves the sibling alone; bindings survive save/reload; record whether a forced recompute was needed at each step.

This mirrors round 1's T2 exactly so the two mechanisms are directly comparable.

### T3 — Boolean bridge

Using round 1's finding that **C1 (`PartDesign::Boolean` referencing the instance directly) is the better bridge**, cut a copied cutter into a `PartDesign::Body` timber.

Note the structural difference from round 1: the operand is now a copied `App::Part` containing a Body, not a Link. Determine what `PartDesign::Boolean` will actually accept — the Part, the Body inside it, or a binder — and record which. Also test C3 (`Part::Cut`) as a fallback.

For each bridge that constructs: correct volume against an analytic expectation; updates on a parameter change; timber remains independently editable; resulting top-level object type.

### T4 — Persistence and relocation

Save, close, reopen in a fresh session: overrides persist, volumes identical. Then move the target document alone to a different directory and reopen. Since a copy has no external dependency, assert the target opens with **no reference to the source document at all** — no `does not exist!` log line, no second document loaded. Round 1's equivalent left a dangling `LinkCopyOnChangeSource`; a copy should be strictly cleaner.

### T5 — Scale

10, 50 and 150 instances with the winning bridge. Record build time, file size, object count, full recompute time, and single-group-parameter-change recompute time at each count. Present these **side by side with round 1's numbers** in the results file.

### T6 — Downstream smoke test

As round 1's T6: TechDraw page, projection group, one dimension; change a parameter; assert nothing raises and states return to Up-to-date. Also record whether the `hasher mismatch` console warnings seen throughout round 1 appear here — if they are absent with copies, that is a meaningful difference given this project's history with topological naming.

## Artifacts

Save inspectable fixtures to `scratch/` in the repo (create it and add to `.gitignore` if not already ignored). At minimum:

- `scratch/r2_template.FCStd` — the A-bis template as built.
- `scratch/r2_two_instances.FCStd` — the T2 document: two copies, group VarSet, bindings live.
- `scratch/r2_cut_timber.FCStd` — the T3 document with the winning bridge applied.
- `scratch/r2_scale_150.FCStd` — the T5 150-instance document.

Do not delete these at the end of the run. State their paths in the results file. They will be opened and inspected in the GUI.

## Report

Write `docs/spike-copyobject-results.md` with the same shape as round 1: results table, per-test observations, and a direct **comparison table against round 1** covering at least — href required, autocomplete available, Python needed to author a template, open upstream bugs in the path, objects per instance, recompute time at 150, group propagation, template-revision propagation, and external dependency after delivery.

End with a recommendation naming the mechanism to adopt: **copyObject**, **variant links**, or **neither** — and, if `copyObject` wins, a short list of what the apply-joint tool must still do that instancing does not cover (mated pairs, mate frames, placement, naming, the stick-allowance contract).

## Constraints

- Do not modify `apply_joint.py` or any production module. Evaluation only.
- A headless PASS is a candidate, not a proof. Flag everything needing GUI confirmation.
- Report negative results as findings. If `copyObject` is worse, say so plainly — round 1's mechanism is already validated and remains available.
