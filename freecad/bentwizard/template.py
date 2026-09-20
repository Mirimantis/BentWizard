"""Reading a joint template — what it declares, without opening it.

A template is an ordinary FreeCAD file (``library/Joint_<Kind>.FCStd``)
holding two timbers with a paired datum each, one joint VarSet
(``J-<Kind>-000``) and, unless it is the jointless starter, one or more
**component** Bodies — a ``Cutter`` modelled in -Z or an ``Adder`` in
+Z — each placed on one of the datums and applied to that datum's
timber by a ``PartDesign::Boolean``. The file is read here purely (the
same reader the linter uses) and **copied**, never rebuilt: what a
template's geometry is made of is none of the tool's business.

The spec is what Apply Timber Joint and the dialog need: the roles (the
two template timbers, in tree order — the first is the host), the
parameters (the joint VarSet's own properties, with tooltips and any
declared ranges), and the components (role, order, and which template
datum each sits on, so it can be re-pointed to the target's).
"""

from __future__ import annotations

from pathlib import Path

from . import naming
from .fcstd import FcstdDocument, expression_refs
from .linter import Model

_NUMERIC = ("App::PropertyLength", "App::PropertyDistance", "App::PropertyAngle",
            "App::PropertyFloat", "App::PropertyInteger", "App::PropertyQuantity")


class JointError(ValueError):
    """A template, apply or remove request that cannot be honored."""


class TemplateSpec:
    """A joint template, as the tool sees it."""

    def __init__(self, path):
        self.path = Path(path)
        self.stem = self.path.stem
        self.kind = naming.template_kind_from_stem(self.stem)
        self.doc = FcstdDocument.from_file(self.path)
        self.model = Model(self.doc)

        joints = self.model.joint_varsets()
        if len(joints) != 1:
            raise JointError(
                f"{self.stem}: expected exactly one joint VarSet, found "
                f"{[v.label for v in joints]}")
        self.varset = joints[0]
        self.varset_label = self.varset.label

        timbers = self.model.timbers()
        if len(timbers) != 2:
            raise JointError(
                f"{self.stem}: a joint template holds exactly two timbers, "
                f"found {[b.label for b in timbers]}")
        # roles in tree order (Document.xml keeps creation order); the
        # host datum's timber is the host role and comes first
        host_datum = self.model.accessor_datum(self.varset, "Host")
        mate_datum = self.model.accessor_datum(self.varset, "Mate")
        if host_datum is None or mate_datum is None:
            raise JointError(
                f"{self.stem}: the joint VarSet's Host*/Mate* accessors do not "
                f"name a pair of datums — pair the two datums first")
        self.host_datum_label = host_datum.label
        self.mate_datum_label = mate_datum.label
        host_body = self.model.datum_owner(host_datum)
        mate_body = self.model.datum_owner(mate_datum)
        if host_body is None or mate_body is None or host_body is mate_body:
            raise JointError(f"{self.stem}: paired datums must sit on the "
                             f"two different template timbers")
        self.roles = [host_body.label, mate_body.label]
        self.host_role, self.mate_role = self.roles
        self.role_datum = {host_body.label: host_datum.label,
                           mate_body.label: mate_datum.label}
        self.datum_face = {host_datum.label: self.model.datum_face(host_datum),
                           mate_datum.label: self.model.datum_face(mate_datum)}

        handed = self.varset.prop(naming.PROP_TEMPLATE_HANDED)
        # None = undeclared: a template predating the flag keeps the
        # mirror rule — a missing flag must never silently un-mirror a
        # handed joint
        self.handed = handed.value if handed is not None and isinstance(
            handed.value, bool) else None

        self.parameters = self._parameters()
        self.components = self._components()

    @property
    def mirrors(self):
        """Whether Apply mirrors a component whose target datum's parity
        differs from its authoring datum's: everything but Handed = False."""
        return self.handed is not False

    # -- parameters ---------------------------------------------------------

    def _parameters(self):
        out = []
        props = self.varset.properties
        for p in props.values():
            if p.group is None:
                continue
            name = p.name
            if (naming.is_accessor_property(name)
                    or naming.is_template_metadata(name, p.group)
                    or naming.is_range_property(name, p.group)
                    or name == naming.PROP_POSITION_TAG
                    or name == naming.PROP_SWEEP_FINDINGS):
                continue
            entry = {"name": name, "type": p.type_id, "default": p.value,
                     "doc": p.doc or "", "group": p.group,
                     "expression": next((e.expression for e in self.varset.expressions
                                         if e.path.lstrip(".") == name), None),
                     "min": None, "max": None,
                     "numeric": p.type_id in _NUMERIC}
            for suffix, key in ((naming.RANGE_MIN_SUFFIX, "min"),
                                (naming.RANGE_MAX_SUFFIX, "max")):
                bound = props.get(name + suffix)
                if bound is not None and isinstance(bound.value, (int, float)):
                    entry[key] = bound.value
            out.append(entry)
        return out

    def parameter(self, name):
        for p in self.parameters:
            if p["name"] == name:
                return p
        return None

    # -- components ----------------------------------------------------------

    def _components(self):
        out = []
        for comp in self.model.components:
            role = comp.prop(naming.PROP_COMPONENT_ROLE).value
            order_p = comp.prop(naming.PROP_COMPONENT_ORDER)
            order = order_p.value if order_p and isinstance(order_p.value, int) else 0
            datum = self.model.component_datum(comp)
            if datum is None:
                raise JointError(f"{self.stem}: component {comp.label!r} is not "
                                 f"placed on a datum")
            if datum.label not in self.datum_face:
                raise JointError(f"{self.stem}: component {comp.label!r} sits on "
                                 f"{datum.label!r}, which is not one of the "
                                 f"paired datums")
            holder = self.model.component_placement_holder(comp)
            out.append({
                "label": comp.label,
                "name": comp.name,
                "role": role,
                "order": order,
                "datum": datum.label,
                "timber_role": self.model.datum_owner(datum).label,
                "mirrored_in_template": holder is not comp,
            })
        out.sort(key=lambda c: (c["order"], c["label"]))
        return out

    @property
    def is_starter(self):
        return not self.components

    def components_for(self, role):
        return [c for c in self.components if c["timber_role"] == role]

    def __repr__(self):
        return (f"TemplateSpec({self.stem}: roles {self.roles}, "
                f"{len(self.components)} component(s), "
                f"{len(self.parameters)} parameter(s))")
