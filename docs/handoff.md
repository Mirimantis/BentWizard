# Session handoff

Living pointer for a fresh session. Read after CLAUDE.md and the rev-2
workflow doc. Update it as work lands.

## Where things stand (September 2026)

The rev-2 foundation is built on branch `claude/rev2-datums`, headless
suite green (108+ tests), **awaiting Adam's GUI round before commit**
(the project rule: nothing lands untested). The rev-1 code is gone:
`apply_joint.py`, `span.py`, the parity tables, `Stick_Allowance_*`, the
companion `Layout_` VarSet, `Template_Handed`, Preview Mated Joint,
Drive Length from Layout Distance, the dovetail template.

What to GUI-test, in order (each step is a command on the BentWizard
toolbar):

1. **New Timber** — a centred stick with `WidthX/WidthY/LengthZ` and two
   end datums in the tree. **Show Face & End Marks** should read ±X/±Y
   and A/B on it. Edit `WidthY` in the Dims VarSet: the section and the
   datums follow.
2. **Add Datum** on each face at a station; then bind a station to a
   project variable via the ƒx field and edit the variable.
3. **Apply Timber Joint** with `Joint_HousedMT` between a post and a
   girt on each face and at both ends of the girt (Assemble now on):
   the girt seats, the post shows the housing and mortise, the girt the
   shoulder and tenon; the handle marker sits on the post's datum; the
   joint files under `TimberJoints_Bent-001`. Edit `TenonLength`,
   `HousingDepth`, the host datum's `Station`, the girt's `WidthX` — the
   right things move and nothing else does. **Audit Timbers** reads
   design vs order length and "one solid" throughout.
4. **Remove Timber Joint** from the handle's context menu: the timbers
   return to bare sticks, the datums stay unpaired, Undo brings the
   joint back live (edit a parameter afterwards).
5. A π bent (two posts, a beam at end A/B) and a second one via
   **Duplicate Timbers** with an offset; a tie between the bents makes
   the frame. Edit the beam's `LengthZ`: does the bent re-solve on a
   plain recompute in the GUI? (Headless it needs an explicit solve —
   the assembly stays `Touched`; the roadmap says the GUI re-solves.)
6. **New Joint Template** from `Joint_Butt`, author a component in the
   GUI per the report window's guide, **Save as Joint Template**, apply
   it. This is the "a framer can author a joint without Python" claim.

**First GUI round (Adam, 2026-09-18):** New Timber and Apply
`Joint_HousedMT` worked; afterwards most of the UI was greyed out as if a
task were open, with an "Access violation" in the report view. Cause:
Apply opened the template with `openDocument(hidden=True)`, which steals
the active document, and closing it left none. Fixed by
`template_library.open_hidden` (restores the active document); verified
by a scripted GUI session through Apply, the template geometry check,
Undo and Redo. Still to confirm in Adam's GUI: that the access violation
is gone with it (the scripted session never produced one). Known noise:
Undo of an Apply prints two `getOverlayIcons` tracebacks from FreeCAD's
own `JointObject.py` — not ours, harmless.

**Second GUI round (Adam, 2026-09-18):** four findings, all fixed
before commit. (1) Apply did not take the selection: now the first
selected timber fills Primary (host), the second Secondary (mate).
(2) The role rows said Post/Girt: now *Primary — passing* / *Secondary —
butting*, read from where the template put each datum. (3) Remove left
the timbers invisible: features added from Python leave the previous
Tip visible and a removed Tip leaves nothing shown — `apply.show_tip`
fixes the view after Apply and Remove. (4) Editing a girt's `WidthX`
raised `Link(s) to object(s) 'XZ_Plane005 …' go out of the allowed
scope 'D_T_Beam_001_B'`: FreeCAD files a datum's child axes under the
first GeoFeatureGroup in the datum's in-list, and a component Body
whose Placement read the datum could come first. Components now bind
to the joint VarSet's `HostPlacement`/`MatePlacement`; the linter's
`component-placement-direct` rule guards it; the library is rebuilt.
Verified by a scripted GUI session (visibility after Apply and Remove,
the width edit recomputing clean).

Things that could only show up in the GUI: recompute ordering
(`Tool shape is null` was a GUI-only failure in the spikes), the
tree's rendering of the handle's group extension, whether the
mirroring's loose source body at root is tolerable in the tree.

## Architecture cheat-sheet (why the code is shaped this way)

- **Datums belong to timbers; a joint is applied to them.** Every datum
  is placed from `facetable.FACE_TABLE`, Z out of the material, so a
  cutter modelled in −Z and an adder in +Z work on every face and end
  with no parity correction. Pairing is two strings (`MateDatum`,
  `Joint`); the cross-timber accessors sit on the joint VarSet because
  two datums reading each other is a dependency cycle.
- **Copy, don't rebuild.** `apply.py` copies the template's VarSet and
  component bodies with `copyObject(objs, False)`, re-points the datum
  references (both `<<Label>>` and the bare form a cross-document copy
  leaves), mirrors on parity, Booleans in `ComponentOrder`, and refuses
  unless every timber is still one solid.
- **Pre-position, then solve.** `assemble.assimilate_joint` moves the
  free side to `datums.seat_delta` before the first recompute with the
  joint present; MbD otherwise rotated the grounded post.
- **Structural, never label-matched.** Dims from the stick pad's
  `LengthZ` binding; joint members from the `<<J-…>>` token anchored on
  component bodies; handles by their links; Fixed joints by the datum
  names they reference.
- **GUI-free cores.** `timber`, `datums`, `apply`, `assemble`,
  `duplicate`, `measure`, `template_check` have no Qt; `commands.py` is
  thin wrappers. Tests drive the cores headless.

## Running things

- Tests: `C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe -m unittest discover -s tests`
- Lint a file: `... python.exe -m freecad.bentwizard.linter <file.FCStd>`
- Rebuild the shipped library: `... python.exe scripts/build_library.py`
  (writes `library/Joint_Butt.FCStd` and `library/Joint_HousedMT.FCStd`
  and runs the template bar on both)
- Headless scripting: `freecadcmd.exe <script.py>` swallows `print`;
  prefer the bundled `python.exe`, and front-load `<repo>/freecad` on
  `freecad.__path__` (`tests/_repo_path.py`) so the checkout wins over
  the `Mod` junction.
- The workbench is dev-installed via the junction at
  `%APPDATA%/FreeCAD/v1-1/Mod/BentWizard` → repo root, so the working
  tree runs live. Restart FreeCAD to pick up changes.
- Scratch experiments go in `scratch/` (gitignored).

## Known limitations / backlog (the roadmap has the full list)

- Per-timber face labels (a `Role` on the Dims VarSet defaulting
  `FaceLabelXPos` … for drawings and the face pickers) — not built; the
  pickers show ±X/±Y.
- Created-part roles (wedges, pegs), the dovetail rebuilt on the new
  contract, the beam tool, the framer-facing panel.
- A mirrored component's source body sits at the document root (the
  Boolean claims the mirroring, not its source).
- Headless assemblies need an explicit `solve()` after a parameter
  edit; confirm the GUI does it on recompute.
