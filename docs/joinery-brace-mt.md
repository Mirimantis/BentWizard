# Brace mortise & tenon — joinery note

Not yet built on the rev-2 contract. This note keeps the joinery from
the rev-1 recipe (`brace-mt-template-build.md`, deleted September 2026)
so the template can be authored as a cutter/adder pair when the
roadmap reaches it. Values are imperial example data.

## The joint

Mortise & tenon for a vertical diagonal — knee braces and struts. The
brace's end is cut at the brace angle (default 45°) so its oblique
shoulder lands flush on the receiving timber's face; the tenon runs
along the brace's axis into an angled mortise slot. **The angle is a
joint parameter**, not a baked-in 45: every angled line is an Angle
constraint bound to the VarSet, so one template serves 40/45/50°
braces. An *angled cut on a perpendicular datum* is pure template
geometry (sketch lines at an angle, prismatic pockets); what the
roadmap's parametrically-angled-joint work buys is *placement*, not
these cuts.

Unhoused: brace mortises bear on the face itself — housings are an
optional shop feature. A housed or diminished variant is a separate
template.

## Roles and datums

- **Primary (host):** the receiving timber (post, tie, plate); the
  landing datum sits on a side face at the station where the brace's
  centerline crosses that face.
- **Secondary (mate):** the brace; joinery on its end datum. Its end is
  the tenon tip; the shoulder plane is oblique to the stick.

A *descending* strut is not this template mirrored: the mirror rule
mirrors across the datum's local X (in the joint plane), and the strut's
handedness is out of that plane. Author a mirrored variant, or place it
from the other end of the receiving timber.

## Parameters (group `Joint`, UpperCamelCase, tooltip on each)

| Property | Example | Meaning |
|---|---|---|
| `BraceAngle` (Angle) | 45° | Angle between the brace's axis and the receiving timber's length axis, in the joint plane. Drives every angled cut in both halves. |
| `TenonThickness` | 1 1/2 in | Across the brace's width, centred on it. |
| `TenonHeight` | 3 1/2 in | Across the brace's depth, centred on it; measured perpendicular to the brace's axis. |
| `TenonLength` | 4 in | Along the brace's axis, from the tip to where the shoulder plane crosses the brace's centerline. |
| `MortiseRelief` | 1/4 in | Extra mortise depth beyond `TenonLength` along the entry axis, so the tenon never bottoms out. |
| `BraceAngleMin` / `BraceAngleMax` (group `Ranges`) | 30° / 60° | The angle range the cut profiles stay valid for; the sweep and the apply dialog read them. |

## Sanity relations (why the range exists)

- Shoulder clears the stick end: `TenonLength > (Depth / 2) · tan(90° − BraceAngle)`.
  At the defaults 2.5 < 4 ✓; below ~32° with these sticks the shoulder
  runs off the tip and the sketches degenerate — the registration sweep
  will find that as a second solid or an invalid pad.
- Mortise mouth along the receiving timber = `TenonHeight / sin(BraceAngle)`
  ≈ 4.95 in at the defaults — keep it clear of other joinery at the station.
