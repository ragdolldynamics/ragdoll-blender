import bpy

from ragdollc import registry

from ..vendor import bpx
from ..ui import window
from .. import commands
from . import get_selected


def get_one_transform_from_selection():
    selection = bpx.selection(type=(bpx.BpxBone, bpx.BpxObject))

    # Exclude any Ragdoll object
    selection = list(filter(
        lambda s: not s.type().startswith("rd"), selection)
    )

    if selection:
        return selection[-1]


def get_one_solver(context=None):
    context = context or bpy.context
    # Solver from current active/pinned object
    if context.object:
        xobj = bpx.BpxType(context.object)
        if xobj.type() == "rdSolver":
            return xobj

    # Solver from last selected marker
    markers = get_selected("rdMarker")
    if markers:
        marker = markers[-1]
        scene_ = registry.get("SceneComponent", marker.data["entity"])
        return bpx.alias(scene_.entity)

    # Last solver listed out from scene
    solvers = bpx.ls(type="rdSolver")
    if solvers:
        return solvers[-1]


class RetargetMenuOp(bpy.types.Operator):
    bl_idname = "ragdoll.ui_menu_retarget"
    bl_label = "Retarget"
    bl_options = {"INTERNAL", "UNDO"}
    bl_description = ("Set recording target to selected marker, "
                      "or hold Ctrl to open Retarget UI")
    icon = "MOD_PARTICLES"

    @classmethod
    def poll(cls, context):
        if not bpx.ls(type="rdSolver"):
            cls.poll_message_set("No Ragdoll solvers in the current scene")
            return False
        return True

    # Breadcrumb for menu item drawing
    __ctrl_invoke__ = True

    def invoke(self, context, event):
        if event.ctrl:
            bpy.ops.ragdoll.retarget_window()
            return {"FINISHED"}
        else:
            return self.execute(context)

    def execute(self, context):
        try:
            bpy.ops.ragdoll.retarget_picker()  # See edit_marker.py
        except RuntimeError as e:
            # operator poll() failed
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        return {"FINISHED"}


class RetargetWindow(bpy.types.Operator):
    bl_idname = "ragdoll.retarget_window"
    bl_label = "Retarget Window"
    bl_options = {"REGISTER"}
    bl_description = "Show solver retargeting window"

    WIDTH = 1200
    HEIGHT = 610
    ROWS = 11  # This row count fits best

    @classmethod
    def poll(cls, context):
        if not bpx.ls(type="rdSolver"):
            cls.poll_message_set("No Ragdoll solvers in the current scene")
            return False
        return True

    def execute(self, context):
        solver = get_one_solver(context)
        open_retarget_window(solver, self.WIDTH, self.HEIGHT, context)
        return {"FINISHED"}

    @classmethod
    def compute_row_count(cls, context):
        """Compute solver targets list UI row count base on window height

        So that when retarget window is resized, targets list UI gets resized
        with it.

        """

        height_per_row = 29  # Roughly
        default_row_count = cls.ROWS
        default_window_height = cls.HEIGHT
        default_targets_ui_height = height_per_row * default_row_count

        #  _____________________________________
        # |_____________________________ - O X  |  ...
        # |                                     |    :
        # |                                     |    : => fixed_area_height
        # |  _________________________________  |    :
        # | | v Targets                       | |  ..:
        # | |---------------------------------| |  ...
        # | | O rMarker_rGround   * rGround   | |    :
        # | | O rMarker_Cube      * Cube      | |    : => height_of_targets_ui
        # | |                                 | |    :
        # | |_________________________________| |  ..:
        # |_____________________________________|

        fixed_area_height = default_window_height - default_targets_ui_height
        current_targets_ui_height = context.window.height - fixed_area_height
        new_row_counts = current_targets_ui_height // height_per_row

        return max(new_row_counts, default_row_count)


