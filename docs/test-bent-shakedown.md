# Test bent — Phase 1 validation shakedown

Building a simple bent with the workbench tools end to end, to validate
them against real workflow (the Phase 0 promise). A **bent** here is two
posts + a tie beam (a "π"): the beam's tenons enter mortises in the two
posts, which form a handed pair. This exercises New Timber ×3, Apply
Joint ×2 (both stick ends of one beam; template vs. mirrored hand),
Preview, and Remove — and the whole document must lint clean.

Dry-run-verified: the sequence below produces correct cut volumes and a
clean lint headless, so any deviation you hit is worth reporting.

Assembly (positioning the three sticks into an actual π in space) is
separate manual work (workflow §4.8, Assembly workbench) — a follow-on,
not part of this shakedown. Here each joint is verified in isolation by
Preview; the sticks can stay at the origin.

MemberIDs use bent 1: posts `P1-1`/`P1-2`, tie beam `TB1-1`.

## 1. Three timbers (New Timber ×3)

| MemberID | Width | Depth | Length | Role |
|---|---|---|---|---|
| `P1-1` | 8 in | 8 in | 108 in | left post |
| `P1-2` | 8 in | 8 in | 108 in | right post |
| `TB1-1` | 6 in | 8 in | 120 in | tie beam (narrower, so housings aren't full-width) |

**Checkpoint 1:** save, tell me — I verify three bodies each with their
Dims, lint clean, no label collisions.

## 2. Left joint — `MT_1a` (Apply Joint)

Select `P1-1` then `TB1-1` (order preseeds the roles), Apply Joint:
- Template: `Joint_HousedMT`
- Joint ID: `1a`
- `T.Post.001` timber `P1-1`, **face Face 4**, **hand As templated**
- `T.AnchorBeam.001` timber `TB1-1`, **end End A**
- Joint_Station: **96 in** (leaves 4 in of post above the footprint)
- everything else default

Expect: post cut ≈ 79.7 in³, beam End A cut ≈ 145.6 in³.

## 3. Right joint — `MT_1b`, the handed mate (Apply Joint)

Select `P1-2` then `TB1-1`, Apply Joint:
- Joint ID: `1b`
- `T.Post.001` timber `P1-2`, **face Face 4**, **hand Mirrored (handed pair)**
- `T.AnchorBeam.001` timber `TB1-1`, **end End B**
- Joint_Station: **96 in**

Expect: the beam now cut at *both* ends (total ≈ 291 in³), `P1-2` mirror
of `P1-1`.

**Checkpoint 2:** save, tell me — I verify both joints, both timbers'
cuts, and a clean lint on the whole document.

## 4. Preview each joint

- Select `Joint_MT_1a` (or click its landing frame in 3D) → Preview
  Mated Joint. The beam ghosts in, tenon seated in `P1-1`'s mortise;
  real `TB1-1` hides. Confirm the shoulder meets the housing face and
  the tenon fills the mortise. Preview again to clear.
- Repeat for `Joint_MT_1b` — the mirrored post. Confirm the tenon seats
  on the correct (mirrored) side.

## 5. Remove + re-apply (multi-joint document check)

- Remove Joint → `Joint_MT_1b`. Confirm it lists ~13 objects across
  `P1-2` and `TB1-1`, removes cleanly, and `P1-1`/`MT_1a` are untouched
  (the beam keeps its End A tenon, loses its End B tenon).
- Re-apply `MT_1b` per step 3.

**Checkpoint 3:** save, tell me — final verification and we close out
the shakedown. Report any friction: hunts, surprises, anything that
felt wrong. This is where the tools meet reality.
