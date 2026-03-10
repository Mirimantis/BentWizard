"""Bent Designer — 2D elevation editor for bent profiles.

Opens as an MDI tab (TechDraw-style) in FreeCAD's central area.
Provides a QGraphicsScene canvas where members are shown as oriented
rectangles, endpoints are draggable with snapping, and built-in
templates can be applied.

This is a UI module — FreeCAD imports are deferred to methods.
"""

import math

from PySide2 import QtCore, QtGui, QtWidgets


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLE_COLORS = {
    "Post":       QtGui.QColor(139, 90, 43),
    "Beam":       QtGui.QColor(210, 180, 140),
    "TieBeam":    QtGui.QColor(210, 180, 140),
    "Rafter":     QtGui.QColor(178, 34, 34),
    "Purlin":     QtGui.QColor(205, 133, 63),
    "Girt":       QtGui.QColor(160, 82, 45),
    "Brace":      QtGui.QColor(60, 120, 60),
    "Plate":      QtGui.QColor(188, 143, 143),
    "Ridge":      QtGui.QColor(128, 0, 0),
    "Sill":       QtGui.QColor(160, 130, 100),
    "Header":     QtGui.QColor(180, 140, 100),
    "Trimmer":    QtGui.QColor(170, 130, 90),
    "FloorJoist": QtGui.QColor(200, 170, 130),
    "SummerBeam": QtGui.QColor(190, 160, 120),
    "Valley":     QtGui.QColor(150, 50, 50),
}

DEFAULT_MEMBER_COLOR = QtGui.QColor(180, 180, 180)

HANDLE_COLOR = QtGui.QColor(30, 120, 220)
HANDLE_HOVER_COLOR = QtGui.QColor(255, 180, 0)
SNAP_ENDPOINT_COLOR = QtGui.QColor(0, 200, 0)
SNAP_ALIGN_COLOR = QtGui.QColor(0, 100, 255, 120)
SNAP_DATUM_COLOR = QtGui.QColor(255, 160, 0, 150)

HANDLE_RADIUS = 8.0
SNAP_TOLERANCE = 20.0
DATUM_SNAP_TOLERANCE = 30.0   # wider catch radius for datum-aligned snap
DATUM_LINE_COLOR = QtGui.QColor(255, 255, 255, 200)
GRID_DEFAULT_SPACING = 50.0
CLUSTER_TOLERANCE = 1.0   # mm — endpoints within this form a cluster

ZOOM_MIN = 0.05
ZOOM_MAX = 20.0
ZOOM_FACTOR = 1.15


# ---------------------------------------------------------------------------
# FreeCAD viewport background colour
# ---------------------------------------------------------------------------

def _get_freecad_bg_color():
    """Read the 3D viewport background colour from FreeCAD preferences.

    Returns the bottom gradient colour (what the user sees most of)
    when a gradient is active, otherwise the solid background colour.
    Falls back to a neutral dark grey if the preference cannot be read.
    """
    try:
        import FreeCAD
        p = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View")
        is_gradient = p.GetBool("Gradient")
        if is_gradient:
            val = p.GetUnsigned("BackgroundColor3")   # bottom of gradient
        else:
            val = p.GetUnsigned("BackgroundColor")
        r = (val >> 24) & 0xFF
        g = (val >> 16) & 0xFF
        b = (val >> 8) & 0xFF
        return QtGui.QColor(r, g, b)
    except Exception:
        return QtGui.QColor(45, 45, 50)


def _grid_colors_for_bg(bg):
    """Return (minor_pen_color, major_pen_color) that contrast with *bg*.

    Alpha values are chosen to give a contrast ratio of ~1.5 for minor
    lines and ~2.0 for major lines against the background.  Cosmetic
    1-pixel lines need higher alpha than filled shapes to be legible.
    """
    lum = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
    if lum < 128:
        # Dark background → white grid lines
        return (QtGui.QColor(255, 255, 255, 80),
                QtGui.QColor(255, 255, 255, 130))
    # Light background → black grid lines
    return (QtGui.QColor(0, 0, 0, 90),
            QtGui.QColor(0, 0, 0, 140))


# ---------------------------------------------------------------------------
# ProjectionPlane
# ---------------------------------------------------------------------------

