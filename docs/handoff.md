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

- **Duplicate Bent** (`duplicate.py`) — merged.

**In review (PR #3, branch `claude/timber-naming-conventions-451894`):**
the naming overhaul decided at the shakedown. Permanent serial labels
(`T-<Role>[-<Qualifier>]-<serial>` timbers, `J-<Kind>-<serial>` joints;
`naming.py` holds the pure helpers) split from position, which is now
display-only Tier-2 data (`Position_Tag` on Dims and joint VarSets).
Tree organization: Dims VarSets nest inside their Bodies, joint VarSets
park in a `TimberJointVars` Std Group (renamed from `Joints` to stay
clear of the Assembly workbench's own `Joints` group), Duplicate
Timbers (né Duplicate Bent) can group its copies.
Suggestion tools bump only the trailing serial segment (the old
first-number bent swap is gone — it mangled descriptive names). Legacy
labels stay accepted (advisory-clean) so the library template and
Adam's existing docs keep working; the template's internals
(`Joint_MT_0a`, roles `P0-1`/`B0-1`) are untouched — new joint labels
take their kind token from the template file stem (`HousedMT`).

**Landing PR #3** (the recommended worktree workflow, in order): (1)
merge the PR; (2) in the MAIN repo dir `…\Projects\BentWizard` — which
sits on `duplicate-bent`, not `main` — run `git checkout main && git
pull` so the main checkout actually holds the merged code; (3)
`scripts/dev-install.ps1 main` + restart FreeCAD. The point-back is a
*post-merge* step: pointing the junction at `main` before then loads the
pre-naming main checkout and FreeCAD silently drops the new dialogs.
Keeping the main checkout on `main` is the hygiene that makes
`dev-install.ps1 main` mean what it says.

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

- Tests: `C:\Users\Adam\Documents\Projects\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe -m unittest discover -s tests`
  (portable FreeCAD now lives outside the repo — see CLAUDE.md Environment)
- Lint a file: `... python.exe -m freecad.bentwizard.linter <file.FCStd>`
- Headless scripting: `freecadcmd.exe <script.py>`; to import the repo
  package, front-load `<repo>/freecad` on the already-imported `freecad`
  package's `__path__` (freecadcmd pre-imports its own `freecad`).
- **Worktree gotcha:** FreeCAD's Mod scan grafts the junction (the MAIN
  repo) onto `freecad.__path__` ahead of a worktree checkout — an
  `append` silently runs the main repo's code. `tests/_repo_path.py`
  front-loads the checkout under test (each test module imports it and
  re-grafts after `import FreeCAD`); do the same in ad-hoc scripts run
  from a worktree.
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
- **Duplicate Timbers** now reproduces the sources' relative
  placements (the copies-land-at-origin debt is paid; they assemble
  into an offset bent sub-assembly). Older joints
  (pre-`Template_Source`) rely on the library kind-scan fallback.
- **Handed tenons** (corner-anchored end frames mirrored about the
  section center) not supported — hand is side-landing-roles only.
- **Layout rules** (reframed July 2026): the workbench's native
  convention is **Mill Rule** — what's built already is it. Square Rule
  ≈ free (its reduce-to-ideal housing is field work, never a drawn
  dimension), Line Rule contained (centered timber variant, 2nd `FACES`
  table). See the roadmap's Layout rules section.
- **Permissive naming** (July 2026): body labels are free-form except
  the reserved characters `>`, `\`, `;`, and line breaks (new strict
  lint; empirically verified against the 1.1.1 expression engine). The
  serial is the trailing digit run after any of `-`/`.`/`_`/space, and
  bump tools preserve the separator — `T-Post.Balcony.001` is
  first-class. Workflow doc §3 has the full rule.
- **Descriptive-first feature labels** (July 2026): features inside
  bodies read `<Descriptive>[.<TypeTag>].<Abbrev>.<serial>`
  (`TailSlope.Skt.WHD.001`) instead of the body-qualified form, which
  buried the descriptive part between two long tokens. The Dims prefix
  shortened to `TDim_`, frame role moved to the Tier-2 `Frame_Role`
  property, and both library templates were migrated by
  `scripts/migrate-naming.py` — including `Joint_HousedMT`, which came
  off the legacy `Joint_MT_0a` / `P0-1` / `B0-1` internals named above.
  Existing documents are grandfathered, never rewritten.
- Joint browsing at scale, reference-face 3D indicator, primary/secondary
  as explicit load-path metadata. (New Timber expression fields and
  copy-from-selected landed July 2026.)
