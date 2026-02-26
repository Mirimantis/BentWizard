"""Joint definition base classes and data types.

This module defines the contract that every joint definition (built-in or
user-defined) must implement, plus the supporting data types used throughout
the joint system.

This module must work headless — no FreeCADGui / Qt imports.
"""

import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Joint Coordinate System
# ---------------------------------------------------------------------------

@dataclass
class JointCoordinateSystem:
    """Local coordinate system at a joint intersection.

    Derived purely from the datum line geometry of two members.

    Attributes
    ----------
    origin : FreeCAD.Vector
        Intersection point in world space.
    primary_axis : FreeCAD.Vector
        Unit direction of the primary member datum.
    secondary_axis : FreeCAD.Vector
        Unit direction of the secondary member datum.
    normal : FreeCAD.Vector
        Cross product of primary and secondary axes, normalized.
    angle : float
        Intersection angle in degrees (0–180).
    """

    origin: Any           # FreeCAD.Vector
    primary_axis: Any     # FreeCAD.Vector
    secondary_axis: Any   # FreeCAD.Vector
    normal: Any           # FreeCAD.Vector
    angle: float


# ---------------------------------------------------------------------------
# Parameter System
# ---------------------------------------------------------------------------

@dataclass
class JointParameter:
    """Single typed parameter for a joint definition.

    Attributes
    ----------
    name : str
        Machine-readable parameter name.
    param_type : str
        One of ``"length"``, ``"angle"``, ``"integer"``, ``"boolean"``,
        ``"enumeration"``.
    default_value : Any
        Value derived from member geometry (auto-calculated).
    value : Any
        Current effective value — equals *default_value* unless overridden.
    is_overridden : bool
        True if the user has set a custom value.
    min_value : Any
        Optional lower bound.
    max_value : Any
        Optional upper bound.
    enum_options : list
        Valid choices when *param_type* is ``"enumeration"``.
    group : str
        UI grouping label.
    description : str
        Tooltip text.
    """

    name: str
    param_type: str
    default_value: Any
    value: Any
    is_overridden: bool = False
    min_value: Any = None
    max_value: Any = None
    enum_options: list = field(default_factory=list)
    group: str = "General"
    description: str = ""


class ParameterSet:
    """Ordered collection of :class:`JointParameter` instances.

    Serializable to/from a JSON string for storage in
    ``App::PropertyString``.
    """

    def __init__(self, parameters: Optional[list] = None):
        self._params: dict = {}
        self._order: list = []
        if parameters:
            for p in parameters:
                self._params[p.name] = p
                self._order.append(p.name)

    # -- value access -------------------------------------------------------

    def get(self, name: str) -> Any:
        """Return the current effective value of a parameter."""
        return self._params[name].value

    def get_param(self, name: str) -> JointParameter:
        """Return the full :class:`JointParameter` object."""
        return self._params[name]

    def __contains__(self, name: str) -> bool:
        return name in self._params

    def items(self):
        """Yield ``(name, JointParameter)`` pairs in definition order."""
        for name in self._order:
            yield name, self._params[name]

    # -- override management ------------------------------------------------

    def set_override(self, name: str, value: Any) -> None:
        """Set a user override for a parameter, clamping to bounds."""
        p = self._params[name]
        if p.min_value is not None and value < p.min_value:
            value = p.min_value
        if p.max_value is not None and value > p.max_value:
            value = p.max_value
        p.value = value
        p.is_overridden = True

    def clear_override(self, name: str) -> None:
        """Revert a parameter to its derived default."""
        p = self._params[name]
        p.value = p.default_value
        p.is_overridden = False

    def update_defaults(self, new_defaults: dict) -> None:
        """Recalculate derived defaults.

        Parameters that the user has *not* overridden adopt the new default.
        Overridden parameters keep their user value.
        """
        for name, new_val in new_defaults.items():
            if name not in self._params:
                continue
            p = self._params[name]
            p.default_value = new_val
            if not p.is_overridden:
                p.value = new_val

    # -- JSON serialization -------------------------------------------------

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        data = []
        for name in self._order:
            p = self._params[name]
            data.append({
                "name": p.name,
                "param_type": p.param_type,
                "default_value": p.default_value,
                "value": p.value,
                "is_overridden": p.is_overridden,
                "min_value": p.min_value,
                "max_value": p.max_value,
                "enum_options": p.enum_options,
                "group": p.group,
                "description": p.description,
            })
        return json.dumps(data, separators=(",", ":"))

    @classmethod
    def from_json(cls, json_str: str) -> "ParameterSet":
        """Deserialize from a JSON string."""
        data = json.loads(json_str)
        params = []
        for d in data:
            params.append(JointParameter(
                name=d["name"],
                param_type=d["param_type"],
                default_value=d["default_value"],
                value=d["value"],
                is_overridden=d.get("is_overridden", False),
                min_value=d.get("min_value"),
                max_value=d.get("max_value"),
                enum_options=d.get("enum_options", []),
                group=d.get("group", "General"),
                description=d.get("description", ""),
            ))
        return cls(params)

    def __len__(self):
        return len(self._params)

    def __repr__(self):
        overrides = sum(1 for p in self._params.values() if p.is_overridden)
        return f"ParameterSet({len(self._params)} params, {overrides} overridden)"