class ProjectionPlane:
    """Derives the best-fit 2D plane from member datum endpoints.

    Uses axis-aligned plane detection (smallest coordinate range is
    the normal axis).  Falls back to XZ when fewer than 3 points or
    when all points are coincident.

    NOTE: For non-axis-aligned bents, this could be extended to full
    PCA (covariance matrix + eigenvectors).  Axis-aligned detection
    covers all standard timber frame bents.
    """

    def __init__(self):
        self.origin = None   # FreeCAD.Vector — centroid of all endpoints
        self.u_axis = None   # horizontal in 2D
        self.v_axis = None   # vertical in 2D
        self.w_axis = None   # normal (into screen)

    def fit(self, points_3d):
        """Compute the projection plane from a list of 3D points.

        Parameters
        ----------
        points_3d : list of FreeCAD.Vector
            Datum endpoints.  May be empty.
        """
        import FreeCAD

        if not points_3d:
            self._set_default_xz()
            return

        n = len(points_3d)
        cx = sum(p.x for p in points_3d) / n
        cy = sum(p.y for p in points_3d) / n
        cz = sum(p.z for p in points_3d) / n
        self.origin = FreeCAD.Vector(cx, cy, cz)

        if n < 2:
            self._set_default_xz()
            self.origin = FreeCAD.Vector(cx, cy, cz)
            return

        xs = [p.x for p in points_3d]
        ys = [p.y for p in points_3d]
        zs = [p.z for p in points_3d]

        rx = max(xs) - min(xs)
        ry = max(ys) - min(ys)
        rz = max(zs) - min(zs)

        # The axis with the least variation is the normal.
        # Prefer Y as normal on ties (most common for timber bents).
        if ry <= rx and ry <= rz:
            self._set_axes_xz(FreeCAD)
        elif rx <= rz:
            self._set_axes_yz(FreeCAD)
        else:
            self._set_axes_xy(FreeCAD)

    # -- axis presets -------------------------------------------------------

    def _set_default_xz(self):
        import FreeCAD
        self.origin = FreeCAD.Vector(0, 0, 0)
        self._set_axes_xz(FreeCAD)

    @staticmethod
    def _vec(fc, x, y, z):
        return fc.Vector(x, y, z)

    def _set_axes_xz(self, fc):
        self.u_axis = fc.Vector(1, 0, 0)
        self.v_axis = fc.Vector(0, 0, 1)
        self.w_axis = fc.Vector(0, 1, 0)

    def _set_axes_yz(self, fc):
        self.u_axis = fc.Vector(0, 1, 0)
        self.v_axis = fc.Vector(0, 0, 1)
        self.w_axis = fc.Vector(1, 0, 0)

    def _set_axes_xy(self, fc):
        self.u_axis = fc.Vector(1, 0, 0)
        self.v_axis = fc.Vector(0, 1, 0)
        self.w_axis = fc.Vector(0, 0, 1)

    # -- projection ---------------------------------------------------------

    def project(self, vec3d):
        """Project a 3D point to 2D scene coordinates (QPointF).

        Scene X = horizontal, scene Y = negated vertical (Qt Y-down,
        but we want "up" to be visually upward).
        """
        d = vec3d - self.origin
        u = d.dot(self.u_axis)
        v = d.dot(self.v_axis)
        return QtCore.QPointF(u, -v)

    def unproject(self, pt2d):
        """Map a 2D scene point back to 3D on the projection plane.

        Parameters
        ----------
        pt2d : QPointF
            Scene coordinates.

        Returns
        -------
        FreeCAD.Vector
        """
        u = pt2d.x()
        v = -pt2d.y()  # un-negate
        return (self.origin
                + self.u_axis * u
                + self.v_axis * v)


# ---------------------------------------------------------------------------
# SnapResult / SnapEngine
# ---------------------------------------------------------------------------

class SnapResult:
    """Result of a snap operation."""
    __slots__ = ("point", "snap_type", "alignment_ref")

    def __init__(self, point, snap_type="free", alignment_ref=None):
        self.point = point            # QPointF — snapped position
        self.snap_type = snap_type    # "endpoint" | "alignment_h" | etc.
        self.alignment_ref = alignment_ref  # QPointF for guide lines


