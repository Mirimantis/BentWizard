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

# Joint visualization
JOINT_VALID_COLOR = QtGui.QColor(102, 128, 153)     # blue-gray (matches 3D)
JOINT_PLACEHOLDER_COLOR = QtGui.QColor(255, 165, 0) # orange
JOINT_BROKEN_COLOR = QtGui.QColor(230, 26, 26)      # red

JOINT_ABBREV = {
    "mortise_tenon": "MT",
    "dovetail": "DT",
    "half_lap": "HL",
    "birdsmouth": "BM",
    "scarf_bladed": "SC",
    "placeholder": "?",
}
JOINT_MARKER_SIZE = 25.0  # half-size of the diamond/circle marker

HANDLE_RADIUS = 8.0
SNAP_TOLERANCE = 20.0
DATUM_SNAP_TOLERANCE = 30.0   # wider catch radius for datum-aligned snap
DATUM_LINE_COLOR = HANDLE_COLOR
GRID_DEFAULT_SPACING = 50.0
GRID_MIN_EXTENT = 10000.0  # minimum half-extent for grid (20000 mm total)
GROUND_LINE_COLOR = QtGui.QColor(80, 180, 80)  # muted green for Z=0 datum

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
        # Dark background → light gray grid lines
        return (QtGui.QColor(255, 255, 255, 30),
                QtGui.QColor(255, 255, 255, 60))
    # Light background → light gray grid lines
    return (QtGui.QColor(0, 0, 0, 30),
            QtGui.QColor(0, 0, 0, 60))


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
        self._fitted = False  # True after the first successful fit

    def fit(self, points_3d):
        """Compute the projection plane from a list of 3D points.

        On the first call the origin is set to the centroid and the
        axes are chosen from the point spread.  Subsequent calls only
        update the axes (if needed) — the origin is kept fixed so the
        grid and members don't shift when timbers move.

        Parameters
        ----------
        points_3d : list of FreeCAD.Vector
            Datum endpoints.  May be empty.
        """
        import FreeCAD

        if not points_3d:
            if not self._fitted:
                self._set_default_xz()
            return

        n = len(points_3d)

        # Lock the origin on the first fit so the grid stays fixed.
        if not self._fitted:
            cx = sum(p.x for p in points_3d) / n
            cy = sum(p.y for p in points_3d) / n
            cz = sum(p.z for p in points_3d) / n
            self.origin = FreeCAD.Vector(cx, cy, cz)

        if n < 2:
            if not self._fitted:
                self._set_default_xz()
                # Keep the centroid origin computed above.
            self._fitted = True
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

        self._fitted = True

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
        self.grid_y_offset = 0.0  # Y offset to align grid with ground line
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

        # 4. Grid snap — Y is offset to align with the ground line
        if self.grid_enabled and self.grid_spacing > 0:
            gs = self.grid_spacing
            gx = round(pos.x() / gs) * gs
            gy = round((pos.y() - self.grid_y_offset) / gs) * gs + self.grid_y_offset
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
        datum_pen = QtGui.QPen(DATUM_LINE_COLOR, 2, QtCore.Qt.SolidLine)
        datum_pen.setCosmetic(True)
        self._datum_line.setPen(datum_pen)
        self._datum_line.setAcceptedMouseButtons(QtCore.Qt.NoButton)

        self._update_geometry()

        # Color by role
        role = str(getattr(self._member, "Role", ""))
        color = ROLE_COLORS.get(role, DEFAULT_MEMBER_COLOR)
        self.setBrush(QtGui.QBrush(color))
        self.setPen(QtGui.QPen(color.darker(150), 1))
        self.setOpacity(0.8)
        self.setZValue(1)

        # MemberID label — ignores view transforms so it stays a fixed
        # screen size regardless of zoom.  Hidden when zoomed out so far
        # that the label would be wider than the timber.
        mid_str = getattr(self._member, "MemberID", "") or self._member.Label
        if mid_str:
            self._label = QtWidgets.QGraphicsSimpleTextItem(mid_str, self)
            self._label.setFlag(
                QtWidgets.QGraphicsItem.ItemIgnoresTransformations
            )
            self._label.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            self._label.setBrush(QtGui.QBrush(QtCore.Qt.white))
            font = self._label.font()
            font.setPointSize(11)
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
        """Align label with the datum line, offset above it.

        The label uses ItemIgnoresTransformations, so it stays at a
        fixed screen size.  A composite QTransform handles both
        rotation (matching the datum angle, normalized to [-90, 90])
        and offset (centered along datum, gap pixels above it).

        Rotation and offset must be in a single transform so the
        offset direction rotates with the text — using separate
        setRotation + setTransform causes the offset to drift at
        non-zero angles because Qt applies them in different
        coordinate spaces.
        """
        dx = self._end_2d.x() - self._start_2d.x()
        dy = self._end_2d.y() - self._start_2d.y()
        angle_deg = math.degrees(math.atan2(dy, dx))

        # Normalize to [-90, 90] for readability
        if angle_deg > 90:
            angle_deg -= 180
        elif angle_deg < -90:
            angle_deg += 180

        angle_rad = math.radians(angle_deg)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        br = self._label.boundingRect()
        w = br.width()
        h = br.height()
        gap = 3  # screen pixels between text bottom and datum line

        # Screen-space offset: center along datum, (h + gap) above it.
        # Projects the local text offset onto the datum-aligned axes.
        tx = -w / 2 * cos_a + (h + gap) * sin_a
        ty = -w / 2 * sin_a - (h + gap) * cos_a

        self._label.setPos(0, 0)
        self._label.setRotation(0)
        t = QtGui.QTransform()
        t.translate(tx, ty)
        t.rotate(angle_deg)
        self._label.setTransform(t)

    def update_endpoint_2d(self, endpoint, new_pos):
        """Update one endpoint and recompute geometry.  Called during drag."""
        if endpoint == "start":
            self._start_2d = QtCore.QPointF(new_pos)
        else:
            self._end_2d = QtCore.QPointF(new_pos)
        self._update_geometry()

    # -- click to select in FreeCAD tree ------------------------------------

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            try:
                import FreeCADGui
                FreeCADGui.Selection.clearSelection()
                FreeCADGui.Selection.addSelection(self._member)
            except Exception:
                pass
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# JointItem
# ---------------------------------------------------------------------------

