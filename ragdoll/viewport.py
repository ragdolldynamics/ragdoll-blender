"""Viewport rendering module

Knows about the Blender viewport and Ragdoll rendering mechanic,
so as to bring the two together.

"""

import bpy
import bpy_extras.view3d_utils

from mathutils import Vector

import ragdollc

from .vendor import bpx
from . import constants
from .operators import manipulator

EVALUATION_REASONS = {"initialising"}


@bpx.with_cumulative_timing
def draw():
    """Render visible solvers

    This is the main entry into Ragdoll, all computations start here.

    """

    if bpx.mode() not in (bpx.ObjectMode, bpx.PoseMode):
        return

    solvers = []

    # Determine which solvers to draw
    for xobj in bpx.ls(type="rdSolver"):
        if xobj.visible():
            solvers.append(xobj)

    if len(solvers) > 0:
        manipulator.show_workspace_tool()
    else:
        manipulator.hide_workspace_tool()

    for solver in solvers:
        entity = solver.data["entity"]

        if should_evaluate():
            ragdollc.scene.evaluate(entity)

        ragdollc.viewport.draw(entity)

    clear_evaluation_reasons()


def should_evaluate():
    return len(EVALUATION_REASONS) > 0


def clear_evaluation_reasons():
    EVALUATION_REASONS.clear()


def add_evaluation_reason(reason):
    EVALUATION_REASONS.add(reason)


def save_state():
    """Fetch Blender viewport state and pass it to Ragdoll

    Ragdoll will call on this whenever it needs to know about
    the viewport it is rendering into.

    """

    ctx = bpy.context
    space = ctx.space_data
    dpi = ctx.preferences.system.ui_scale

    display_style = space.shading.type
    show_wireframes = space.overlay.show_wireframes

    tools_width = 0
    ui_width = 0
    header_height = 0
    for region in ctx.area.regions:
        if tools_width and header_height and ui_width:
            break
        if region.type == "TOOLS":
            tools_width = region.width
        elif region.type == "UI":
            ui_width = region.width
        elif constants.BLENDER_4 and region.type == "HEADER":
            header_height += region.height
        elif region.type == "TOOL_HEADER" and space.show_region_tool_header:
            header_height += region.height

    if space.show_gizmo and space.show_gizmo_navigate:
        pref_view = ctx.preferences.view
        mini_axis_type = pref_view.mini_axis_type

        if mini_axis_type == "GIZMO":
            size = dpi * pref_view.gizmo_size_navigate_v3d
            spacing = 10 * dpi
            ui_width += int(size + spacing)

        elif mini_axis_type == "NONE":
            spacing = 40 * dpi
            ui_width += int(spacing)

        else:  # MINIMAL
            size = dpi * pref_view.mini_axis_size
            spacing = 45 * dpi
            ui_width += int(size + spacing)

    else:
        spacing = int(-5 * dpi)
        ui_width += spacing

    tools_shown = space.show_region_toolbar
    tools_offset = int(8 * dpi) if tools_shown else 0

    view_matrix = ctx.region_data.view_matrix
    proj_matrix = ctx.region_data.window_matrix

    viewport_width = ctx.region.width
    viewport_height = ctx.region.height

    frustum_min, frustum_max = _frustum_box(ctx,
                                            viewport_width,
                                            viewport_height)

    canvas_x = tools_width - tools_offset
    canvas_y = header_height
    canvas_width = viewport_width - ui_width
    canvas_height = viewport_height - header_height

    state = {
        "canvasX": canvas_x,
        "canvasY": canvas_y,
        "canvasWidth": canvas_width,
        "canvasHeight": canvas_height,
        "viewportWidth": viewport_width,
        "viewportHeight": viewport_height,
        "showWireframes": show_wireframes,
        "displayStyle": display_style,
        "viewMatrix": view_matrix,
        "projectionMatrix": proj_matrix,
        "frustumMin": frustum_min,
        "frustumMax": frustum_max,
    }

    ragdollc.viewport.saveState(state)


def restore_state():
    """Restore any modifications done during save_state

    In case the global state of Blender's viewport is changed,
    such as altering the depth buffer or changing the front-facing
    nature of polygons, this is where such changes should be restored.

    """


@bpx.with_cumulative_timing
def _frustum_box(context, view_width, view_height):
    region = context.region
    region_3d = context.space_data.region_3d
    cam_pos = context.region_data.view_matrix.inverted().to_translation()
    corners = [
        [0, 0],                     # bottom left
        [0, view_height],           # top left
        [view_width, view_height],  # top right
        [view_width, 0],            # bottom right
    ]
    mid = [view_width / 2, view_height / 2]

    forward = bpy_extras.view3d_utils.region_2d_to_vector_3d(
        region, region_3d, mid
    )

    near = cam_pos + (forward * context.space_data.clip_start)
    far = cam_pos + (forward * context.space_data.clip_end)

    points = []
    for p in corners:
        f = bpy_extras.view3d_utils.region_2d_to_location_3d(
            region, region_3d, p, far)
        n = bpy_extras.view3d_utils.region_2d_to_location_3d(
            region, region_3d, p, near)
        points.append(f)
        points.append(n)

    min_x = min(p[0] for p in points)
    min_y = min(p[1] for p in points)
    min_z = min(p[2] for p in points)
    max_x = max(p[0] for p in points)
    max_y = max(p[1] for p in points)
    max_z = max(p[2] for p in points)

    return Vector((min_x, min_y, min_z)), Vector((max_x, max_y, max_z))