class SnapEngine:
    """Combined snap system: endpoint > alignment > datum > grid > free.

    Shift key suppresses all snapping.
    """

    def __init__(self):
        self.grid_spacing = GRID_DEFAULT_SPACING
        self.grid_enabled = True
        self.endpoint_enabled = True
        self.alignment_enabled = True
        self.datum_enabled = True
        self._endpoints = []  # list of QPointF
        self._datums = []     # list of (QPointF, QPointF, member_name)

    def set_endpoints(self, points):
        """Set the available snap target positions."""
        self._endpoints = list(points)

    def set_datums(self, segments):
        """Set datum line segments for datum-aligned snapping.

        Parameters
        ----------
        segments : list of (QPointF, QPointF, str)
            Each tuple is (start_2d, end_2d, member_name).
        """
        self._datums = list(segments)

    def combined_snap(self, pos, exclude_positions=None,
                      exclude_members=None):
        """Apply snap to *pos*.  Returns a SnapResult.

        Parameters
        ----------
        pos : QPointF
            Proposed position in scene coordinates.
        exclude_positions : set of (float, float) or None
            Positions to skip (rounded to 0.1 mm precision).
        exclude_members : set of str or None
            Member Names whose datums should be skipped.
        """
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        if modifiers & QtCore.Qt.ShiftModifier:
            return SnapResult(pos, "free")

        if exclude_positions is None:
            exclude_positions = set()
        if exclude_members is None:
            exclude_members = set()

        # 1. Endpoint snap — nearest existing endpoint within tolerance
        if self.endpoint_enabled:
            best_dist = SNAP_TOLERANCE
            best_pt = None
            for ep in self._endpoints:
                key = (round(ep.x(), 1), round(ep.y(), 1))
                if key in exclude_positions:
                    continue
                dx = pos.x() - ep.x()
                dy = pos.y() - ep.y()
                dist = math.hypot(dx, dy)
                if dist < best_dist:
                    best_dist = dist
                    best_pt = ep
            if best_pt is not None:
                return SnapResult(
                    QtCore.QPointF(best_pt), "endpoint"
                )

        # 2. Alignment snap — H/V alignment with other endpoints
        if self.alignment_enabled:
            best_h_dist = SNAP_TOLERANCE
            best_h_y = None
            best_h_ref = None
            best_v_dist = SNAP_TOLERANCE
            best_v_x = None
            best_v_ref = None

            for ep in self._endpoints:
                key = (round(ep.x(), 1), round(ep.y(), 1))
                if key in exclude_positions:
                    continue
                dy = abs(pos.y() - ep.y())
                if dy < best_h_dist:
                    best_h_dist = dy
                    best_h_y = ep.y()
                    best_h_ref = ep
                dx = abs(pos.x() - ep.x())
                if dx < best_v_dist:
                    best_v_dist = dx
                    best_v_x = ep.x()
                    best_v_ref = ep

            result_x = pos.x()
            result_y = pos.y()
            snap_type = "free"
            alignment_ref = None

            if best_v_x is not None:
                result_x = best_v_x
                snap_type = "alignment_v"
                alignment_ref = best_v_ref
            if best_h_y is not None:
                result_y = best_h_y
                if snap_type == "free":
                    snap_type = "alignment_h"
                else:
                    snap_type = "alignment_hv"
                if alignment_ref is None:
                    alignment_ref = best_h_ref

            if snap_type != "free":
                return SnapResult(
                    QtCore.QPointF(result_x, result_y),
                    snap_type, alignment_ref,
                )

        # 3. Datum snap — grid-spaced ticks along other members' datums
        #    Activation uses perpendicular distance to the datum line
        #    (not total distance to the tick mark), so the snap engages
        #    reliably regardless of datum orientation.
        if self.datum_enabled and self.grid_spacing > 0:
            gs = self.grid_spacing
            best_perp = DATUM_SNAP_TOLERANCE
            best_datum_pt = None
            best_datum_dir = None  # (dx, dy) unit vector along datum

            for p0, p1, name in self._datums:
                if name in exclude_members:
                    continue
                # Direction vector and squared length
                ddx = p1.x() - p0.x()
                ddy = p1.y() - p0.y()
                len_sq = ddx * ddx + ddy * ddy
                if len_sq < 1.0:
                    continue
                length = math.sqrt(len_sq)

                # Project pos onto the datum segment
                t = ((pos.x() - p0.x()) * ddx
                     + (pos.y() - p0.y()) * ddy) / len_sq
                t = max(0.0, min(1.0, t))

                # Perpendicular distance to segment
                closest_x = p0.x() + t * ddx
                closest_y = p0.y() + t * ddy
                perp_dist = math.hypot(
                    pos.x() - closest_x, pos.y() - closest_y
                )
                if perp_dist >= DATUM_SNAP_TOLERANCE:
                    continue

                # Snap to nearest grid tick along datum
                dist_along = t * length
                snapped_dist = round(dist_along / gs) * gs
                snapped_dist = max(0.0, min(length, snapped_dist))
                t_snap = snapped_dist / length

                snap_x = p0.x() + t_snap * ddx
                snap_y = p0.y() + t_snap * ddy

                # Rank by perpendicular distance (closeness to the
                # datum line), not total distance to the tick mark.
                if perp_dist < best_perp:
                    best_perp = perp_dist
                    best_datum_pt = QtCore.QPointF(snap_x, snap_y)
                    best_datum_dir = (ddx / length, ddy / length)

            if best_datum_pt is not None:
                return SnapResult(
                    best_datum_pt, "datum", best_datum_dir
                )

        # 4. Grid snap
        if self.grid_enabled and self.grid_spacing > 0:
            gs = self.grid_spacing
            gx = round(pos.x() / gs) * gs
            gy = round(pos.y() / gs) * gs
            return SnapResult(QtCore.QPointF(gx, gy), "grid")

        # 5. Free
        return SnapResult(pos, "free")


# ---------------------------------------------------------------------------
# MemberItem
# ---------------------------------------------------------------------------