def open_retarget_window(solver: bpx.BpxType, w: int, h: int, context=None):

    context = context or bpy.context
    solver = solver.handle()
    solver_ui = solver.rdSolverUi

    prev_win = None
    if solver_ui.targets_window:
        for win in context.window_manager.windows:
            if str(hash(win)) == solver_ui.targets_window:
                prev_win = win
                break

    if prev_win:
        # Close previous retarget window if found, e.g. minimized.
        #
        _areas = prev_win.screen.areas
        _space = _areas[0].spaces[0]
        # Check ui status.
        # If it is being used to display something else, leave it be.
        _is_retarget_win = (
                len(_areas) == 1 and
                _areas[0].type == "PROPERTIES" and
                _space.context == "PHYSICS" and
                _space.pin_id == solver
        )
        if _is_retarget_win:
            with context.temp_override(window=prev_win):
                bpy.ops.wm.window_close()

    win = window.create_window(w, h, window.E_SPACE_PROPERTIES)
    solver_ui.targets_window = str(hash(win))

    win_area = win.screen.areas[0]
    win_space = win_area.spaces[0]
    win_space.show_region_header = False
    win_space.use_pin_id = True
    win_space.pin_id = solver
    win_space.context = "PHYSICS"

    # Hide properties panel context tabs (left side tab bar)
    bpy.ops.screen.region_toggle(region_type="NAVIGATION_BAR")


class Retarget(bpy.types.Operator):
    bl_idname = "ragdoll.ui_retarget"
    bl_label = "Set/Append Marker Target"
    bl_options = {"INTERNAL", "UNDO"}
    bl_description = "Set recording target to the selected marker"

    marker: bpy.props.IntProperty(
        options={"SKIP_SAVE"},
        description="Marker entity Id. If 0, a marker needs to be selected",
    )
    append: bpy.props.BoolProperty(
        default=False,
        options={"SKIP_SAVE"},
        description="Append recording target to marker",
    )

    @classmethod
    def poll(cls, context):
        if context.space_data.type == "PROPERTIES":
            # In Retarget UI.

            xobj = bpx.BpxType(context.object)
            if xobj.type() == "rdSolver":

                if context.space_data.use_pin_id:
                    # Marker is set by UI, so just need to select transform.
                    if get_one_transform_from_selection():
                        return True

                    else:
                        cls.poll_message_set("Select one object or pose bone.")
                        return False
                else:
                    # If solver object is not pinned, it doesn't make sense
                    # to continue. Because the solver panel will no longer
                    # active after selecting a transform.
                    cls.poll_message_set("Please enable 'Pin ID'.")
                    return False
        else:
            # For Retarget UI only
            return False

    def execute(self, context):
        transform = get_one_transform_from_selection()
        marker = bpx.alias(self.marker)

        commands.retarget(transform, marker, append=self.append)

        self.report({"INFO"}, "Retargeted %s -> %s" % (marker, transform))
        return {"FINISHED"}


class Untarget(bpy.types.Operator):
    bl_idname = "ragdoll.ui_untarget"
    bl_label = "Remove Marker Target"
    bl_options = {"INTERNAL", "UNDO"}
    bl_description = "Remove all recording targets from selected marker"

    marker: bpy.props.IntProperty(
        options={"SKIP_SAVE"},
        description="Marker entity Id.",
    )

    @classmethod
    def poll(cls, context):
        if context.space_data.type == "PROPERTIES":
            # In Retarget UI.
            xobj = bpx.BpxType(context.object)
            if xobj.type() == "rdSolver":
                return True

            else:
                cls.poll_message_set("Active object is not a solver.")
                return False
        else:
            # For Retarget UI only
            return False

    def execute(self, context):
        marker = bpx.alias(self.marker)
        commands.untarget(marker)
        return {"FINISHED"}


def install():
    bpy.utils.register_class(RetargetWindow)
    bpy.utils.register_class(RetargetMenuOp)
    bpy.utils.register_class(Retarget)
    bpy.utils.register_class(Untarget)


def uninstall():
    bpy.utils.unregister_class(RetargetWindow)
    bpy.utils.unregister_class(RetargetMenuOp)
    bpy.utils.unregister_class(Retarget)
    bpy.utils.unregister_class(Untarget)
