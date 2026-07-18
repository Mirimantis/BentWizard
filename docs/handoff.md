# Session handoff

Living pointer for a fresh session. Read after CLAUDE.md and the three
spec docs (roadmap, workflow, findings). Update it as work lands.

## Where things stand (Phase 1)

Done and on `main`, all output lints clean, full suite green
(`python -m unittest discover -s tests` with the bundled python):

- **Linter** (`freecad/bentwizard/linter.py`) — workflow §6 as rules, pure
  Python over `fcstd.py`. Ground-truthed against the session-12 fixture.
- **Joint template** `library/Joint_HousedMT.FCStd` — housed, pegged,
  drawbored M&T on a landing-frame LCS per role, plus a **mate frame**
  on the tenon role (declares the engaged pose). Built by the recipe in
  `docs/mt-template-build.md`; mirrored as a test fixture that must stay
  strict- and advisory-clean.
- **Workbench commands** (`commands.py`, registered in `init_gui.py`):
  New Timber, Apply Joint (full placement: end A/B, faces 1–4, hand),
  Remove Joint, Preview Mated Joint.
- **Apply Joint** (`apply_joint.py`) — reads a template as a spec and
  rebuilds it natively in the target; junction bindings (§4.3) written
  to the mating timber's Dims; records `Placement_Record` and
  `Template_Source` on the joint VarSet.
- **Preview** — ghost App::Link of the secondary seated in the real
  primary, attached to the landing frame so it tracks most edits live
  (see the mate-frame-moving caveat below).

**In review (this PR, branch `duplicate-bent`):** Duplicate Bent
(`duplicate.py`) — Adam GUI-approved; awaiting merge.

## Architecture cheat-sheet (why the code is shaped this way)

- **Rebuild, don't copy.** New Timber, Apply Joint, and Duplicate Bent
  all *construct* native geometry rather than FreeCAD-copy it, so the
  phantom-feature / stale-expression traps (findings #2/#12) can't
  occur. This is the load-bearing decision.
- **Landing frame + mate frame.** Each role's stack hangs off one datum
  LCS (the landing frame); placement = re-placing that one frame (end
  via flip_z, face via the `FACES` table, hand via flip_x). The mate
  frame declares engagement (two frames coincide) — rule-neutral, so
  preview/assembly need no joint-specific code.
- **Junction point (§4.3).** All cross-timber coupling is joint-VarSet
  properties bound to the mating timber's Dims; body-internal features
  never reference a foreign Dims. The linter enforces this.
- **GUI-free cores.** `timber.py` / `apply_joint.py` / `duplicate.py`
  have no Qt imports; `commands.py` is thin wrappers. Tests drive the
  cores headless (FreeCAD-gated, skip under plain Python).
- **Verification is by resolved geometry**, not frame coincidence — the
  End-B bug (a backwards joint whose frames coincided perfectly) is why
  the seating tests assert solid interference, not just placement.

## Running things

- Tests: `FreeCAD_1.1.1-Windows-x86_64-py311/bin/python.exe -m unittest discover -s tests`
- Lint a file: `... python.exe -m freecad.bentwizard.linter <file.FCStd>`
- Headless scripting: `freecadcmd.exe <script.py>`; to import the repo
  package, append `<repo>/freecad` to the already-imported `freecad`
  namespace `__path__` (freecadcmd pre-imports its own `freecad`).
- The workbench is dev-installed via a junction at
  `%APPDATA%/FreeCAD/v1-1/Mod/BentWizard` → repo root, so the working
  tree runs live (uncommitted code included). Adam must restart FreeCAD
  to pick up changes.
- **Commit workflow (adopted):** build + headless-test, then Adam
  GUI-tests and approves BEFORE committing. Commits land tested.
- Scratch experiments go in `scratch/` (gitignored). Never save over a
  file Adam has open; read his files or copy to scratch.

## Next candidates (roadmap has full detail)

- **Save-as-joint-template** — the linter is already the validator;
  wrap it as a command that registers a user-modeled joint into
  `library/`. Natural next Phase-1 piece; low new surface.
- **Full test-bent assembly** (§4.8) — position the sticks into a real
  π with the Assembly workbench (datum-to-datum, mate frames are the
  natural anchors). Currently duplicated/new timbers sit at the origin.
- **Parameter groups / presets** — the type layer (§4.9); a preset is a
  Group VarSet the instance binds to. Adam wants this ("TieBeam01").
- Then Phase 2 (cut lists, TechDraw) per the roadmap.

## Known limitations / backlog (all in the roadmap's Open Items)

- **Preview** doesn't track edits that move the mate frame within the
  secondary (its Width/Depth, or Tenon_Length) or a body moved while
  the preview is up — refresh (toggle) fixes it. Complete fix = a
  recompute-driven ghost placement (FeaturePython); deferred.
- **Duplicate Bent** doesn't copy body Placements (copies land at the
  origin — assembly-phase concern). Older joints (pre-`Template_Source`)
  rely on the library kind-scan fallback.
- **Handed tenons** (corner-anchored end frames mirrored about the
  section center) not supported — hand is side-landing-roles only.
- **Layout rules**: Square Rule is a template convention on rule-neutral
  machinery; Mill Rule ≈ free (new templates + label), Line Rule
  contained (centered timber variant, 2nd `FACES` table). Assessed,
  backlogged.
- Joint browsing at scale, reference-face 3D indicator, primary/secondary
  as explicit load-path metadata, expression fields in the dialog.