class MemberItem(QtWidgets.QGraphicsRectItem):
    """Oriented rectangle representing one timber member.

    Positioned at the datum midpoint, rotated to match datum angle.
    Colored by role.  MemberID label at center.

    Stores its 2D endpoint positions so that HandleItem can update
    the rectangle live during drag without touching FreeCAD data.
    """

    def __init__(self, member_obj, projection):
        super().__init__()
        self._member = member_obj
        self._start_2d = QtCore.QPointF()
        self._end_2d = QtCore.QPointF()
        self._visible_depth = 0.0
        self._label = None
        self._datum_line = None
        self._setup(projection)

    def _setup(self, projection):
        import FreeCAD
        from objects.TimberMember import TimberMember

        start_3d = FreeCAD.Vector(self._member.A_StartPoint)
        end_3d = FreeCAD.Vector(self._member.B_EndPoint)

        self._start_2d = projection.project(start_3d)
        self._end_2d = projection.project(end_3d)

        # Determine visible depth (cross-section dim NOT along view normal)
        _, _x, y_axis, z_axis = TimberMember.get_member_local_cs(
            self._member
        )
        w = float(self._member.Width)
        h = float(self._member.Height)

        if abs(y_axis.dot(projection.w_axis)) > abs(
            z_axis.dot(projection.w_axis)
        ):
            self._visible_depth = h
        else:
            self._visible_depth = w

        # Datum centerline — child item in local coordinates.
        # Runs along y=0 from -length/2 to +length/2, so it
        # follows the parent's position and rotation automatically.
        self._datum_line = QtWidgets.QGraphicsLineItem(self)
        self._datum_line.setPen(QtGui.QPen(
            DATUM_LINE_COLOR, 1, QtCore.Qt.DashDotLine,
        ))

        self._update_geometry()

        # Color by role
        role = str(getattr(self._member, "Role", ""))
        color = ROLE_COLORS.get(role, DEFAULT_MEMBER_COLOR)
        self.setBrush(QtGui.QBrush(color))
        self.setPen(QtGui.QPen(color.darker(150), 1))
        self.setOpacity(0.8)
        self.setZValue(1)

        # MemberID label
        mid_str = getattr(self._member, "MemberID", "") or self._member.Label
        if mid_str:
            self._label = QtWidgets.QGraphicsSimpleTextItem(mid_str, self)
            self._label.setBrush(QtGui.QBrush(QtCore.Qt.white))
            font = self._label.font()
            font.setPointSize(8)
            font.setBold(True)
            self._label.setFont(font)
            self._update_label_position()

    def _update_geometry(self):
        """Recompute rect position, rotation, and size from stored 2D endpoints."""
        dx = self._end_2d.x() - self._start_2d.x()
        dy = self._end_2d.y() - self._start_2d.y()
        length_2d = math.hypot(dx, dy)
        angle_deg = math.degrees(math.atan2(dy, dx))

        if length_2d < 1.0:
            length_2d = 10.0

        self.setRect(
            -length_2d / 2, -self._visible_depth / 2,
            length_2d, self._visible_depth,
        )

        mid_x = (self._start_2d.x() + self._end_2d.x()) / 2
        mid_y = (self._start_2d.y() + self._end_2d.y()) / 2
        self.setPos(mid_x, mid_y)
        self.setRotation(angle_deg)

        if self._datum_line is not None:
            overshoot = HANDLE_RADIUS
            self._datum_line.setLine(
                -length_2d / 2 - overshoot, 0,
                length_2d / 2 + overshoot, 0,
            )

        if self._label is not None:
            self._update_label_position()

    def _update_label_position(self):
        """Center the label and flip for readability when member points left."""
        br = self._label.boundingRect()
        self._label.setPos(-br.width() / 2, -br.height() / 2)

        dx = self._end_2d.x() - self._start_2d.x()
        dy = self._end_2d.y() - self._start_2d.y()
        angle_deg = math.degrees(math.atan2(dy, dx))
        if angle_deg > 90 or angle_deg < -90:
            self._label.setRotation(180)
        else:
            self._label.setRotation(0)

    def update_endpoint_2d(self, endpoint, new_pos):
        """Update one endpoint and recompute geometry.  Called during drag."""
        if endpoint == "start":
            self._start_2d = QtCore.QPointF(new_pos)
        else:
            self._end_2d = QtCore.QPointF(new_pos)
        self._update_geometry()


# ---------------------------------------------------------------------------
# HandleItem
# ---------------------------------------------------------------------------

