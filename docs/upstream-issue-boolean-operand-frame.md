# Upstream issue draft — PartDesign Boolean operand ignores the target Body's Placement (26.3)

Paste into <https://github.com/FreeCAD/FreeCAD/issues/new>. Written
2026-09-20 from the measurements in
[spike-fine-grained-recompute-results.md](spike-fine-grained-recompute-results.md).
Not filed by Claude — Adam files it.

---

**Title:** PartDesign Boolean places its operand in global space when the target Body has a non-identity Placement (26.3 regression; `Cut` fails silently)

### Description

In 1.1.3 a `PartDesign::Boolean` interprets its operand Body in the
**target Body's local frame**: moving the target moves the operand with
it, and the boolean result is unchanged. In 26.3 the operand stays where
it is in global space, so a target Body that has been moved no longer
intersects its own operand.

`Fuse` produces a two-solid Body. **`Cut` is worse: it removes nothing
and reports success**, leaving a valid but wrong solid with no error,
which is how a wrong part reaches a shop drawing unnoticed.

This is not caused by the new fine-grained recomputes: the result is
identical with `FineGrainedRecompute` true and false. A plain
`Part.fuse` of two face-touching boxes is also unaffected, so it is not
a kernel boolean change either — it is the frame the operand is taken in.

### Version

```
OS:       Windows 10 Pro (10.0.19045)
Version:  26.3.0, weekly 2026.09.16, git a4ce44d33b7e42e16cb8156058a1894237042ab4
Compare:  1.1.3, git 145529fe74 — correct there
```

### Steps to reproduce

Run in the Python console of each build (no add-ons, no GUI needed):

```python
import FreeCAD as App

def case(op, move):
    doc = App.newDocument("R")
    body = doc.addObject("PartDesign::Body", "Body")
    stick = body.newObject("PartDesign::AdditiveBox", "Stick")
    stick.Length, stick.Width, stick.Height = 100, 100, 200
    tool = doc.addObject("PartDesign::Body", "Tool")
    tb = tool.newObject("PartDesign::AdditiveBox", "Tool")
    tb.Length, tb.Width, tb.Height = 40, 40, 40
    tb.Placement.Base = App.Vector(30, 30, 180)      # straddles the top face
    doc.recompute()
    if move:                                          # the only difference
        body.Placement = App.Placement(App.Vector(1000, 500, 0),
                                       App.Rotation(App.Vector(0, 0, 1), 30))
        doc.recompute()
    bo = body.newObject("PartDesign::Boolean", "Bool")
    bo.Group = [tool]
    bo.Type = op
    doc.recompute()
    print(op, "moved" if move else "at origin",
          "solids:", len(body.Shape.Solids), "volume:", body.Shape.Volume)
    App.closeDocument(doc.Name)

for op in ("Fuse", "Cut"):
    for move in (False, True):
        case(op, move)
```

### Results

| Case | 1.1.3 | 26.3 | Expected |
|---|---|---|---|
| `Fuse`, Body at origin | 1 solid, 2032000 | 1 solid, 2032000 | 1 solid, 2032000 |
| `Fuse`, Body moved | 1 solid, 2032000 | **2 solids, 2064000** | 1 solid, 2032000 |
| `Cut`, Body at origin | 1 solid, 1968000 | 1 solid, 1968000 | 1 solid, 1968000 |
| `Cut`, Body moved | 1 solid, 1968000 | **1 solid, 2000000** | 1 solid, 1968000 |

2064000 is the stick plus the *whole* tool (2000000 + 64000): the tool
was added as a disjoint lump instead of overlapping. 2000000 is the bare
stick: the cut removed nothing.

### Why this matters downstream

In the timber-framing workbench this was found in, every joint is a
component Body (a mortise cutter, a tenon adder) applied to a timber
Body by a `PartDesign::Boolean`, with the component's `Placement` bound
by expression to a datum's *local* placement — precisely because the
Boolean has always resolved its operand in the target's local frame.
Timbers are then positioned by expressions, so most of them have a
non-identity `Placement`. On 26.3, 13 of 123 tests fail with two-solid
timbers, and the `Cut` case would pass its volume assertions while
cutting nothing.

If the change is intentional (operands resolved in global space), please
say so and I will rebind the components to global placements — but the
silent `Cut` result seems worth an error either way.
