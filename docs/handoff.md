# Session handoff

Living pointer for a fresh session. Read after CLAUDE.md and the rev-2
workflow doc. Update it as work lands.

## Where things stand (2026-09-24)

On `main`, FreeCAD 26.3 (the minimum; the weekly dev build is the test
environment), 154 tests green on the weekly, every piece through Adam's
GUI round:

- **The rev-2 foundation.** New Timber, Add Datum, Apply / Remove Timber
  Joint, Duplicate Timbers, Show Face & End Marks, Audit Timbers,
  Store in Variable Set, and the template bar (New / Save as Joint
  Template). The shipped library is `Joint_Butt` and `Joint_HousedMT`.
- **The flat frame is built** (`rebuild-flat-frame-handoff.md`). There
  is no Assembly object: the frame is a Std Group of bent and bay Std
  Groups, every timber but the anchor is **seated by expression**
  (`Seat_J-…` under the placing joint's handle), and the anchor is bound
  to `ProjectVars.FrameOrigin`. Seat Timbers is the bulk and repair
  path. Audit Timbers reports each timber as anchored, seated,
  provisional or loose, with each timber joint's misfit.
  - Workstreams A (seats), C (handles) and D (readers) are built.
  - B (value splits) is retired: 26.3's fine-grained recomputes do its
    job.
  - E (export to Assembly) is Phase 2.
- **The 26.3 move is complete** (`freecad-26-3-compatibility-brief.md`).
  Booleans carry `UseLegacyBodyPlacement` (route (a)); the sweep found
  nothing moved under the geometry.

**Next:** the front end's near-term items and the roadmap's deferred
list: face labels per timber role, created-part roles, the dovetail,
the beam tool, the panel. **Before 26.3 releases:** the brief's route
(b), binding components globally in place of `UseLegacyBodyPlacement`.

## How it got here — the September 2026 GUI rounds

The rev-1 code is gone: `apply_joint.py`, `span.py`, the parity tables,
`Stick_Allowance_*`, the companion `Layout_` VarSet, `Template_Handed`,
Preview Mated Joint, Drive Length from Layout Distance, the dovetail
template, and — with the flat frame — `assemble.py` and the Fixed-joint
solver.

The first GUI walk-through, as written before rev 2 was committed
(Assemble Timbers is now Seat Timbers, and there is no assembly to
re-solve):

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

**Third GUI round (Adam, 2026-09-18/19): bent spacing is blocked.**
Editing a tie's length moves a bent sub-assembly, and FreeCAD then
draws that bent's Fixed-joint markers at twice its shift (FreeCAD's
bug, not ours). A flat-frame spike found two more problems: closed
loops of Fixed joints break the solver from 4 bents, and even loop-free
the solver cannot re-space 10 bents. **Read
[spike-flat-frame-results.md](spike-flat-frame-results.md) before
touching `assemble.py`**. **Decided 2026-09-19: the flat frame** — one
assembly per frame, bents and bays as Std Groups, and timbers **seated
by expression** (a `Seat_J-…` VarSet under each placing joint's
handle) rather than by the solver — exact to 20 bents (roadmap, *Flat
frame*; spike round 2). **Built** since, from the build brief
[rebuild-flat-frame-handoff.md](rebuild-flat-frame-handoff.md) (A, C
and D; B retired; E Phase 2). Fixed in the same round: joint-handle
markers under moved containers, Duplicate Timbers moving the new
assembly, the Apply dialog dropping a chosen face. The last item then
still open was fixed on 2026-09-24: switching templates in the Apply
dialog now keeps every choice, and the dialog opens on the template
last applied.

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
- **Seat by expression, never by a solver.** The placing joint's seat
  VarSet computes `anchor · near · flip · far⁻¹` from the two datums;
  the placed timber's `Placement` reads it (`frame.seat`). Placing
  joints form a spanning tree from the anchor. A joint whose timbers are
  both placed closes a loop and is checked by its misfit. The placement
  tree is not the load path.
- **Structural, never label-matched.** Dims from the stick pad's
  `LengthZ` binding; joint members from the `<<J-…>>` token anchored on
  component bodies; handles by their links; seats by the `<<Seat_…>>`
  their timbers read. Stored references are matched in the form FreeCAD
  writes (`naming.label_ref`: quotes in a label are escaped).
- **GUI-free cores.** `timber`, `datums`, `apply`, `frame`,
  `duplicate`, `measure`, `template_check` have no Qt; `commands.py` is
  thin wrappers. Tests drive the cores headless.

## Running things

- Tests: `<FreeCAD>\bin\python.exe -W error::DeprecationWarning -m
  unittest discover -s tests`, where `<FreeCAD>` is the 26.3 weekly
  beside the checkout (location varies per machine; see CLAUDE.md →
  Environment). The flag turns any deprecated FreeCAD call into a
  failure.
- Lint a file: `... python.exe -m freecad.bentwizard.linter <file.FCStd>`
- Rebuild the shipped library: `... python.exe scripts/build_library.py`
  (writes `library/Joint_Butt.FCStd` and `library/Joint_HousedMT.FCStd`
  and runs the template bar on both)
- Headless scripting: `freecadcmd.exe <script.py>` swallows `print`;
  prefer the bundled `python.exe`, and front-load `<repo>/freecad` on
  `freecad.__path__` (`tests/_repo_path.py`) so the checkout wins over
  the `Mod` junction.
- The workbench is dev-installed via the junction at
  `%APPDATA%/FreeCAD/v26-3/Mod/BentWizard` → repo root (one for every
  26.3 weekly), so the working tree runs live. Restart FreeCAD to pick
  up changes.
- Scratch experiments go in `scratch/` (gitignored).

## Known limitations / backlog (the roadmap has the full list)

- Per-timber face labels (a `Role` on the Dims VarSet defaulting
  `FaceLabelXPos` … for drawings and the face pickers) — not built; the
  pickers show ±X/±Y.
- Created-part roles (wedges, pegs), the dovetail rebuilt on the new
  contract, the beam tool, the framer-facing panel.
- A mirrored component's source body sits at the document root (the
  Boolean claims the mirroring, not its source), and the mirroring's
  link to it is reported out of scope on every GUI recompute. Only
  handed templates mirror now (`Handed` flag, 2026-09-19); both-hands
  templates, due with the dovetail, remove mirroring entirely.
- Route (b) of the 26.3 brief: components bound globally instead of
  `UseLegacyBodyPlacement` on every Boolean — before 26.3 releases.
- Export to Assembly (flat-frame workstream E, Phase 2). FreeCAD's
  moved-assembly marker bug is fixed upstream in the weekly (#28089);
  check it in the GUI when the export is built.