class HandleItem(QtWidgets.QGraphicsEllipseItem):
    """Draggable circle at a datum endpoint.

    Supports endpoint clusters: handles sharing the same 3D position
    (within CLUSTER_TOLERANCE) move together.  On mouse release,
    writes the new position to FreeCAD objects within a transaction.
    """

    def __init__(self, member_obj, endpoint, designer_scene):
        r = HANDLE_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r)
        self._member = member_obj
        self._endpoint = endpoint      # "start" or "end"
        self._scene_ref = designer_scene
        self._cluster = []             # other HandleItems in same cluster
        self._batch_moving = False
        self._drag_start_pos = None
        self._original_pos = None      # set after placement

        self.setBrush(QtGui.QBrush(HANDLE_COLOR))
        self.setPen(QtGui.QPen(QtCore.Qt.NoPen))
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable)
        self.setFlag(QtWidgets.QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setZValue(10)

        self._update_tooltip()

    def _update_tooltip(self):
        try:
            if self._endpoint == "start":
                pt = self._member.A_StartPoint
            else:
                pt = self._member.B_EndPoint
            self.setToolTip(
                f"{self._member.Label} ({self._endpoint})\n"
                f"({pt.x:.0f}, {pt.y:.0f}, {pt.z:.0f})"
            )
        except Exception:
            pass

    # -- hover feedback -----------------------------------------------------

    def hoverEnterEvent(self, event):
        self.setBrush(QtGui.QBrush(HANDLE_HOVER_COLOR))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QtGui.QBrush(HANDLE_COLOR))
        super().hoverLeaveEvent(event)

    # -- drag handling ------------------------------------------------------

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionChange:
            if self._batch_moving:
                return value

            # Build exclusion sets from this handle + cluster
            exclude = set()
            if self._original_pos is not None:
                exclude.add((
                    round(self._original_pos.x(), 1),
                    round(self._original_pos.y(), 1),
                ))
            exclude_members = {self._member.Name}
            for other in self._cluster:
                op = other._original_pos
                if op is not None:
                    exclude.add((round(op.x(), 1), round(op.y(), 1)))
                exclude_members.add(other._member.Name)

            snap = self._scene_ref.snap_engine.combined_snap(
                value, exclude_positions=exclude,
                exclude_members=exclude_members,
            )
            snapped_pos = snap.point

            # Move cluster members
            for other in self._cluster:
                other._batch_moving = True
                other.setPos(snapped_pos)
                other._batch_moving = False

            # Live update of member rectangles during drag
            member_item = self._scene_ref._member_items.get(
                self._member.Name
            )
            if member_item is not None:
                member_item.update_endpoint_2d(self._endpoint, snapped_pos)
            for other in self._cluster:
                other_mi = self._scene_ref._member_items.get(
                    other._member.Name
                )
                if other_mi is not None:
                    other_mi.update_endpoint_2d(
                        other._endpoint, snapped_pos
                    )

            self._scene_ref.update_snap_feedback(snap)
            return snapped_pos

        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_start_pos = QtCore.QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if (event.button() == QtCore.Qt.LeftButton
                and self._drag_start_pos is not None):
            dx = self.pos().x() - self._drag_start_pos.x()
            dy = self.pos().y() - self._drag_start_pos.y()
            if math.hypot(dx, dy) > 0.5:
                self._commit_move()
            self._drag_start_pos = None
            self._scene_ref.clear_snap_feedback()

    def _commit_move(self):
        """Write the new endpoint position to FreeCAD objects."""
        import FreeCAD

        projection = self._scene_ref.projection
        new_3d = projection.unproject(self.pos())

        doc = self._member.Document
        doc.openTransaction("Move Bent Endpoint")
        try:
            self._write_endpoint(self._member, self._endpoint, new_3d)
            for other in self._cluster:
                self._write_endpoint(
                    other._member, other._endpoint, new_3d,
                )
            doc.recompute()
        except Exception as e:
            FreeCAD.Console.PrintError(
                f"BentDesigner move failed: {e}\n"
            )
        finally:
            doc.commitTransaction()

        # Rebuild from scratch for consistency
        self._scene_ref.rebuild()

    @staticmethod
    def _write_endpoint(member, endpoint, vec3d):
        if endpoint == "start":
            member.A_StartPoint = vec3d
        else:
            member.B_EndPoint = vec3d


# ---------------------------------------------------------------------------
# BentDesignerScene
# ---------------------------------------------------------------------------

