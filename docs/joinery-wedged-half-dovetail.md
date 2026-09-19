# Wedged half-dovetail (Dutch anchor beam) — joinery note

The rev-1 template `Joint_WedgedHalfDovetail.FCStd` was retired with
the rev-2 rebuild; this note keeps its joinery (from
`wedged-half-dovetail-template-build.md`, deleted September 2026) for
the rebuild on the new contract. Rewritten July 2026 from Adam's
finished model, which corrected the first draft: the original had the
dovetail inverted — slope on top, wedge below — which resists nothing.
Values are imperial example data.

## The joint

The Dutch anchor-beam joint: a through tenon whose **underside is a
half dovetail**, flaring so the tenon is tallest at its protruding tip;
the post's through mortise carries the matching slope on its floor. The
mortise is cut taller than the tenon, and that surplus sits **above**
the seated beam, where a wedge is driven down to lock the beam and
force the sloped faces into bearing. Housed (an optional bearing
feature).

## The socket role is a post — this is not the housed dovetail

The mortise timber must be a **post or other vertical member**; the
tenon timber is a horizontal beam or tie entering its face. The housed
dovetail drops a joist into a *horizontal* girt's top face, tops flush.
Two dovetails, two purposes, two templates.

The constraint is gravity, and it is baked into the geometry rather
than into any check. The landing datum's local Y runs **along the post
toward its end A**, so every "above" here — the mortise surplus, the
wedge seat, the direction the beam is lowered from — is along the
post's length, and the station reads as a height up the post. Lay the
socket member down and the wedge pocket opens sideways: the wedge has
nothing to bear against and drops out.

Section rules it out too. The mortise is taller than the incoming
beam's *full depth* (`TenonHeight + WedgeDepth`), so a girt of
comparable depth would be cut through top to bottom with nothing left
to carry load. Posts have the section to give up; horizontal members in
the same frame do not.

## The three geometric facts that define this joint

Everything follows from these; get them wrong and the joint is
decorative.

1. **The slope is on the tenon's underside, and the tenon is tallest at
   the tip.** Withdrawal pulls the tall tip against the narrower
   mortise mouth. (On the built model: tenon height 7.96 in at the tip,
   7.08 in at the shoulder.)
2. **The tenon is the full depth of the beam** — its top face *is* the
   beam's top face. No top or bottom shoulder is cut: the angled
   underside creates the only shoulder, at the bottom. Fewer cuts, and
   a flush top surface for driving the wedge.
3. **The mortise is taller than the beam, and the surplus is above it**
   — above meaning *up the post*, which is why the socket member must
   be plumb. Mortise opening = `TenonHeight + WedgeDepth`; the beam's
   landing footprint = the housing. The difference is deliberately
   exposed above the seated beam so the wedge is reachable — a wedge
   you cannot get at is a joint you cannot assemble.

The insertion clearance follows from (1): the tenon enters tip-first
past a mouth sized for the *root*, so the beam is carried in high and
lowered — again, along the post's length.
**`WedgeDepth` ≥ `TenonLength` × tan(`DovetailAngle`)** — as built,
11 × tan 5° = 0.96 in ≤ 1.25 in.

## Roles and datums

- **Primary (host):** the post; landing datum on the entered face at
  the station of the housing's underside. Cutter: the housing
  (`MateWidthU × MateWidthV × HousingDepth`) and the through mortise
  with its sloped floor and the wedge surplus above.
- **Secondary (mate):** the anchor beam; joinery on its end datum.
  Adder: the through tenon, full beam depth at the shoulder, underside
  rising at `DovetailAngle` toward the tip. It is asymmetric *along the
  post* (vertical), which the mirror rule (across the datum's local X)
  never touches — the chirality test the parity rule wants.

## Parameters (group `Joint`, UpperCamelCase, tooltip on each)

| Property | Example | Meaning |
|---|---|---|
| `HousingDepth` | 1 in | Depth of the housing into the post. A deep housing spreads bearing across the full beam width. |
| `TenonThickness` | 2 in | Horizontal across the landed beam, centred on the beam's width. |
| `TenonHeight` | = `MateWidthV` | Tenon height at the mouth — the full beam depth, since the tenon's top is the beam's top face and only the underside is cut. |
| `DovetailAngle` (Angle) | 5° | Rise of the tenon's underside from the tip toward the shoulder, off the beam's axis. The mortise floor matches it. |
| `TenonLength` | 11 in | From the beam's end to the shoulder plane; must exceed the post's through-dimension (`HostDepthW`) so the tip emerges. |
| `WedgeDepth` | 1 1/4 in | Height of the mortise above the seated tenon — the wedge seat, left open above the beam so the wedge can be driven. |
| `WedgeWidth` | = `TenonThickness` | Wedge stock width across the mortise, for the parts schedule. |
| `WedgeLength` | = `TenonLength` | Wedge stock length along the beam's axis, for the parts schedule. |
| `WedgeCount` (Integer) | 1 | Number of wedges, for the parts schedule. Not geometry. |

**The wedge is not modelled.** Its cavity is (it is simply the mortise
surplus) and its stock rides on the VarSet for the parts schedule, the
same Tier-2 pattern as `PegCount`. Modelling it is the roadmap's
created-part role.
