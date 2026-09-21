# Draft upstream issue — `Gui::QuantitySpinBox` in 26.3

**Status: drafted 2026-09-21, NOT filed.** Adam's call whether it goes
up. Evidence is [spike-26-3-gui-results.md](spike-26-3-gui-results.md)
finding 9. If it is filed, record the issue number here and in that
finding; if it is withdrawn, say why, as the last one did.

Everything below the line is the issue text.

---

## Quantity spin boxes: steppers do not change the value, and unitless input is read in mm rather than the displayed unit

### Summary

On 26.3.0 (weekly `2026.09.16`, git `a4ce44d33b`), `Gui::QuantitySpinBox`
appears to have lost track of the unit it displays in, in two directions:

1. **The up/down steppers change the displayed text but not the
   widget's value.** The next focus-out repaints from the unchanged
   value, so the edit is silently discarded.
2. **A unitless typed number is interpreted in the internal unit (mm)
   rather than the displayed unit.** Under a schema that displays
   inches, typing `10` into a field reading `8"` yields 0.39" (`3/8"`),
   not 10".

Both reproduce in stock dialogs — Part → Box is the shortest path — so
this is not specific to any one workbench. Both worked correctly in
1.1.3 with the same user schema.

### Reproduce (no scripting)

Preferences → General → Units → **Building US (ft/in/fraction)**, then
Part workbench → **Box**:

1. Click the **Length** field's up arrow a few times. The text advances
   (`10'` → `10' 1"` → …).
2. Click into another field. **Length snaps back to its original
   value.** Same with the Up/Down arrow keys and the mouse wheel.
3. Select Length's contents, type `10`, click away. It becomes
   **`3/8"`** — 10 mm — rather than 10 inches.

Expected: the stepper commits, and a unitless entry is read in the unit
the field is displaying.

### Reproduce (scripted)

In the Python console, with the unit schema set to Building US; no
add-ons involved:

```python
import FreeCADGui as Gui

def field():
    w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
    w.setProperty("unit", "mm")
    w.setProperty("rawValue", 203.2)      # 8 in
    w.show()
    return w

a = field()
print(a.lineEdit().text(), a.property("rawValue"))   # '8"'  203.2
a.stepUp(); a.stepUp()
print(a.lineEdit().text(), a.property("rawValue"))   # '10"' 203.2 <-- unchanged

b = field()
b.lineEdit().setText("10"); b.interpretText()
print(b.property("rawValue"))                        # 10.0       <-- mm, not 10 in
```

Measured output, same machine, same schema:

| | after two steps | after typing `10` |
|---|---|---|
| 1.1.3 (`20260725`) | `'10"'` **254.0** | **254.0** |
| 26.3.0 (`a4ce44d33b`) | `'10"'` **203.2** | **10.0** |

### Scope of the stepper problem

The value is unchanged no matter how the widget is configured. All of
the following were tried, and all revert on 26.3 while all hold on
1.1.3: `unit` set to `mm`, set to the displayed unit, or left unset;
`value` set as a `Base::Quantity`; `quantityString`; `setValue()` as a
method; `keyboardTracking` off; `autoNormalize` off.

`interpretText()` and emitting `editingFinished` do not commit it
either. Re-assigning `value` from the line edit's text does, as does
`userInput()` — which is how a workaround is possible downstream, but
the steppers are broken for every existing dialog as shipped.

### A related inconsistency in `minimum` / `maximum`

Possibly the same root cause, and present in **1.1.3 as well**, so not a
regression — but it makes the bounds unusable from Python:
`minimum`/`maximum` are read **in the displayed unit while stepping**
but as **raw internal values on focus-out**. Setting a 152.4 mm maximum
as `152.4` lets a step clamp to 152.4 *inches*; setting it as `6.0`
(inches) lets focus-out clamp a valid 4" value down to 6 **mm**. Passing
a `Base::Quantity` is accepted but leaves the bound unset. There is no
value that is correct in both code paths.

### Environment

- FreeCAD 26.3.0, weekly `2026.09.16`, git `a4ce44d33b`, Windows x86_64
- Python 3.14.7, PySide6 6.11.1 / Qt 6.11.1
- Compared against 1.1.3 (`20260725`) on the same machine and the same
  unit schema, where all of the above behaves as expected