class BentDesignerScene(QtWidgets.QGraphicsScene):
    """QGraphicsScene managing MemberItems, HandleItems, and grid.

    Rebuilds from scratch on every commit to stay consistent with
    the 3D model.
    """

    def __init__(self, designer_widget):
        super().__init__()
        self._designer = designer_widget
        self.snap_engine = SnapEngine()
        self.projection = ProjectionPlane()
        self._snap_indicators = []
        self._member_items = {}          # member.Name → MemberItem
        self._grid_enabled = True
        self._grid_spacing = GRID_DEFAULT_SPACING
        self.setSceneRect(-50000, -50000, 100000, 100000)

        # Derive grid colours from FreeCAD's viewport background.
        self._bg_color = _get_freecad_bg_color()
        minor, major = _grid_colors_for_bg(self._bg_color)
        self._grid_minor_color = minor
        self._grid_major_color = major

    # -- grid (scene items) -------------------------------------------------

    def _add_grid_items(self):
        """Add grid lines as QGraphicsLineItems around the members area.

        Lines are placed at z = -1 so they sit behind members and
        handles.  The grid extends 10 grid spacings beyond the items
        bounding rect, which is sufficient for the typical bent editing
        workflow.
        """
        if not self._grid_enabled or self._grid_spacing <= 0:
            return

        items_rect = self.itemsBoundingRect()
        if items_rect.isEmpty():
            return

        gs = self._grid_spacing
        margin = gs * 10
        rect = items_rect.adjusted(-margin, -margin, margin, margin)

        minor_pen = QtGui.QPen(self._grid_minor_color, 0)   # cosmetic
        major_pen = QtGui.QPen(self._grid_major_color, 0)

        left = math.floor(rect.left() / gs) * gs
        top = math.floor(rect.top() / gs) * gs

        # Vertical lines
        x = left
        while x <= rect.right():
            idx = round(x / gs)
            pen = major_pen if idx % 5 == 0 else minor_pen
            line = self.addLine(x, rect.top(), x, rect.bottom(), pen)
            line.setZValue(-1)
            x += gs

        # Horizontal lines
        y = top
        while y <= rect.bottom():
            idx = round(y / gs)
            pen = major_pen if idx % 5 == 0 else minor_pen
            line = self.addLine(rect.left(), y, rect.right(), y, pen)
            line.setZValue(-1)
            y += gs

    # -- rebuild from FreeCAD state -----------------------------------------

    def rebuild(self):
        """Clear and rebuild all items from the Bent's current state."""
        self._designer._rebuilding = True
        try:
            self._rebuild_impl()
        finally:
            self._designer._rebuilding = False

    def _rebuild_impl(self):
        self.clear()
        self._snap_indicators = []
        self._member_items = {}

        obj = self._designer._obj
        if obj is None:
            return

        try:
            members = obj.Members or []
        except Exception:
            return

        if not members:
            self.projection.fit([])
            return

        # Collect 3D endpoints and fit projection plane
        import FreeCAD
        points_3d = []
        for m in members:
            try:
                points_3d.append(FreeCAD.Vector(m.A_StartPoint))
                points_3d.append(FreeCAD.Vector(m.B_EndPoint))
            except Exception:
                pass

        self.projection.fit(points_3d)

        # Create MemberItems
        for m in members:
            try:
                item = MemberItem(m, self.projection)
                self.addItem(item)
                self._member_items[m.Name] = item
            except Exception as e:
                FreeCAD.Console.PrintWarning(
                    f"BentDesigner: skip member: {e}\n"
                )

        # Create HandleItems
        handles = []
        for m in members:
            try:
                for ep in ("start", "end"):
                    h = HandleItem(m, ep, self)
                    if ep == "start":
                        pos2d = self.projection.project(
                            FreeCAD.Vector(m.A_StartPoint)
                        )
                    else:
                        pos2d = self.projection.project(
                            FreeCAD.Vector(m.B_EndPoint)
                        )
                    h.setPos(pos2d)
                    h._original_pos = QtCore.QPointF(pos2d)
                    self.addItem(h)
                    handles.append(h)
            except Exception:
                pass

        # Build endpoint clusters
        self._build_clusters(handles)

        # Update snap engine
        self.snap_engine.set_endpoints(
            [h._original_pos for h in handles if h._original_pos]
        )
        self.snap_engine.set_datums([
            (QtCore.QPointF(mi._start_2d),
             QtCore.QPointF(mi._end_2d), name)
            for name, mi in self._member_items.items()
        ])

        # Grid lines (added last; z = -1 keeps them behind everything).
        self._add_grid_items()

    def _build_clusters(self, handles):
        """Group handles at the same 2D position into clusters."""
        assigned = set()
        for i, h1 in enumerate(handles):
            if i in assigned:
                continue
            cluster = [h1]
            assigned.add(i)
            for j, h2 in enumerate(handles):
                if j in assigned:
                    continue
                dx = h1.pos().x() - h2.pos().x()
                dy = h1.pos().y() - h2.pos().y()
                if math.hypot(dx, dy) < CLUSTER_TOLERANCE:
                    cluster.append(h2)
                    assigned.add(j)
            # Link each handle to the others in its cluster
            for h in cluster:
                h._cluster = [o for o in cluster if o is not h]

    # -- snap visual feedback -----------------------------------------------

    def update_snap_feedback(self, snap_result):
        """Show visual indicators for the current snap state."""
        self.clear_snap_feedback()

        if snap_result.snap_type == "endpoint":
            r = HANDLE_RADIUS * 1.5
            dot = self.addEllipse(
                snap_result.point.x() - r, snap_result.point.y() - r,
                2 * r, 2 * r,
                QtGui.QPen(SNAP_ENDPOINT_COLOR, 2),
                QtGui.QBrush(QtCore.Qt.NoBrush),
            )
            dot.setZValue(20)
            self._snap_indicators.append(dot)

        elif ("alignment" in snap_result.snap_type
              and snap_result.alignment_ref is not None):
            pen = QtGui.QPen(SNAP_ALIGN_COLOR, 1, QtCore.Qt.DashLine)
            ref = snap_result.alignment_ref
            pt = snap_result.point

            if "v" in snap_result.snap_type:
                line = self.addLine(
                    pt.x(), min(pt.y(), ref.y()) - 200,
                    pt.x(), max(pt.y(), ref.y()) + 200,
                    pen,
                )
                line.setZValue(20)
                self._snap_indicators.append(line)

            if "h" in snap_result.snap_type:
                line = self.addLine(
                    min(pt.x(), ref.x()) - 200, pt.y(),
                    max(pt.x(), ref.x()) + 200, pt.y(),
                    pen,
                )
                line.setZValue(20)
                self._snap_indicators.append(line)

        elif (snap_result.snap_type == "datum"
              and snap_result.alignment_ref is not None):
            # alignment_ref is (dx, dy) unit vector along datum;
            # draw a perpendicular tick mark centered on the snap point.
            datum_dx, datum_dy = snap_result.alignment_ref
            perp_dx, perp_dy = -datum_dy, datum_dx  # 90° rotation
            extent = HANDLE_RADIUS * 3
            pt = snap_result.point
            pen = QtGui.QPen(SNAP_DATUM_COLOR, 2, QtCore.Qt.DashLine)
            line = self.addLine(
                pt.x() - perp_dx * extent,
                pt.y() - perp_dy * extent,
                pt.x() + perp_dx * extent,
                pt.y() + perp_dy * extent,
                pen,
            )
            line.setZValue(20)
            self._snap_indicators.append(line)

    def clear_snap_feedback(self):
        for item in self._snap_indicators:
            self.removeItem(item)
        self._snap_indicators = []