# ---------------------------------------------------------------------------
# Joint Geometry Output Types
# ---------------------------------------------------------------------------

@dataclass
class SecondaryProfile:
    """Geometry output for the secondary (tenoned) member.

    Attributes
    ----------
    tenon_shape : Part.Shape
        The positive tenon geometry (for visualization).
    shoulder_cut : Part.Shape
        The boolean subtraction tool for cutting the secondary member.
    """

    tenon_shape: Any     # Part.Shape
    shoulder_cut: Any    # Part.Shape


@dataclass
class PegDefinition:
    """A single peg (drawbore pin) in a joint.

    All geometry is expressed in the joint local coordinate system.

    Attributes
    ----------
    center : FreeCAD.Vector
        Centre point in joint local CS.
    diameter : float
        Peg diameter in mm.
    length : float
        Peg length in mm.
    axis : FreeCAD.Vector
        Peg axis direction in joint local CS.
    offset : float
        Drawbore offset in mm (0 = no drawbore).
    """

    center: Any          # FreeCAD.Vector
    diameter: float
    length: float
    axis: Any            # FreeCAD.Vector
    offset: float = 0.0


@dataclass
class ValidationResult:
    """Single validation finding for a joint.

    Attributes
    ----------
    level : str
        One of ``"error"``, ``"warning"``, ``"info"``.
    message : str
        Human-readable description.
    code : str
        Machine-readable code like ``"TENON_TOO_THIN"``.
    """

    level: str
    message: str
    code: str = ""


@dataclass
class JointStructuralProperties:
    """Structural capacity values for a joint configuration.

    All values default to zero (unknown / not computed).
    """

    allowable_moment: float = 0.0       # N-mm
    allowable_shear: float = 0.0        # N
    rotational_stiffness: float = 0.0   # N-mm/rad


# ---------------------------------------------------------------------------
# Joint Definition Base Class
# ---------------------------------------------------------------------------

class TimberJointDefinition:
    """Abstract base class for all joint definitions.

    Subclass this and implement all methods to create a new joint type.
    Place the file in ``joints/builtin/`` for built-in joints, or in the
    user joints directory (``%APPDATA%/TimberFrame/joints/``).

    Class Attributes
    ----------------
    NAME : str
        Human-readable name (e.g. ``"Through Mortise and Tenon"``).
    ID : str
        Stable unique identifier (e.g. ``"through_mortise_tenon"``).
    CATEGORY : str
        Grouping category (e.g. ``"Mortise and Tenon"``).
    DESCRIPTION : str
        Short description of the joint.
    ICON : str
        Path to icon file, relative to the definition file.
    DIAGRAM : str
        Path to diagram file, relative to the definition file.
    PRIMARY_ROLES : list[str]
        Compatible roles for the primary (housing) member.
    SECONDARY_ROLES : list[str]
        Compatible roles for the secondary (tenoned) member.
    MIN_ANGLE : float
        Minimum intersection angle in degrees.
    MAX_ANGLE : float
        Maximum intersection angle in degrees.
    """

    NAME = ""
    ID = ""
    CATEGORY = ""
    DESCRIPTION = ""
    ICON = ""
    DIAGRAM = ""
    PRIMARY_ROLES: list = []
    SECONDARY_ROLES: list = []
    MIN_ANGLE = 45.0
    MAX_ANGLE = 135.0

    def get_parameters(self, primary, secondary,
                       joint_cs: JointCoordinateSystem) -> ParameterSet:
        """Return a :class:`ParameterSet` with derived defaults.

        Parameters
        ----------
        primary : FreeCAD document object
            The primary (housing) TimberMember.
        secondary : FreeCAD document object
            The secondary (tenoned) TimberMember.
        joint_cs : JointCoordinateSystem
            The local coordinate system at the intersection.
        """
        raise NotImplementedError

    def build_primary_tool(self, params: ParameterSet, primary, secondary,
                           joint_cs: JointCoordinateSystem) -> Any:
        """Return the ``Part.Shape`` to boolean-subtract from the primary member.

        This is the mortise or housing cut.
        """
        raise NotImplementedError

    def build_secondary_profile(self, params: ParameterSet, primary, secondary,
                                joint_cs: JointCoordinateSystem) -> SecondaryProfile:
        """Return the :class:`SecondaryProfile` for the secondary member.

        Includes the tenon shape (for visualization) and the shoulder cut
        (for boolean subtraction from the secondary member).
        """
        raise NotImplementedError

    def build_pegs(self, params: ParameterSet, primary, secondary,
                   joint_cs: JointCoordinateSystem) -> list:
        """Return a list of :class:`PegDefinition` instances.

        May return an empty list if the joint has no pegs.
        """
        return []

    def validate(self, params: ParameterSet, primary, secondary,
                 joint_cs: JointCoordinateSystem) -> list:
        """Return a list of :class:`ValidationResult` instances."""
        return []

    def fabrication_signature(self, params: ParameterSet, primary, secondary,
                              joint_cs: JointCoordinateSystem) -> dict:
        """Return a dict of normalized values for fabrication identity.

        Two joints with identical fabrication signatures on members with
        identical fabrication signatures produce identical cuts.
        """
        return {}

    def structural_properties(self, params: ParameterSet,
                              primary, secondary) -> JointStructuralProperties:
        """Return the structural capacity of this joint configuration."""
        return JointStructuralProperties()
