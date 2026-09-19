# Joint template library

One ordinary `.FCStd` file per joint template, built by
`scripts/build_library.py` from the workbench's own API (so the shipped
files are exactly what New Timber, Add Datum and the component helpers
produce — the library is a test of the tool as much as a product).

A template contains:

- **two timbers** — the *host* (first in the tree) and the *mate* — each
  with a **datum** paired to the other's under the joint VarSet: the
  host's face datum (`D_T-Post-000_YPos_001`, on +Y at 48 in) and the
  mate's end datum (`D_T-Girt-000_B`). The mate is seated so the file
  shows the joint as it engages.
- **one joint VarSet**, `J-<Kind>-000` — the parameter schema the apply
  dialog is generated from. Parameters live in group `Joint`
  (UpperCamelCase, a tooltip on every one, stating which datum axis it
  measures along). Optional range bounds go in group `Ranges` as
  `<Name>Min` / `<Name>Max`; the registration sweep and the apply
  dialog read them. The tool writes the six accessors `HostWidthU …
  MateDepthW` and `HostPlacement` / `MatePlacement` (group `Datums`):
  they read the two datums, and they are how a component learns the
  *other* timber's section and where it sits.
- **component Bodies** at the document root — a `Cutter` modelled in
  −Z from its own origin (it eats into the material behind the datum)
  or an `Adder` modelled in +Z (it grows out of it) — each carrying
  `ComponentRole` and `ComponentOrder`, its `Placement` bound to the
  joint VarSet's accessor for the datum it sits on
  (`<<J-<Kind>-000>>.HostPlacement` / `.MatePlacement` — never to the
  datum itself: a Body that reads a datum makes FreeCAD file the datum's
  axes under that Body, and the datum fails its scope check on
  recompute), labelled
  `<Descriptive>.<Kind>.000` (`Mortise.HousedMT.000`), and applied to
  that datum's timber by a `PartDesign::Boolean` (`Cut.Mortise.HousedMT.000`,
  `Fuse.Tenon.HousedMT.000`), cutters before adders.
- non-geometric schedule data (`PegCount`) as VarSet properties.

**A component reads only the datum it is placed on and the joint
VarSet** — host data through the datum's own `WidthU`/`WidthV`/`DepthW`,
mate data through the VarSet's `Mate*` accessors — never a timber's Dims,
never another datum. Referencing the mate's datum directly gives the
right numbers today and the wrong ones after a re-pair, and a datum
that reads another datum is a dependency cycle (FreeCAD's graph is
object-granular).

**Applying a template copies it.** Apply Timber Joint copies the VarSet
and the component bodies into the document, relabels them to the new
serial, re-points every `<<D_…>>` reference to the target datums,
mirrors a component across its local X when the target datum's parity
differs from the authoring datum's (so a component keeps its
timber-local offsets at either end and on opposite faces), and applies
the Booleans in `ComponentOrder`, refusing if a timber stops being one
solid. Nothing about the geometry is rebuilt, so a template author never
learns a feature vocabulary.

Templates must clear the **template bar**:

```
python -m freecad.bentwizard.linter library/<template>.FCStd
```

plus `template_check.check` (skeleton, stem contract, a real
`TemplateSpec` load) and `template_check.check_geometry` (one solid per
timber, growth direction, the parameter sweep across each declared
range — the sweep's findings are persisted on the VarSet as
`SweepFindings`, empty when clean). `tests/test_template_check.py`
runs the bar over every file here.

## Shipped

- `Joint_Butt.FCStd` — a squared end landing flush on a face at a
  station, no joinery: two timbers, two paired datums, an empty VarSet.
  The **starter skeleton** New Joint Template authors from (a starter is
  any template with no Boolean in it — found structurally, so a second
  starter is a file to author, not code to write), and a real project
  joint in its own right for bracketed or gusseted connections.
- `Joint_HousedMT.FCStd` — housed, square-shouldered mortise and tenon.
  `Mortise.HousedMT.000` (Cutter, order 1, on the post's face datum): the
  housing, `MateWidthU × MateWidthV × HousingDepth`, and the mortise,
  `TenonThickness × TenonWidth × (TenonLength + HousingDepth + MortiseFit)`,
  both in −Z. `Tenon.HousedMT.000` (Adder, order 2, on the girt's end-B
  datum): the full section through the housing, `WidthU × WidthV ×
  HousingDepth`, and the tenon, `TenonThickness × TenonWidth ×
  (TenonLength + HousingDepth)`, both in +Z. No lateral fit: cheeks are
  tight, `MortiseFit` is extra depth so the shoulder seats.

## Authoring your own

**New Joint Template** copies a starter to your template folder under
the kind you name, relabels its VarSet to `J-<Kind>-000`, and opens it.
Author the parameters on the VarSet and the components as above (the
report window it opens repeats the rules), and apply each component
with a Boolean so the file shows the finished joint. Never start from a
template that already has components: the copy brings them along.

**Save as Joint Template** writes the open document into your template
folder and reports what the bar found. It reports, never blocks — a
template with findings is saved anyway; the report is a checklist to
work through in the document. *Check* runs the same bar on a
temporary copy without saving.

Two folders are searched, the user's ahead of this one, so a locally
revised copy of a shipped joint shadows it rather than appearing twice:

- **your template folder** — `<FreeCAD user app data>/BentWizard/library`
  by default (stored as `TemplateDir` under
  `BaseApp/Preferences/Mod/BentWizard`),
- **this shipped library**.

The **file stem is the joint's kind**: `Joint_BraceMT.FCStd` makes every
joint applied from it `J-BraceMT-<serial>`, which is what reaches the
cut list. Saving relabels the VarSet, components, Booleans and
mirrorings to match — safe, because FreeCAD re-points every `<<Label>>`
expression when an object is relabeled.
