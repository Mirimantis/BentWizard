"""Built-in bent templates for the Bent Designer.

Each template defines member roles and positions using fractional
coordinates (0.0–1.0) that are scaled to the user's specified span
and total height when applied.

This module must work headless — no FreeCADGui / Qt imports.
"""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class TemplateMember:
    """One member in a bent template.

    Coordinates are fractions of the bent's span (X) and total
    height (Z), where (0, 0) is bottom-left and (1, 1) is top-right.
    """
    role: str
    start: Tuple[float, float]   # (x_frac, z_frac)
    end: Tuple[float, float]     # (x_frac, z_frac)
    width: float = 150.0         # mm — default section
    height: float = 200.0        # mm — default section


@dataclass
class BentTemplate:
    """A reusable bent profile definition."""
    name: str
    description: str
    members: List[TemplateMember] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------

KING_POST = BentTemplate(
    name="King Post",
    description="Triangular truss with a central vertical king post",
    members=[
        TemplateMember("Post",    (0.0, 0.0), (0.0, 0.5)),
        TemplateMember("Post",    (1.0, 0.0), (1.0, 0.5)),
        TemplateMember("TieBeam", (0.0, 0.5), (1.0, 0.5)),
        TemplateMember("Rafter",  (0.0, 0.5), (0.5, 1.0)),
        TemplateMember("Rafter",  (1.0, 0.5), (0.5, 1.0)),
        TemplateMember("Post",    (0.5, 0.5), (0.5, 1.0), 150, 150),
    ],
)

QUEEN_POST = BentTemplate(
    name="Queen Post",
    description="Truss with two vertical queen posts at the third points",
    members=[
        TemplateMember("Post",    (0.0,   0.0),   (0.0,   0.5)),
        TemplateMember("Post",    (1.0,   0.0),   (1.0,   0.5)),
        TemplateMember("TieBeam", (0.0,   0.5),   (1.0,   0.5)),
        TemplateMember("Rafter",  (0.0,   0.5),   (0.5,   1.0)),
        TemplateMember("Rafter",  (1.0,   0.5),   (0.5,   1.0)),
        TemplateMember("Post",    (0.333, 0.5),   (0.333, 0.833), 150, 150),
        TemplateMember("Post",    (0.667, 0.5),   (0.667, 0.833), 150, 150),
        TemplateMember("Girt",    (0.333, 0.833), (0.667, 0.833), 150, 150),
    ],
)

HAMMER_BEAM = BentTemplate(
    name="Hammer Beam",
    description="Open truss with hammer beams projecting from the posts",
    members=[
        TemplateMember("Post",    (0.0,  0.0),  (0.0,  0.5)),
        TemplateMember("Post",    (1.0,  0.0),  (1.0,  0.5)),
        TemplateMember("TieBeam", (0.0,  0.5),  (1.0,  0.5)),
        # Hammer beams projecting inward from post tops
        TemplateMember("Beam",    (0.0,  0.55), (0.2,  0.55), 150, 200),
        TemplateMember("Beam",    (1.0,  0.55), (0.8,  0.55), 150, 200),
        # Hammer posts rising from hammer beam ends
        TemplateMember("Post",    (0.2,  0.55), (0.2,  0.75), 150, 150),
        TemplateMember("Post",    (0.8,  0.55), (0.8,  0.75), 150, 150),
        # Rafters from hammer post tops to ridge
        TemplateMember("Rafter",  (0.2,  0.75), (0.5,  1.0)),
        TemplateMember("Rafter",  (0.8,  0.75), (0.5,  1.0)),
        # Braces from posts to hammer beams
        TemplateMember("Brace",   (0.0,  0.35), (0.2,  0.55), 150, 150),
        TemplateMember("Brace",   (1.0,  0.35), (0.8,  0.55), 150, 150),
    ],
)

SCISSORS_TRUSS = BentTemplate(
    name="Scissors Truss",
    description="Open truss with two crossing scissor members",
    members=[
        TemplateMember("Post",    (0.0, 0.0), (0.0, 0.5)),
        TemplateMember("Post",    (1.0, 0.0), (1.0, 0.5)),
        TemplateMember("TieBeam", (0.0, 0.5), (1.0, 0.5)),
        TemplateMember("Rafter",  (0.0, 0.5), (0.5, 1.0)),
        TemplateMember("Rafter",  (1.0, 0.5), (0.5, 1.0)),
        # Scissors: cross from each plate to opposite rafter midpoint
        TemplateMember("Beam",    (0.0, 0.5), (0.75, 0.75), 150, 150),
        TemplateMember("Beam",    (1.0, 0.5), (0.25, 0.75), 150, 150),
    ],
)

# Ordered list for UI dropdowns.
BUILTIN_TEMPLATES = [KING_POST, QUEEN_POST, HAMMER_BEAM, SCISSORS_TRUSS]