# ---------------------------------------------------------------------------
# BentDesignerView
# ---------------------------------------------------------------------------

class BentDesignerView(QtWidgets.QGraphicsView):
    """Custom QGraphicsView with wheel zoom, middle-drag pan, F-to-fit."""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.AnchorUnderMouse
        )
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        # Match FreeCAD's 3D viewport background.
        self.setBackgroundBrush(QtGui.QBrush(scene._bg_color))

        self._panning = False
        self._pan_start = None

    # -- zoom ---------------------------------------------------------------

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            factor = ZOOM_FACTOR
        else:
            factor = 1.0 / ZOOM_FACTOR

        current = self.transform().m11()
        new_scale = current * factor
        if new_scale < ZOOM_MIN or new_scale > ZOOM_MAX:
            return

        self.scale(factor, factor)

    # -- pan (middle mouse) -------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self._panning = False
            self._pan_start = None
            self.setCursor(QtCore.Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -- fit all (F key) ----------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_F:
            self.fit_all()
            return
        super().keyPressEvent(event)

    def fit_all(self):
        """Fit all items in view with 10 % padding."""
        rect = self.scene().itemsBoundingRect()
        if rect.isEmpty():
            return
        margin = max(rect.width(), rect.height()) * 0.1
        rect.adjust(-margin, -margin, margin, margin)
        self.fitInView(rect, QtCore.Qt.KeepAspectRatio)


# ---------------------------------------------------------------------------
# BentDesignerWidget
# ---------------------------------------------------------------------------

class BentDesignerWidget(QtWidgets.QWidget):
    """Main Bent Designer widget — canvas + controls toolbar.

    Hosted as an MDI subwindow in FreeCAD's central area.
    """

    def __init__(self, bent_obj, parent=None):
        super().__init__(parent)
        self._obj = bent_obj
        self._rebuilding = False

        title = bent_obj.BentName or bent_obj.Label
        self.setWindowTitle(f"Bent Designer \u2014 {title}")

        self._build_ui()

        # F shortcut — bound to the widget so it fires when any child
        # (view, toolbar controls) has focus inside this MDI tab.
        self._fit_shortcut = QtWidgets.QShortcut(
            QtGui.QKeySequence("F"), self,
            context=QtCore.Qt.WidgetWithChildrenShortcut,
        )
        self._fit_shortcut.activated.connect(self._view.fit_all)

        self._scene.rebuild()
        QtCore.QTimer.singleShot(100, self._view.fit_all)

    # -- UI construction ----------------------------------------------------

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Canvas
        self._scene = BentDesignerScene(self)
        self._view = BentDesignerView(self._scene, self)
        layout.addWidget(self._view, 1)

        # Controls toolbar
        toolbar = QtWidgets.QWidget()
        toolbar.setFixedHeight(80)
        controls = QtWidgets.QVBoxLayout(toolbar)
        controls.setContentsMargins(8, 4, 8, 4)

        # Row 1: Grid / Snap controls
        row1 = QtWidgets.QHBoxLayout()

        row1.addWidget(QtWidgets.QLabel("Grid:"))
        self._grid_spin = QtWidgets.QSpinBox()
        self._grid_spin.setRange(10, 500)
        self._grid_spin.setValue(int(GRID_DEFAULT_SPACING))
        self._grid_spin.setSuffix(" mm")
        self._grid_spin.valueChanged.connect(self._on_grid_changed)
        row1.addWidget(self._grid_spin)

        self._grid_check = QtWidgets.QCheckBox("Grid")
        self._grid_check.setChecked(True)
        self._grid_check.toggled.connect(self._on_snap_toggle)
        row1.addWidget(self._grid_check)

        self._endpoint_check = QtWidgets.QCheckBox("Endpoint")
        self._endpoint_check.setChecked(True)
        self._endpoint_check.toggled.connect(self._on_snap_toggle)
        row1.addWidget(self._endpoint_check)

        self._align_check = QtWidgets.QCheckBox("Align")
        self._align_check.setChecked(True)
        self._align_check.toggled.connect(self._on_snap_toggle)
        row1.addWidget(self._align_check)

        row1.addStretch()

        fit_btn = QtWidgets.QPushButton("Fit View")
        fit_btn.clicked.connect(self._view.fit_all)
        row1.addWidget(fit_btn)

        controls.addLayout(row1)

        # Row 2: Template controls
        row2 = QtWidgets.QHBoxLayout()

        row2.addWidget(QtWidgets.QLabel("Template:"))
        self._template_combo = QtWidgets.QComboBox()
        self._populate_templates()
        row2.addWidget(self._template_combo)

        row2.addWidget(QtWidgets.QLabel("Span:"))
        self._span_spin = QtWidgets.QSpinBox()
        self._span_spin.setRange(1000, 20000)
        self._span_spin.setValue(6000)
        self._span_spin.setSuffix(" mm")
        row2.addWidget(self._span_spin)

        row2.addWidget(QtWidgets.QLabel("Height:"))
        self._height_spin = QtWidgets.QSpinBox()
        self._height_spin.setRange(1000, 15000)
        self._height_spin.setValue(4000)
        self._height_spin.setSuffix(" mm")
        row2.addWidget(self._height_spin)

        apply_btn = QtWidgets.QPushButton("Apply Template")
        apply_btn.clicked.connect(self._on_apply_template)
        row2.addWidget(apply_btn)

        row2.addStretch()
        controls.addLayout(row2)

        layout.addWidget(toolbar)

    def _populate_templates(self):
        from ui.bent_templates import BUILTIN_TEMPLATES

        self._template_combo.clear()
        for t in BUILTIN_TEMPLATES:
            self._template_combo.addItem(t.name, t)

    # -- control slots ------------------------------------------------------

    def _on_grid_changed(self, value):
        self._scene._grid_spacing = float(value)
        self._scene.snap_engine.grid_spacing = float(value)
        self._scene.rebuild()

    def _on_snap_toggle(self):
        self._scene._grid_enabled = self._grid_check.isChecked()
        self._scene.snap_engine.grid_enabled = self._grid_check.isChecked()
        self._scene.snap_engine.endpoint_enabled = (
            self._endpoint_check.isChecked()
        )
        self._scene.snap_engine.alignment_enabled = (
            self._align_check.isChecked()
        )
        self._scene.rebuild()

    # -- template application -----------------------------------------------

    def _on_apply_template(self):
        import FreeCAD
        from objects.TimberMember import create_timber_member
        from objects.Bent import Bent

        if not self._obj_valid():
            return

        idx = self._template_combo.currentIndex()
        template = self._template_combo.itemData(idx)
        if template is None:
            return

        span = float(self._span_spin.value())
        height = float(self._height_spin.value())

        # Confirm if bent already has members
        existing = self._obj.Members or []
        if existing:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Apply Template",
                f"This bent has {len(existing)} existing member(s).\n\n"
                "New members will be added without removing existing "
                "ones.\n\nContinue?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return

        # Ensure projection is initialised for empty bents
        proj = self._scene.projection
        if proj.u_axis is None:
            proj.fit([])

        doc = self._obj.Document
        doc.openTransaction(f"Apply Template: {template.name}")
        try:
            for tm in template.members:
                sx = tm.start[0] * span
                sz = tm.start[1] * height
                ex = tm.end[0] * span
                ez = tm.end[1] * height

                # Convert to 3D via projection plane
                start_3d = proj.unproject(QtCore.QPointF(sx, -sz))
                end_3d = proj.unproject(QtCore.QPointF(ex, -ez))

                member = create_timber_member(
                    name=f"TM_{tm.role}",
                    start=start_3d,
                    end=end_3d,
                    role=tm.role,
                )
                member.Width = tm.width
                member.Height = tm.height

                Bent.add_member(self._obj, member)

            self._obj.BentTemplate = template.name
            doc.recompute()
        except Exception as e:
            FreeCAD.Console.PrintError(
                f"Template apply failed: {e}\n"
            )
        finally:
            doc.commitTransaction()

        self._scene.rebuild()
        QtCore.QTimer.singleShot(50, self._view.fit_all)

    # -- external change notification ---------------------------------------

    def notify_property_changed(self, prop):
        """Called by the ViewProvider when the bent recomputes externally."""
        if self._rebuilding:
            return
        if prop in ("Members", "Shape"):
            QtCore.QTimer.singleShot(0, self._deferred_rebuild)

    def _deferred_rebuild(self):
        if self._rebuilding:
            return
        self._scene.rebuild()

    # -- object validity / cleanup ------------------------------------------

    def _obj_valid(self):
        if self._obj is None:
            return False
        try:
            _ = self._obj.Name
            return True
        except Exception:
            self._obj = None
            return False

    def _disconnect(self):
        self._obj = None

    def closeEvent(self, event):
        self._disconnect()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def open_bent_designer(bent_obj):
    """Open the Bent Designer as an MDI tab for *bent_obj*.

    If a designer is already open for this bent, activates it instead
    of creating a duplicate.
    """
    import FreeCADGui

    main = FreeCADGui.getMainWindow()
    mdi = main.findChild(QtWidgets.QMdiArea)
    if mdi is None:
        import FreeCAD
        FreeCAD.Console.PrintError(
            "BentDesigner: no MDI area found\n"
        )
        return

    # Check for an existing designer for this bent
    for sub in mdi.subWindowList():
        widget = sub.widget()
        if isinstance(widget, BentDesignerWidget):
            if widget._obj is bent_obj:
                mdi.setActiveSubWindow(sub)
                return

    designer = BentDesignerWidget(bent_obj)
    sub = mdi.addSubWindow(designer)
    title = bent_obj.BentName or bent_obj.Label
    sub.setWindowTitle(f"Bent Designer \u2014 {title}")
    sub.showMaximized()

    # Register with ViewProvider for external change notifications
    try:
        vp = bent_obj.ViewObject.Proxy
        if vp is not None:
            vp._active_designer = designer
    except Exception:
        pass
