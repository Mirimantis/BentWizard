# Housed dropped-in dovetail — joinery note

Not yet built on the rev-2 contract. This note keeps the joinery from
the rev-1 recipe (`housed-dovetail-template-build.md`, deleted
September 2026). Values are imperial example data.

## The joint

A housed, dropped-in dovetail between a girt (socket role) and a joist
or tie (tail role), tops flush. **Both members are horizontal** — the
joist is lowered into the girt's top face. Do not confuse this with the
wedged half-dovetail, whose socket role must be a post: same family,
different purpose, different template.

The joist's end is shaped into a flared tail on its upper portion; the
girt gets a full-footprint housing in its side face plus a flared
socket cut down from its top face. The joist drops in from above:
vertical load bears on the housing ledger and the socket floor,
withdrawal is resisted by the flared flanks. The dovetail is defined
from the centerline (root and tip widths, both centred), so the joint
is symmetrical about its centerline and the mirror rule has nothing to
correct.

## Roles and datums

- **Primary (host):** the girt; landing datum on the side face the
  joist enters, at the station of the housing's near edge. The socket
  is cut from the girt's top face, so the cutter reaches around the
  datum's local +Y/−Y edge — author it and let the sweep confirm one
  solid.
- **Secondary (mate):** the joist or tie; joinery on its end datum. The
  tail is the adder-shaped end; the tail's flanks and the socket's
  match at the same parameters.

## Parameters (group `Joint`, UpperCamelCase, tooltip on each)

| Property | Example | Meaning |
|---|---|---|
| `HousingDepth` | 1/2 in | Depth of the housing into the girt's landed face; its ledger carries the joist's underside. The housing opening itself is `MateWidthU × MateWidthV` from the VarSet accessors — never a Dims binding. |
| `TailLength` | 4 in | From the joist's end to the shoulder plane; also the socket's reach beyond the housing floor. |
| `TailDepth` | 3 in | Vertical depth of the tail, down from the flush top faces; the socket floor sits this far below the girt's top. |
| `TailWidthRoot` | 3 in | Across the joist at the shoulder (the narrow end), centred. |
| `TailWidthTip` | 4 in | Across the joist at its end (the wide end); must exceed `TailWidthRoot` for the flanks to hold. |

## Sanity relations

- `TailWidthTip > TailWidthRoot`, or the flanks resist nothing; declare
  `TailWidthRootMax` = `TailWidthTip` in `Ranges` if the sweep should
  hunt it.
- `TailDepth < MateWidthV` (the joist's depth), or the tail is the whole
  end and the housing ledger carries nothing.
