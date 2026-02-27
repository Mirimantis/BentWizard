"""Joint definition discovery and registry.

Scans ``joints/builtin/`` for built-in definitions and the user joints
directory (``%APPDATA%/TimberFrame/joints/``) for user-defined definitions.
User definitions with the same ID override built-in ones.

This module must work headless — no FreeCADGui / Qt imports.
"""

import importlib
import importlib.util
import inspect
import os
import sys

import FreeCAD

from joints.base import TimberJointDefinition

# ---------------------------------------------------------------------------
# Module-level registry
# ---------------------------------------------------------------------------

_registry: dict = {}    # {id_string: TimberJointDefinition instance}
_loaded: bool = False

# Default joint type for each intersection type.
DEFAULT_JOINT_TYPES = {
    "EndpointToMidpoint": "through_mortise_tenon",
    "MidpointToMidpoint": "half_lap",
    "EndpointToEndpoint": "scarf_bladed",
}


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _get_builtin_dir() -> str:
    """Return the absolute path to ``joints/builtin/``."""
    return os.path.join(os.path.dirname(__file__), "builtin")


def _get_user_joints_dir() -> str:
    """Return the user joints directory path.

    On Windows: ``%APPDATA%/TimberFrame/joints/``.
    Creates the directory if it does not exist.
    """
    base = os.environ.get("APPDATA", os.path.expanduser("~"))
    user_dir = os.path.join(base, "TimberFrame", "joints")
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


def _discover_in_directory(directory: str) -> list:
    """Import all ``.py`` files in *directory* and return definition instances.

    Each file is loaded as an isolated module.  Every class found that is a
    direct subclass of :class:`TimberJointDefinition` (and has a non-empty
    ``ID``) is instantiated and returned.
    """
    definitions = []
    if not os.path.isdir(directory):
        return definitions

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        filepath = os.path.join(directory, filename)
        module_name = f"timber_joint_def_{filename[:-3]}"

        try:
            spec = importlib.util.spec_from_file_location(module_name,
                                                          filepath)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            # Temporarily add to sys.modules so relative imports work
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as exc:
            FreeCAD.Console.PrintWarning(
                f"Joint loader: failed to import {filepath}: {exc}\n"
            )
            sys.modules.pop(module_name, None)
            continue

        # Find TimberJointDefinition subclasses in the module.
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            if (cls is not TimberJointDefinition
                    and issubclass(cls, TimberJointDefinition)
                    and getattr(cls, "ID", "")):
                try:
                    definitions.append(cls())
                except Exception as exc:
                    FreeCAD.Console.PrintWarning(
                        f"Joint loader: failed to instantiate {cls}: {exc}\n"
                    )

        # Clean up sys.modules
        sys.modules.pop(module_name, None)

    return definitions


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_all() -> None:
    """Discover and register all joint definitions.

    Call once at workbench initialization.  Safe to call multiple times
    (clears the registry first).
    """
    global _loaded, _registry
    _registry.clear()

    # Built-in joints first.
    for defn in _discover_in_directory(_get_builtin_dir()):
        _registry[defn.ID] = defn
        FreeCAD.Console.PrintMessage(
            f"  Joint loaded: {defn.NAME} [{defn.ID}]\n"
        )

    # User joints (override built-in if same ID).
    user_dir = _get_user_joints_dir()
    for defn in _discover_in_directory(user_dir):
        _registry[defn.ID] = defn
        FreeCAD.Console.PrintMessage(
            f"  User joint loaded: {defn.NAME} [{defn.ID}]\n"
        )

    _loaded = True
    FreeCAD.Console.PrintMessage(
        f"Joint registry: {len(_registry)} definition(s) loaded\n"
    )


def get_definition(joint_type_id: str):
    """Look up a joint definition by ID.

    Returns ``None`` if not found.  Triggers lazy loading if
    :func:`load_all` hasn't been called yet.
    """
    if not _loaded:
        load_all()
    return _registry.get(joint_type_id)


def get_all_definitions() -> dict:
    """Return a copy of the full registry dict."""
    if not _loaded:
        load_all()
    return dict(_registry)


def get_ids() -> list:
    """Return a sorted list of all registered joint type IDs."""
    if not _loaded:
        load_all()
    return sorted(_registry.keys())


def get_suggested_types(intersection_type: str, primary_role: str,
                        secondary_role: str, angle: float) -> list:
    """Return compatible joint definition IDs for a given context.

    Filters by intersection type family, role compatibility, and angle range.

    Returns
    -------
    list[str]
        Joint ID strings, with the default type first if applicable.
    """
    if not _loaded:
        load_all()

    candidates = []
    default_id = DEFAULT_JOINT_TYPES.get(intersection_type)

    for jid, defn in _registry.items():
        # Angle range check.
        if angle < defn.MIN_ANGLE or angle > defn.MAX_ANGLE:
            continue
        # Role compatibility (empty list means "any role").
        if defn.PRIMARY_ROLES and primary_role not in defn.PRIMARY_ROLES:
            continue
        if defn.SECONDARY_ROLES and secondary_role not in defn.SECONDARY_ROLES:
            continue
        candidates.append(jid)

    # Put the default type first if it's in the candidate list.
    if default_id and default_id in candidates:
        candidates.remove(default_id)
        candidates.insert(0, default_id)

    return candidates