class JointItem(QtWidgets.QGraphicsItem):
    """2D marker for a TimberJoint in the Bent Designer.

    Positioned at the projected intersection point.  Visual style depends
    on joint state: assigned (blue-gray diamond with type abbreviation),
    placeholder (orange circle with "?"), or broken (red X marks at
    last-valid positions on each member's datum with connecting line).

    Rendered behind endpoint handles (z=4 vs handles at default z)
    so the marker is visible around the edges but doesn't block handle
    interaction.
    """

    def __init__(self, joint_obj, projection, member_items):
        super().__init__()
        self._joint = joint_obj
        self._projection = projection
        self._member_items = member_items  # dict: member.Name → MemberItem
        self._primary_name = ""
        self._secondary_name = ""
        self._is_broken = False
        self._joint_type = "placeholder"
        self._abbrev = "?"

        # 2D positions for broken-joint line drawing
        self._pri_point_2d = QtCore.QPointF()
        self._sec_point_2d = QtCore.QPointF()

        self._read_state()
        self._setup()

    def _read_state(self):
        """Read joint state from the FreeCAD object."""
        import FreeCAD
        try:
            self._is_broken = getattr(self._joint, "IsBroken", False)
            self._joint_type = getattr(self._joint, "JointType", "placeholder")
            self._abbrev = JOINT_ABBREV.get(self._joint_type, "?")

            pri = self._joint.PrimaryMember
            sec = self._joint.SecondaryMember
            self._primary_name = pri.Name if pri else ""
            self._secondary_name = sec.Name if sec else ""

            if self._is_broken:
                lv_pri = FreeCAD.Vector(self._joint.LastValidPrimaryPoint)
                lv_sec = FreeCAD.Vector(self._joint.LastValidSecondaryPoint)
                self._pri_point_2d = self._projection.project(lv_pri)
                self._sec_point_2d = self._projection.project(lv_sec)
                # Position at midpoint of the two last-valid points.
                mid = FreeCAD.Vector(self._joint.LastValidPoint)
                pos2d = self._projection.project(mid)
            else:
                ip = FreeCAD.Vector(self._joint.IntersectionPoint)
                pos2d = self._projection.project(ip)
                self._pri_point_2d = QtCore.QPointF(pos2d)
                self._sec_point_2d = QtCore.QPointF(pos2d)
        except Exception:
            pos2d = QtCore.QPointF(0, 0)

        self.setPos(pos2d)

    def _setup(self):
        # Non-broken joints use ItemIgnoresTransformations for fixed
        # screen-size markers.  Broken joints paint in scene coordinates
        # so the connecting line between distant points scales correctly.
        if not self._is_broken:
            self.setFlag(
                QtWidgets.QGraphicsItem.ItemIgnoresTransformations, True
            )
        self.setAcceptHoverEvents(True)
        # Z=4: behind endpoint handles (z=10) but above member rects (z=0)
        self.setZValue(4)
        self._update_tooltip()

    def _update_tooltip(self):
        try:
            jtype = self._joint_type or "placeholder"
            name_map = {
                "mortise_tenon": "Mortise & Tenon",
                "dovetail": "Dovetail",
                "half_lap": "Half Lap",
                "birdsmouth": "Birdsmouth",
                "scarf_bladed": "Scarf",
                "placeholder": "Unassigned",
            }
            type_name = name_map.get(jtype, jtype)
            pri_label = ""
            sec_label = ""
            try:
                if self._joint.PrimaryMember:
                    pri_label = self._joint.PrimaryMember.Label
                if self._joint.SecondaryMember:
                    sec_label = self._joint.SecondaryMember.Label
            except Exception:
                pass
            angle = getattr(self._joint, "IntersectionAngle", 0.0)
            tip = f"{type_name}\n{pri_label} + {sec_label}\n{angle:.1f}\u00b0"
            if self._is_broken:
                tip += "\nBROKEN"
            self.setToolTip(tip)
        except Exception:
            pass

    # -- geometry and painting ------------------------------------------------

    def boundingRect(self):
        if self._is_broken:
            # Broken state paints in scene coordinates — compute bounds
            # from the two last-valid points relative to this item's pos.
            pri_local = self._pri_point_2d - self.pos()
            sec_local = self._sec_point_2d - self.pos()
            xs = [pri_local.x(), sec_local.x(), 0]
            ys = [pri_local.y(), sec_local.y(), 0]
            margin = 10.0
            return QtCore.QRectF(
                min(xs) - margin, min(ys) - margin,
                max(xs) - min(xs) + 2 * margin,
                max(ys) - min(ys) + 2 * margin,
            )
        s = JOINT_MARKER_SIZE + 2
        # Extra space above for the text label
        return QtCore.QRectF(-s, -s * 2.4, 2 * s, s * 3.4)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        if self._is_broken:
            self._paint_broken(painter)
        elif self._joint_type == "placeholder":
            self._paint_placeholder(painter)
        else:
            self._paint_assigned(painter)

    def _paint_assigned(self, painter):
        """Blue-gray diamond with type abbreviation above."""
        s = JOINT_MARKER_SIZE
        diamond = QtGui.QPolygonF([
            QtCore.QPointF(0, -s),
            QtCore.QPointF(s, 0),
            QtCore.QPointF(0, s),
            QtCore.QPointF(-s, 0),
        ])
        painter.setBrush(QtGui.QBrush(JOINT_VALID_COLOR))
        painter.setPen(QtGui.QPen(JOINT_VALID_COLOR.darker(140), 1.5))
        painter.drawPolygon(diamond)

        # Type abbreviation — drawn above the diamond
        painter.setPen(QtGui.QPen(QtCore.Qt.white))
        font = painter.font()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        text_rect = QtCore.QRectF(-s, -s * 2.2, 2 * s, s)
        painter.drawText(text_rect, QtCore.Qt.AlignCenter, self._abbrev)

    def _paint_placeholder(self, painter):
        """Orange circle with '?' above."""
        s = JOINT_MARKER_SIZE
        painter.setBrush(QtGui.QBrush(JOINT_PLACEHOLDER_COLOR))
        painter.setPen(QtGui.QPen(JOINT_PLACEHOLDER_COLOR.darker(140), 1.5))
        painter.drawEllipse(QtCore.QRectF(-s, -s, 2 * s, 2 * s))

        # Question mark — drawn above the circle
        painter.setPen(QtGui.QPen(QtCore.Qt.white))
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        text_rect = QtCore.QRectF(-s, -s * 2.2, 2 * s, s)
        painter.drawText(text_rect, QtCore.Qt.AlignCenter, "?")

    def _paint_broken(self, painter):
        """Red X marks at last-valid positions with dashed connecting line.

        Painted in scene coordinates (ItemIgnoresTransformations is NOT set
        for broken joints).  Cosmetic pens keep line width constant.
        """
        # Convert scene positions to local coordinates (relative to item pos)
        pri_local = self._pri_point_2d - self.pos()
        sec_local = self._sec_point_2d - self.pos()

        pen = QtGui.QPen(JOINT_BROKEN_COLOR, 2, QtCore.Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)

        # Dashed line connecting the two last-valid points
        painter.drawLine(pri_local, sec_local)

        # X marks at each last-valid point — size in scene units
        xs = 8.0
        xpen = QtGui.QPen(JOINT_BROKEN_COLOR, 2.5)
        xpen.setCosmetic(True)
        painter.setPen(xpen)
        for pt in (pri_local, sec_local):
            painter.drawLine(
                QtCore.QPointF(pt.x() - xs, pt.y() - xs),
                QtCore.QPointF(pt.x() + xs, pt.y() + xs),
            )
            painter.drawLine(
                QtCore.QPointF(pt.x() - xs, pt.y() + xs),
                QtCore.QPointF(pt.x() + xs, pt.y() - xs),
            )

    # -- interaction ----------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            try:
                import FreeCADGui
                FreeCADGui.Selection.clearSelection()
                FreeCADGui.Selection.addSelection(self._joint)
            except Exception:
                pass
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            try:
                import FreeCADGui
                vobj = self._joint.ViewObject
                if vobj and hasattr(vobj.Proxy, 'doubleClicked'):
                    vobj.Proxy.doubleClicked(vobj)
            except Exception:
                pass
        super().mouseDoubleClickEvent(event)

    # -- live drag update -----------------------------------------------------

    def update_position_from_members(self, member_items):
        """Recompute 2D position from current member endpoint positions.

        Called during handle drag for cosmetic live preview.
        Uses 2D line intersection of the two member datums.  During drag,
        the marker keeps showing its joint type and moves along the primary
        datum at the point where the secondary datum line intersects.
        """
        pri_mi = member_items.get(self._primary_name)
        sec_mi = member_items.get(self._secondary_name)
        if pri_mi is None or sec_mi is None:
            return

        # 2D line intersection of the two datums
        pt = _intersect_2d_segments(
            pri_mi._start_2d, pri_mi._end_2d,
            sec_mi._start_2d, sec_mi._end_2d,
        )
        if pt is not None:
            self.setPos(pt)
            self._pri_point_2d = QtCore.QPointF(pt)
            self._sec_point_2d = QtCore.QPointF(pt)


