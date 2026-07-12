# Dev build macros

Session transcripts and helpers from the Phase 1 template builds
(FreeCAD-side artifacts, not workbench code).

- `Phase1JointBuild01*.FCMacro` — recorded build sessions for
  `library/Joint_HousedMT.FCStd`.
- `EnforceNaming.FCMacro` — dev helper: prompts for a convention-
  conforming label whenever a watched object type is created, so the
  tree never fills with `Sketch007` debris. Toggle by running the macro;
  auto-enabled at startup by a shim at
  `%APPDATA%\FreeCAD\v1-1\Mod\EnforceNaming\InitGui.py` (machine-local,
  not in the repo) which execs this file, so edits here take effect on
  the next FreeCAD start.
