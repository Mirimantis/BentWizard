"""Built-in bent templates for the Bent Designer.

Each template defines member roles and positions using fractional
coordinates (0.0–1.0) that are scaled to the user's specified span
and total height when applied.

Primary (through) members extend past their connection points by ~0.1
in fractional coordinates so that secondary endpoints always land at
the primary's midpoint, never endpoint-to-endpoint.  This ensures the
intersection detector classifies every joint as EndpointToMidpoint
(or MidpointToMidpoint), which is required for valid joinery geometry.

Joints are specified as index pairs referencing the ``members`` list.
Primary/secondary assignment is handled by the intersection detection
code at application time — the template only declares which pairs
connect.

This module must work headless — no FreeCADGui / Qt imports.
"""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class TemplateMember:
    """One member in a bent template.

    Coordinates are fractions of the bent's span (X) and total
    height (Z), where (0, 0) is bottom-left and (1, 1) is top-right.
    Primary members may extend outside this range to provide
    overshoot past connection points.
    """
    role: str
    start: Tuple[float, float]   # (x_frac, z_frac)
    end: Tuple[float, float]     # (x_frac, z_frac)
    width: float = 150.0         # mm — default section
    height: float = 200.0        # mm — default section


@dataclass
class TemplateJoint:
    """A joint between two members in a bent template.

    Indices reference the ``members`` list of the parent template.
    """
    member_a: int
    member_b: int


@dataclass
class BentTemplate:
    """A reusable bent profile definition."""
    name: str
    description: str
    members: List[TemplateMember] = field(default_factory=list)
    joints: List[TemplateJoint] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------

#   King Post
#   =========
#   0: Left Post       (0, 0) → (0, 0.5)
#   1: Right Post      (1, 0) → (1, 0.5)
#   2: Tie Beam        (-0.1, 0.5) → (1.1, 0.5)      [extended past posts]
#   3: Left Rafter     (0, 0.5) → (0.5, 1)
#   4: Right Rafter    (1, 0.5) → (0.5, 1)
#   5: King Post       (0.5, 0.5) → (0.5, 1.1)        [extended past ridge]

KING_POST = BentTemplate(
    name="King Post",
    description="Triangular truss with a central vertical king post",
    members=[
        TemplateMember("Post",    (0.0, 0.0), (0.0, 0.5)),        # 0
        TemplateMember("Post",    (1.0, 0.0), (1.0, 0.5)),        # 1
        TemplateMember("TieBeam", (-0.1, 0.5), (1.1, 0.5)),       # 2  extended
        TemplateMember("Rafter",  (0.0, 0.5), (0.5, 1.0)),        # 3
        TemplateMember("Rafter",  (1.0, 0.5), (0.5, 1.0)),        # 4
        TemplateMember("Post",    (0.5, 0.5), (0.5, 1.1), 150, 150),  # 5  extended
    ],
    joints=[
        TemplateJoint(0, 2),   # left post → tie beam
        TemplateJoint(1, 2),   # right post → tie beam
        TemplateJoint(3, 2),   # left rafter → tie beam
        TemplateJoint(4, 2),   # right rafter → tie beam
        TemplateJoint(5, 2),   # king post → tie beam
        TemplateJoint(3, 5),   # left rafter → king post (at ridge)
        TemplateJoint(4, 5),   # right rafter → king post (at ridge)
    ],
)

#   Queen Post
#   ==========
#   0: Left Post       (0, 0) → (0, 0.5)
#   1: Right Post      (1, 0) → (1, 0.5)
#   2: Tie Beam        (-0.1, 0.5) → (1.1, 0.5)       [extended past posts]
#   3: Left Rafter     (0, 0.5) → (0.571, 1.071)       [extended past ridge]
#   4: Right Rafter    (1, 0.5) → (0.5, 1)
#   5: Left Queen Post (0.333, 0.5) → (0.333, 0.833)
#   6: Right Queen Post(0.667, 0.5) → (0.667, 0.833)
#   7: Girt            (0.233, 0.833) → (0.767, 0.833) [extended past QPs]

QUEEN_POST = BentTemplate(
    name="Queen Post",
    description="Truss with two vertical queen posts at the third points",
    members=[
        TemplateMember("Post",    (0.0,   0.0),   (0.0,   0.5)),        # 0
        TemplateMember("Post",    (1.0,   0.0),   (1.0,   0.5)),        # 1
        TemplateMember("TieBeam", (-0.1,  0.5),   (1.1,   0.5)),        # 2  extended
        TemplateMember("Rafter",  (0.0,   0.5),   (0.571, 1.071)),      # 3  extended past ridge
        TemplateMember("Rafter",  (1.0,   0.5),   (0.5,   1.0)),        # 4
        TemplateMember("Post",    (0.333, 0.5),   (0.333, 0.833), 150, 150),  # 5
        TemplateMember("Post",    (0.667, 0.5),   (0.667, 0.833), 150, 150),  # 6
        TemplateMember("Girt",    (0.233, 0.833), (0.767, 0.833), 150, 150),  # 7  extended
    ],
    joints=[
        TemplateJoint(0, 2),   # left post → tie beam
        TemplateJoint(1, 2),   # right post → tie beam
        TemplateJoint(3, 2),   # left rafter → tie beam
        TemplateJoint(4, 2),   # right rafter → tie beam
        TemplateJoint(5, 2),   # left queen post → tie beam
        TemplateJoint(6, 2),   # right queen post → tie beam
        TemplateJoint(5, 7),   # left queen post → girt
        TemplateJoint(6, 7),   # right queen post → girt
        TemplateJoint(3, 5),   # left rafter → left queen post (rafter over QP top)
        TemplateJoint(4, 6),   # right rafter → right queen post
        TemplateJoint(3, 4),   # left rafter → right rafter (ridge)
    ],
)