def _intersect_2d_segments(p1, p2, p3, p4):
    """Compute the intersection of two 2D line segments (or their extensions).

    Returns a QPointF or None if lines are parallel.
    Uses the parametric form and allows intersection outside segment bounds
    (since member datums extend beyond their endpoints in the frame).
    """
    x1, y1 = p1.x(), p1.y()
    x2, y2 = p2.x(), p2.y()
    x3, y3 = p3.x(), p3.y()
    x4, y4 = p4.x(), p4.y()

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-10:
        return None  # parallel

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    ix = x1 + t * (x2 - x1)
    iy = y1 + t * (y2 - y1)
    return QtCore.QPointF(ix, iy)


# ---------------------------------------------------------------------------
# HandleItem
# ---------------------------------------------------------------------------

class HandleItem(QtWidgets.QGraphicsEllipseItem):
    """Draggable circle at a datum endpoint.

    On mouse release, writes the new position to FreeCAD objects
    within a transaction.
    """

    def __init__(self, member_obj, endpoint, designer_scene):
        r = HANDLE_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r)
        self._member = member_obj
        self._endpoint = endpoint      # "start" or "end"
        self._scene_ref = designer_scene
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

            exclude = set()
            if self._original_pos is not None:
                exclude.add((
                    round(self._original_pos.x(), 1),
                    round(self._original_pos.y(), 1),
                ))
            exclude_members = {self._member.Name}

            snap = self._scene_ref.snap_engine.combined_snap(
                value, exclude_positions=exclude,
                exclude_members=exclude_members,
            )
            snapped_pos = snap.point

            # Live update of member rectangle during drag
            member_item = self._scene_ref._member_items.get(
                self._member.Name
            )
            if member_item is not None:
                member_item.update_endpoint_2d(self._endpoint, snapped_pos)

            # Live update of joint markers during drag
            joint_items = getattr(self._scene_ref, '_joint_items', {})
            mi_dict = self._scene_ref._member_items
            for _jname, ji in joint_items.items():
                if ji._primary_name == self._member.Name or ji._secondary_name == self._member.Name:
                    ji.update_position_from_members(mi_dict)

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
# DatumTranslateHandle
# ---------------------------------------------------------------------------