#   Hammer Beam
#   ===========
#   0: Left Post       (0, 0) → (0, 0.5)
#   1: Right Post      (1, 0) → (1, 0.5)
#   2: Tie Beam        (-0.1, 0.5) → (1.1, 0.5)       [extended past posts]
#   3: Left HB         (0, 0.55) → (0.3, 0.55)         [extended past HP]
#   4: Right HB        (1, 0.55) → (0.7, 0.55)         [extended past HP]
#   5: Left HP         (0.2, 0.55) → (0.2, 0.75)
#   6: Right HP        (0.8, 0.55) → (0.8, 0.75)
#   7: Left Rafter     (0.123, 0.686) → (0.577, 1.064) [extended both ends]
#   8: Right Rafter    (0.8, 0.75) → (0.5, 1)
#   9: Left Brace      (0, 0.35) → (0.2, 0.55)
#  10: Right Brace     (1, 0.35) → (0.8, 0.55)

HAMMER_BEAM = BentTemplate(
    name="Hammer Beam",
    description="Open truss with hammer beams projecting from the posts",
    members=[
        TemplateMember("Post",    (0.0,   0.0),   (0.0,   0.5)),            # 0
        TemplateMember("Post",    (1.0,   0.0),   (1.0,   0.5)),            # 1
        TemplateMember("TieBeam", (-0.1,  0.5),   (1.1,   0.5)),            # 2  extended
        TemplateMember("Beam",    (0.0,   0.55),  (0.3,   0.55), 150, 200), # 3  extended
        TemplateMember("Beam",    (1.0,   0.55),  (0.7,   0.55), 150, 200), # 4  extended
        TemplateMember("Post",    (0.2,   0.55),  (0.2,   0.75), 150, 150), # 5
        TemplateMember("Post",    (0.8,   0.55),  (0.8,   0.75), 150, 150), # 6
        TemplateMember("Rafter",  (0.123, 0.686), (0.577, 1.064)),           # 7  extended both ends
        TemplateMember("Rafter",  (0.8,   0.75),  (0.5,   1.0)),            # 8
        TemplateMember("Brace",   (0.0,   0.35),  (0.2,   0.55), 150, 150), # 9
        TemplateMember("Brace",   (1.0,   0.35),  (0.8,   0.55), 150, 150), # 10
    ],
    joints=[
        TemplateJoint(0, 2),    # left post → tie beam
        TemplateJoint(1, 2),    # right post → tie beam
        TemplateJoint(9, 0),    # left brace → left post (midpoint)
        TemplateJoint(10, 1),   # right brace → right post (midpoint)
        TemplateJoint(9, 3),    # left brace → left hammer beam
        TemplateJoint(10, 4),   # right brace → right hammer beam
        TemplateJoint(5, 3),    # left hammer post → left hammer beam
        TemplateJoint(6, 4),    # right hammer post → right hammer beam
        TemplateJoint(7, 5),    # left rafter → left hammer post
        TemplateJoint(8, 6),    # right rafter → right hammer post
        TemplateJoint(7, 8),    # left rafter → right rafter (ridge)
    ],
)

#   Scissors Truss
#   ==============
#   0: Left Post       (0, 0) → (0, 0.5)
#   1: Right Post      (1, 0) → (1, 0.5)
#   2: Tie Beam        (-0.1, 0.5) → (1.1, 0.5)       [extended past posts]
#   3: Left Rafter     (0, 0.5) → (0.571, 1.071)       [extended past ridge]
#   4: Right Rafter    (1, 0.5) → (0.5, 1)
#   5: Left Scissor    (0, 0.5) → (0.75, 0.75)
#   6: Right Scissor   (1, 0.5) → (0.25, 0.75)

SCISSORS_TRUSS = BentTemplate(
    name="Scissors Truss",
    description="Open truss with two crossing scissor members",
    members=[
        TemplateMember("Post",    (0.0, 0.0), (0.0, 0.5)),        # 0
        TemplateMember("Post",    (1.0, 0.0), (1.0, 0.5)),        # 1
        TemplateMember("TieBeam", (-0.1, 0.5), (1.1, 0.5)),       # 2  extended
        TemplateMember("Rafter",  (0.0, 0.5), (0.571, 1.071)),    # 3  extended past ridge
        TemplateMember("Rafter",  (1.0, 0.5), (0.5, 1.0)),        # 4
        TemplateMember("Beam",    (0.0, 0.5), (0.75, 0.75), 150, 150),  # 5
        TemplateMember("Beam",    (1.0, 0.5), (0.25, 0.75), 150, 150),  # 6
    ],
    joints=[
        TemplateJoint(0, 2),   # left post → tie beam
        TemplateJoint(1, 2),   # right post → tie beam
        TemplateJoint(3, 2),   # left rafter → tie beam
        TemplateJoint(4, 2),   # right rafter → tie beam
        TemplateJoint(5, 2),   # left scissor → tie beam
        TemplateJoint(6, 2),   # right scissor → tie beam
        TemplateJoint(3, 4),   # left rafter → right rafter (ridge)
        TemplateJoint(5, 6),   # left scissor → right scissor (crossing)
        TemplateJoint(5, 4),   # left scissor → right rafter (endpoint to midpoint)
        TemplateJoint(6, 3),   # right scissor → left rafter (endpoint to midpoint)
    ],
)

# Ordered list for UI dropdowns.
BUILTIN_TEMPLATES = [KING_POST, QUEEN_POST, HAMMER_BEAM, SCISSORS_TRUSS]