class DatumTranslateHandle(QtWidgets.QGraphicsPathItem):
    """Diamond handle at datum midpoint for translating an entire member.

    Dragging moves both endpoints by the same delta, preserving member
    length and angle.  Clustered endpoint handles follow the move.
    """

    def __init__(self, member_obj, start_handle, end_handle, designer_scene):
        super().__init__()
        self._member = member_obj
        self._start_handle = start_handle
        self._end_handle = end_handle
        self._scene_ref = designer_scene
        self._original_midpoint = None
        self._original_start = None
        self._original_end = None
        self._drag_start_pos = None

        # Diamond shape
        r = HANDLE_RADIUS * 0.9
        path = QtGui.QPainterPath()
        path.moveTo(0, -r)
        path.lineTo(r, 0)
        path.lineTo(0, r)
        path.lineTo(-r, 0)
        path.closeSubpath()
        self.setPath(path)

        self.setBrush(QtGui.QBrush(HANDLE_COLOR))
        self.setPen(QtGui.QPen(QtCore.Qt.NoPen))
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable)
        self.setFlag(QtWidgets.QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setCursor(QtCore.Qt.SizeAllCursor)
        self.setZValue(9)

        self.setToolTip(f"{member_obj.Label} (move)")

    # -- hover feedback -----------------------------------------------------

    def hoverEnterEvent(self, event):
        self.setBrush(QtGui.QBrush(HANDLE_HOVER_COLOR))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QtGui.QBrush(HANDLE_COLOR))
        super().hoverLeaveEvent(event)

    # -- drag handling ------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_start_pos = QtCore.QPointF(self.pos())
            self._original_midpoint = QtCore.QPointF(self.pos())
            self._original_start = QtCore.QPointF(
                self._start_handle.pos()
            )
            self._original_end = QtCore.QPointF(self._end_handle.pos())
        super().mousePressEvent(event)

    def itemChange(self, change, value):
        if change != QtWidgets.QGraphicsItem.ItemPositionChange:
            return super().itemChange(change, value)
        if self._original_midpoint is None:
            return value

        exclude = set()
        exclude_members = {self._member.Name}
        for pos in (self._original_start, self._original_end):
            exclude.add((round(pos.x(), 1), round(pos.y(), 1)))

        snap = self._scene_ref.snap_engine.combined_snap(
            value, exclude_positions=exclude,
            exclude_members=exclude_members,
        )
        snapped_pos = snap.point

        # Delta from original midpoint
        delta_x = snapped_pos.x() - self._original_midpoint.x()
        delta_y = snapped_pos.y() - self._original_midpoint.y()

        new_start = QtCore.QPointF(
            self._original_start.x() + delta_x,
            self._original_start.y() + delta_y,
        )
        new_end = QtCore.QPointF(
            self._original_end.x() + delta_x,
            self._original_end.y() + delta_y,
        )

        # Move endpoint handles (batch flag skips their snap logic)
        self._start_handle._batch_moving = True
        self._start_handle.setPos(new_start)
        self._start_handle._batch_moving = False

        self._end_handle._batch_moving = True
        self._end_handle.setPos(new_end)
        self._end_handle._batch_moving = False

        # Live-update member rectangle
        mi = self._scene_ref._member_items.get(self._member.Name)
        if mi is not None:
            mi.update_endpoint_2d("start", new_start)
            mi.update_endpoint_2d("end", new_end)

        self._scene_ref.update_snap_feedback(snap)
        return snapped_pos

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if (event.button() == QtCore.Qt.LeftButton
                and self._drag_start_pos is not None):
            dx = self.pos().x() - self._drag_start_pos.x()
            dy = self.pos().y() - self._drag_start_pos.y()
            if math.hypot(dx, dy) > 0.5:
                self._commit_move()
            self._drag_start_pos = None
            self._original_midpoint = None
            self._scene_ref.clear_snap_feedback()

    def _commit_move(self):
        """Write both endpoint positions to FreeCAD objects."""
        import FreeCAD

        projection = self._scene_ref.projection
        new_start_3d = projection.unproject(self._start_handle.pos())
        new_end_3d = projection.unproject(self._end_handle.pos())

        doc = self._member.Document
        doc.openTransaction("Move Timber Member")
        try:
            self._member.A_StartPoint = new_start_3d
            self._member.B_EndPoint = new_end_3d
            doc.recompute()
        except Exception as e:
            FreeCAD.Console.PrintError(
                f"BentDesigner move failed: {e}\n"
            )
        finally:
            doc.commitTransaction()

        self._scene_ref.rebuild()


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

    def _ground_y(self):
        """Scene Y coordinate of the Z=0 ground plane."""
        proj = self.projection
        if proj.origin is None or proj.v_axis is None:
            return 0.0
        import FreeCAD
        return proj.project(FreeCAD.Vector(0, 0, 0)).y()

    def _add_grid_items(self):
        """Add grid lines aligned to the ground plane.

        Horizontal lines are offset so that a major grid line falls
        exactly on the Z=0 ground line.  Vertical lines are anchored
        at X=0 in scene space.  Lines sit at z = -1 behind members
        and handles.
        """
        if not self._grid_enabled or self._grid_spacing <= 0:
            return

        gs = self._grid_spacing
        margin = gs * 10

        # Compute extent from origin, covering items + margin on all sides.
        # Always at least GRID_MIN_EXTENT so the grid is visible on empty bents.
        items_rect = self.itemsBoundingRect()
        if items_rect.isEmpty():
            extent = GRID_MIN_EXTENT
        else:
            extent = max(
                abs(items_rect.left()),
                abs(items_rect.right()),
                abs(items_rect.top()),
                abs(items_rect.bottom()),
            ) + margin
            extent = max(extent, GRID_MIN_EXTENT)

        minor_pen = QtGui.QPen(self._grid_minor_color, 0)   # cosmetic
        major_pen = QtGui.QPen(self._grid_major_color, 0)

        # Offset horizontal grid so a major line lands on the ground (Z=0).
        # Round ground_y to the nearest major interval (5 * gs).
        ground_y = self._ground_y()
        major_interval = 5 * gs
        h_offset = ground_y - round(ground_y / major_interval) * major_interval

        # Keep snap engine in sync with the visible grid.
        self.snap_engine.grid_y_offset = h_offset

        n = int(math.ceil(extent / gs))

        for i in range(-n, n + 1):
            pen = major_pen if i % 5 == 0 else minor_pen
            coord = i * gs
            # Vertical line — anchored at x = 0
            vline = self.addLine(coord, -extent + h_offset, coord, extent + h_offset, pen)
            vline.setZValue(-1)
            # Horizontal line — offset to align with ground
            hy = coord + h_offset
            hline = self.addLine(-extent, hy, extent, hy, pen)
            hline.setZValue(-1)

    def _add_ground_line(self):
        """Draw a prominent horizontal line at Z=0 (the default ground plane).

        Sits at z=0 — above grid lines (z=-1) but below members (z=1).
        Always collinear with a major grid line due to grid alignment.
        """
        ground_y = self._ground_y()

        # Extent — reuse the grid extent calculation.
        items_rect = self.itemsBoundingRect()
        gs = self._grid_spacing if self._grid_spacing > 0 else GRID_DEFAULT_SPACING
        margin = gs * 10
        if items_rect.isEmpty():
            extent = GRID_MIN_EXTENT
        else:
            extent = max(
                abs(items_rect.left()),
                abs(items_rect.right()),
                abs(items_rect.top()),
                abs(items_rect.bottom()),
            ) + margin
            extent = max(extent, GRID_MIN_EXTENT)

        pen = QtGui.QPen(GROUND_LINE_COLOR, 2)
        pen.setCosmetic(True)
        line = self.addLine(-extent, ground_y, extent, ground_y, pen)
        line.setZValue(0)

    # -- rebuild from FreeCAD state -----------------------------------------

    def rebuild(self):
        """Clear and rebuild all items from the Bent's current state."""
        self._designer._rebuilding = True
        try:
            self._rebuild_impl()
        finally:
            self._designer._rebuilding = False
        # Update label visibility for the current zoom level.
        view = getattr(self._designer, '_view', None)
        if view is not None:
            view._update_label_visibility()

    def _rebuild_impl(self):
        self.clear()
        self._snap_indicators = []
        self._member_items = {}
        self._joint_items = {}

        obj = self._designer._obj
        if obj is None:
            return

        try:
            members = obj.Members or []
        except Exception:
            return

        if not members:
            self.projection.fit([])
            self._add_grid_items()
            self._add_ground_line()
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

        # Create HandleItems — track per-member for datum translate handles
        handles = []
        member_handles = {}  # member.Name → {"start": h, "end": h}
        for m in members:
            try:
                mh = {}
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
                    mh[ep] = h
                member_handles[m.Name] = mh
            except Exception:
                pass

        # Create datum translate handles (diamond at midpoint)
        for m in members:
            try:
                mh = member_handles.get(m.Name)
                if mh and "start" in mh and "end" in mh:
                    dth = DatumTranslateHandle(
                        m, mh["start"], mh["end"], self,
                    )
                    mid = QtCore.QPointF(
                        (mh["start"].pos().x() + mh["end"].pos().x()) / 2,
                        (mh["start"].pos().y() + mh["end"].pos().y()) / 2,
                    )
                    dth.setPos(mid)
                    self.addItem(dth)
            except Exception:
                pass

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

        # Z=0 ground reference line (z=0, above grid, below members).
        self._add_ground_line()

        # Create JointItems from the Bent's Joints list.
        try:
            joints = obj.Joints or []
        except Exception:
            joints = []
        for j in joints:
            try:
                ji = JointItem(j, self.projection, self._member_items)
                self.addItem(ji)
                self._joint_items[j.Name] = ji
            except Exception as e:
                import FreeCAD
                FreeCAD.Console.PrintWarning(
                    f"BentDesigner: skip joint: {e}\n"
                )

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
        self._update_label_visibility()

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
        """Fit members in view with 10 % padding (ignores grid/ground)."""
        rect = self._members_bounding_rect()
        if rect.isEmpty():
            return
        margin = max(rect.width(), rect.height()) * 0.1
        rect.adjust(-margin, -margin, margin, margin)
        self.fitInView(rect, QtCore.Qt.KeepAspectRatio)
        self._update_label_visibility()

    def _members_bounding_rect(self):
        """Bounding rect of member items only, excluding grid/ground lines."""
        scene = self.scene()
        if not hasattr(scene, '_member_items') or not scene._member_items:
            return QtCore.QRectF()
        rect = QtCore.QRectF()
        for mi in scene._member_items.values():
            rect = rect.united(mi.sceneBoundingRect())
        return rect

    # -- label visibility ---------------------------------------------------

    def _update_label_visibility(self):
        """Hide labels when the member is smaller than the label on screen.

        Labels use ItemIgnoresTransformations, so they stay at a fixed
        screen size.  When zoomed far out, the member's screen-space
        length may be smaller than the label — hide the label in that case.
        """
        scene = self.scene()
        if not hasattr(scene, '_member_items'):
            return
        scale = abs(self.transform().m11())
        for _name, mi in scene._member_items.items():
            if mi._label is None:
                continue
            dx = mi._end_2d.x() - mi._start_2d.x()
            dy = mi._end_2d.y() - mi._start_2d.y()
            length_px = math.hypot(dx, dy) * scale
            label_w = mi._label.boundingRect().width()
            mi._label.setVisible(length_px > label_w * 1.2)


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
        from joints.intersection import _test_pair, INTERSECTION_TOLERANCE
        from objects.TimberJoint import create_timber_joint

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
            created_members = []
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
                created_members.append(member)

            self._obj.BentTemplate = template.name
            doc.recompute()

            # Create joints for the specific pairs defined in the
            # template.  Each pair is tested via intersection detection
            # to compute primary/secondary assignment and the joint
            # coordinate system.
            for tj in template.joints:
                if tj.member_a >= len(created_members):
                    continue
                if tj.member_b >= len(created_members):
                    continue
                obj_a = created_members[tj.member_a]
                obj_b = created_members[tj.member_b]
                result = _test_pair(obj_a, obj_b, INTERSECTION_TOLERANCE)
                if result is None:
                    FreeCAD.Console.PrintWarning(
                        f"Template joint ({tj.member_a}, {tj.member_b}) "
                        f"did not intersect within tolerance.\n"
                    )
                    continue
                try:
                    create_timber_joint(
                        result.primary_obj,
                        result.secondary_obj,
                        result,
                    )
                except Exception as exc:
                    FreeCAD.Console.PrintWarning(
                        f"Template joint creation failed: {exc}\n"
                    )
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
        if prop in ("Members", "Shape", "Joints"):
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
