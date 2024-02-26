import bpy
import collections

import ragdollc
from ragdollc import registry

from .. import scene, types, constants, log, viewport, preferences
from ..vendor import bpx
from ..ui import icons
from . import find_hotkey


class ManipulatorOp(bpy.types.Operator):
    bl_idname = "ragdoll.manipulator"
    bl_label = "Ragdoll Manipulator"

    # Only permit 1 Manipulator to be active at any given time
    RUNNING = False

    # Increment time at even increments for Live Mode
    TIMER = None

    # For referencing an instance of `DisabledHud` while tool is active
    HUD_DISABLER = None

    @classmethod
    def poll(cls, context):
        """Can the operator be called?"""
        if cls.RUNNING:
            cls.poll_message_set("Already running")
            return False

        return True

    def cancel(self, context):
        """Safe place for cleaning

        This function gets called when {"CANCELLED"} returned or on Blender
        exiting, before __del__ and the destruction of this operator.

        So do necessary cleanup here. Especially when Blender is exiting, the
        world is going to collapse and unstable after this point, which can
        easily turn to "access violation" crash if something went wrong.

        """

        ManipulatorOp.HUD_DISABLER = None
        self.on_exit(context)

    def execute(self, context):
        solver = scene.find_or_create_current_solver()

        # Can happen if creating a new scene with the manipulator still open
        if not solver:
            return {"CANCELLED"}

        entity = solver.data.get("entity")

        if not ragdollc.viewport.manipulatorEnter(entity):
            return {"CANCELLED"}

        self._is_alt_navigation = is_alt_navigation()
        self._is_dragging = False
        self._live_time = 0
        self._last_mode = -1
        self._attribute_sets = collections.OrderedDict()
        self._edited = False

        # Listen for cursor position when hovering the viewport, except
        # when hovering the "tools" area where workspace buttons are.
        #
        #  __ __________________________________ _________
        # |  |__________________________________|         |
        # |  |                                  |         |
        # |  |                                  |         |
        # |  |                                  |         |
        # |  |                                  |         |
        # |  |                                  |         |
        # |  |        Manipulator Area          |         |
        # |  |                                  |         |
        # |  |                                  |         |
        # |  |                                  |         |
        # |  |                                  |         |
        # |__|__________________________________|_________|
        #
        #
        self._tools_panel_size = _find_tools_panel_size(context)
        self._header_panel_height = _find_header_panel_height(context)

        # For Live Mode, we'll want to refresh the viewport at a rate
        # consistent with normal playback, so we'll use the native FPS
        fps = context.scene.render.fps
        timestep = 1.0 / fps

        ManipulatorOp.TIMER = context.window_manager.event_timer_add(
            timestep, window=context.window)

        ManipulatorOp.RUNNING = True
        if not ManipulatorOp.HUD_DISABLER:
            ManipulatorOp.HUD_DISABLER = DisabledHud(context)

        # Let the user orbit around the selected Marker
        FitToViewHotkey.activate()

        # Listen for attribute changes within the Manipulator
        ragdollc.handlers.attributeSet.append(self.on_attribute_set)

        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Manipulator activated")
        return {"RUNNING_MODAL"}

    def on_exit(self, context):
        frame = context.scene.frame_current
        ragdollc.scene.setCurrentFrame(frame)
        ragdollc.viewport.manipulatorExit()

        ManipulatorOp.RUNNING = False
        FitToViewHotkey.deactivate()

        if context.area:
            context.area.tag_redraw()

        wm = context.window_manager
        wm.event_timer_remove(ManipulatorOp.TIMER)

        ragdollc.handlers.attributeSet.remove(self.on_attribute_set)

        # Trigger evaluation
        viewport.add_evaluation_reason("manipulatorExit")

        return {"FINISHED"}

    def modal(self, context, event):
        if self._edited:
            # Blender typically only considers undo
            # when exiting an operator.
            bpy.ops.ed.undo_push(
                message="Manipulator edited one or more properties"
            )

            # It's been handled
            self._edited = False

        if event.type == "TIMER":
            return self.on_timer_event(context, event)

        # Exit if user activates a different tool
        tools = context.workspace.tools
        current_tool = tools.from_space_view3d_mode(context.mode, create=False)
        if not current_tool or current_tool.idname != WorkspaceTool.bl_idname:
            ManipulatorOp.HUD_DISABLER = None  # Restore HUD on tool changed.
            return self.on_exit(context)

        # Also called on LEFT_CTRL pressed etc.
        mouse_events = (
            "LEFTMOUSE",
            "RIGHTMOUSE",
            "MIDDLEMOUSE",
            "MOUSEMOVE",
        )

        if event.type in mouse_events:
            return self.on_mouse_event(context, event)
        else:
            return {"PASS_THROUGH"}

    def on_timer_event(self, context, event):
        manip = registry.ctx("Manipulator")

        if not manip.active:
            return {"PASS_THROUGH"}

        self.flush_attribute_sets()

        if manip.mode != self._last_mode:
            self._live_time = 0
            frame = context.scene.frame_current
            ragdollc.scene.setCurrentFrame(frame)
            viewport.add_evaluation_reason("mode_changed")

        self._last_mode = manip.mode

        if manip.mode != manip.LiveMode:
            return {"PASS_THROUGH"}

        ragdollc.viewport.manipulatorStep()

        live = registry.ctx("LiveManipulator")
        if not live.isRunning:
            return {"PASS_THROUGH"}

        self._live_time += 1

        ragdollc.scene.setCurrentFrame(self._live_time)

        # Can be None when togging fullscreen
        area = context.area
        if area is not None:
            area.tag_redraw()

        # Trigger evaluation
        viewport.add_evaluation_reason("time_changed")

        return {"PASS_THROUGH"}

    def on_mouse_event(self, context, event):
        if self._is_alt_navigation:
            is_navigating = event.alt
        else:
            is_navigating = event.type == "MIDDLEMOUSE"

        if context.area is None:
            return self.on_exit(context)

        if _is_mouse_in_other_viewport(event, context):
            # Leave and activate in other viewport
            return self.on_exit(context)

        # Leave room for Blender border elements, primarily resizing a panel
        padding = 5

        out_of_view = any((
            # Prevent blocking of left-hand side tools panel
            (event.mouse_region_x < self._tools_panel_size.x),
            (event.mouse_region_y < 0),

            (event.mouse_region_x > context.area.width - padding),
            event.mouse_region_y > (

                # Prevent blocking of header panel, coordinates
                # are from bottom-up.
                context.area.height - self._header_panel_height - padding
            )
        ))

        # Let Blender handle it, unless we're dragging something
        if out_of_view and not self._is_dragging:
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            data = types.to_rdevent(event)

            if not self._is_alt_navigation:
                data = remap_to_industry_keys(data)

            self.on_mouse_moved(context, data)

        elif not is_navigating:
            data = types.to_rdevent(event)

            if not self._is_alt_navigation:
                data = remap_to_industry_keys(data)

            if event.value == "PRESS":
                if not self._is_dragging:
                    self.on_mouse_pressed(context, data)

                self._is_dragging = True

            if event.value == "RELEASE":
                if self._is_dragging:
                    self.on_mouse_released(context, data)

                self._is_dragging = False

        if is_navigating:
            return {"PASS_THROUGH"}
        else:
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

    def on_mouse_pressed(self, context, data):
        ragdollc.viewport.mousePressed(data)

    def on_mouse_released(self, context, data):
        ragdollc.viewport.mouseReleased(data)

    def on_mouse_moved(self, context, data):
        ragdollc.viewport.mouseMoved(data)

    def on_attribute_set(self, entity, key, value):
        """An attribute was set by Ragdoll

        Consolidate attribute edits from a single draw, as there
        can be dozens or hundreds if many entities are modified en-masse

        Store as entity/key pairs, such that only the latest
        attribute set is remembered. No point setting the
        same attribute multiple times

        """

        try:
            self._attribute_sets[(entity, key)] = types.to_bltype(value)

        except Exception:
            # This is a bug, but we cannot raise any exceptions from
            # a callback.
            import traceback
            traceback.print_exc()

    @bpx.with_cumulative_timing
    def flush_attribute_sets(self):
        """Consolidated attribute sets

        Ragdoll can trigger multiple attribute sets in a short span of time

        """

        while self._attribute_sets:
            (entity, key), value = self._attribute_sets.popitem()
            marker = bpx.alias(entity)

            if not marker:
                # This would mean that somehow an entity was interacted
                # with through the Manipulator that didn't have a corresponding
                # object in Blender. This is our bad.
                log.warning(
                    "Marker for entity %s not found, this is a bug" % entity
                )
                continue

            try:
                marker[key] = value

            except bpx.ExistError:
                self.report(
                    {"WARNING"},
                    "%s[%s] not found, this is a bug" % (marker, key)
                )

            except Exception as e:
                import traceback
                traceback.print_exc()

                self.report(
                    {"WARNING"},
                    "Failed to do `%s['%s'] = %s`, this is a bug: %s"
                    % (marker, key, value, str(e))
                )

            else:
                # Let the manipulator know there's an edit waiting
                self._edited = True


class DisabledHud:
    """Disable viewport HUD on __init__ and restore HUD on __del__

    IMPORTANT:
        We need to be careful when restoring HUD, blender will crash if the
        timing is bad.
        E.g. Restoring HUD (DisabledHud.__del__ called) when an operator that
        owns an instance of this class is being killed on:
        1) Blender exit or,
        2) Viewport maximized (Ctrl + Space).

    """

    def __init__(self, context):
        self._hud_states = dict()
        self._space_attributes = (
            "show_gizmo_tool",
            "show_gizmo_navigate",
            "show_region_ui",
            "show_region_hud",
            "show_region_tool_header",
        )
        self._overlay_attributes = (
            "show_text",
            "show_stats",
        )
        self._preferences_view = (

            # These can block the Manipulator and refuse to disappear,
            # as the mouse never leaves the item as far as Blender is concerned
            "show_tooltips",
        )
        self.remember_hud(context)
        self.disable_hud(context)

    def __del__(self):
        self.restore_hud()

    def remember_hud(self, context):
        states = {}

        for attr in self._space_attributes:
            states[attr] = getattr(context.space_data, attr)

        for attr in self._overlay_attributes:
            states[attr] = getattr(context.space_data.overlay, attr)

        for attr in self._preferences_view:
            states[attr] = getattr(context.preferences.view, attr)

        self._hud_states[context] = states

    def disable_hud(self, context):
        for attr in self._space_attributes:
            # Don't set it to False unless it's True,
            # since doing that will flicker some elements,
            # primarily the show_region_hud
            if getattr(context.space_data, attr):
                setattr(context.space_data, attr, False)

        for attr in self._overlay_attributes:
            if getattr(context.space_data.overlay, attr):
                setattr(context.space_data.overlay, attr, False)

        for attr in self._preferences_view:
            if getattr(context.preferences.view, attr):
                setattr(context.preferences.view, attr, False)

    def restore_hud(self):
        for context, record in self._hud_states.items():
            for attr in self._overlay_attributes:
                if record.get(attr, False):
                    setattr(context.space_data.overlay, attr, True)

            for attr in self._space_attributes:
                if record.get(attr, False):
                    setattr(context.space_data, attr, True)

            for attr in self._preferences_view:
                if record.get(attr, False):
                    setattr(context.preferences.view, attr, True)

        self._hud_states.clear()


def is_alt_navigation():
    """Is the user navigating using the ALT key?

    Blender provides 2 methods of navigating, and Ragdoll needs to know
    whether it can look at the ALT key for interactions or whether it
    should leave it for host navigation.

    """

    user_keyconfig = bpy.context.window_manager.keyconfigs.user
    view3d_keymap = user_keyconfig.keymaps["3D View"]

    for key, data in view3d_keymap.keymap_items.items():
        if key == "view3d.rotate" and data.value == "PRESS":
            if data.type == "MIDDLEMOUSE" and not data.alt:
                # Blender
                return False

            elif data.type == "LEFTMOUSE" and data.alt:
                # Industry
                return True

    return False


def remap_to_industry_keys(data):
    """Remap Blender style keybindings to Industry compatible (Ragdoll)

    | Action       | Blender            | Industry (Ragdoll) |
    | ------------ | ------------------ | ------------------ |
    | Select       | LMB                | LMB                |
    | Multi-Select | LMB + Shift        | LMB + Shift        |
    | Translate    | LMB + Ctrl         | MMB                |
    | Rotate       | LMB + Ctrl + Alt   | MMB + Ctrl         |
    | Scale        | LMB + Ctrl + Shift | LMB + Ctrl         |
    | Asymmetry    | LMB + Ctrl         | LMB + Ctrl         |  # Limit Mode
    | Snap         | LMB + Shift        | LMB + Shift        |  # Limit Mode

    """
    manip = registry.ctx("Manipulator")

    if manip.mode == manip.ShapeMode:

        LEFT_OR_MOVE = data["button"] == 0 or data["button"] == -1
        if LEFT_OR_MOVE:

            if data["ctrl"] and not data["shift"] and not data["alt"]:
                # Translate: [ LMB + Ctrl ] -> [ MMB ]
                data["button"] = 2
                data["ctrl"] = False
                data["shift"] = False
                data["alt"] = False

            elif data["ctrl"] and not data["shift"] and data["alt"]:
                # Rotate: [ LMB + Ctrl + Alt ] -> [ MMB + Ctrl ]
                data["button"] = 2
                data["ctrl"] = True
                data["shift"] = False
                data["alt"] = False

            elif data["ctrl"] and data["shift"] and not data["alt"]:
                # Scale: [ LMB + Ctrl + Shift ] -> [ LMB + Ctrl ]
                data["button"] = 0
                data["ctrl"] = True
                data["shift"] = False
                data["alt"] = False

    return data


def _find_tools_panel_size(context):
    for region in context.area.regions:
        if region.type == "TOOLS":
            return bpx.Vector((region.width, region.height, 0))
    return bpx.Vector()


def _find_header_panel_height(context):
    for region in context.area.regions:
        if constants.BLENDER_4:
            if region.type == "HEADER":
                return region.height
        else:
            if context.space_data.show_region_tool_header:
                if region.type == "TOOL_HEADER":
                    return region.height
    return 0


def _is_mouse_in_other_viewport(event, context):
    current_area = context.area

    for area in context.screen.areas:
        # Only consider other views, not the current one
        if area == current_area:
            continue

        # Only consider other 3d views
        if area.ui_type != "VIEW_3D":
            continue

        # Is it within this other viewport?
        is_inside_x = 0 <= (event.mouse_x - area.x) <= area.width
        is_inside_y = 0 <= (event.mouse_y - area.y) <= area.height

        if is_inside_x and is_inside_y:
            return True

    return False


class WorkspaceTool(bpy.types.WorkSpaceTool):
    registered = False

    @staticmethod
    def keymap(event_type, event_value, *modifiers):
        key = {"type": event_type, "value": event_value}
        key.update({mod: True for mod in modifiers})
        return (
            ManipulatorOp.bl_idname,
            key,
            {"properties": None},
        )

    bl_label = "Manipulator"
    bl_idname = "ragdoll.manipulator_tool"
    bl_space_type = "VIEW_3D"
    bl_description = "Enter Ragdoll manipulation workspace"
    bl_icon = icons.fname_to_icon_path("ragdoll.manipulator_tool")
    bl_widget = None
    bl_keymap = (
        keymap("MOUSEMOVE", "NOTHING"),
        keymap("MOUSEMOVE", "NOTHING", "ctrl"),
        keymap("MOUSEMOVE", "NOTHING", "shift"),
        keymap("MOUSEMOVE", "NOTHING", "shift", "ctrl"),
    )
    idname_fallback = "builtin.select_box"

    @staticmethod
    def draw_settings(context, layout, _tool):
        scene = context.scene
        space = context.space_data

        toolbar_visible = any((
            getattr(space, "show_region_toolbar", False),
            getattr(space, "show_region_header", False)
        ))

        if toolbar_visible:
            layout.label(
                text="Ragdoll",
                icon_value=icons.fname_to_icon_id["logo2.png"],
            )

        layout.separator()
        layout.prop(
            scene.tool_settings,
            "lock_object_mode",
            text="Lock Object Modes"
        )

        # Solver selector
        if context.mode == "OBJECT":
            # TODO: Not ready yet.
            # tokens = getattr(scene, _c.Solver_Key)
            # current = to_cpp.manip_get_active_solver_id()
            # if len(tokens) < 3:
            #     for token in tokens:
            #         solver = token.rdx_data()
            #         is_active = solver.rdx_uuid == current
            #         handle = solver.id_data
            #         layout.operator(
            #             "ragdoll.set_solver_active",
            #             text=handle.name,
            #             icon="VIEW3D",
            #             depress=is_active
            #         ).rdx_uuid = solver.rdx_uuid
            # else:
            #     text = "Select Solver"
            #     if current:
            #         solver = commands2.data_from_id(scene, current)
            #         text = solver.id_data.name
            #     layout.operator_menu_enum(
            #         "ragdoll.set_solver_active_from_enum",
            #         "solvers",
            #         text=text,
            #         icon="VIEW3D",
            #     )
            pass

        elif context.mode == "POSE":
            pass

    @classmethod
    def install(cls):
        bpy.utils.register_tool(
            cls,
            after={"builtin.transform"},
            separator=True,
            group=False,
        )
        cls.registered = True

    @classmethod
    def uninstall(cls):
        bpy.utils.unregister_tool(cls)
        cls.registered = False


class ObjectWorkspaceTool(WorkspaceTool):
    bl_context_mode = "OBJECT"


class PoseWorkspaceTool(WorkspaceTool):
    bl_context_mode = "POSE"


def _add_manipulator_keymap(key):
    """Add manipulator hotkey entry to addon config"""

    addon_keyconfigs = bpy.context.window_manager.keyconfigs.addon
    addon_view3d_keymaps = addon_keyconfigs.keymaps.new(
        name="3D View Generic",
        space_type="VIEW_3D"
    )
    new_keymap = addon_view3d_keymaps.keymap_items.new(
        idname=ManipulatorOp.bl_idname,
        type=key,
        value="PRESS",
    )
    new_keymap.active = True
    addon_view3d_keymaps.keymap_items.update()


def _redraw_toolbar():
    """Once changed, the toolbar needs to be explicitly told to update"""
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for region in area.regions:
                if region.type == "TOOLS":
                    region.tag_redraw()


def show_workspace_tool():
    """Draw a Ragdoll button in Blender's native left-hand toolbar"""
    if ObjectWorkspaceTool.registered:
        return

    ObjectWorkspaceTool.install()
    _redraw_toolbar()


def hide_workspace_tool():
    """Hide Ragdoll button, if visible"""
    if not ObjectWorkspaceTool.registered:
        return

    ObjectWorkspaceTool.uninstall()
    _redraw_toolbar()


class FitToViewHotkey(bpy.types.Operator):
    """A custom fit-to-view when using the Manipulator"""

    bl_idname = "view3d.view_selected_marker"
    bl_label = "View Selected Marker"

    KEYMAP = None
    PREFERENCE_BACKUP = None

    @classmethod
    def activate(cls):
        if not cls.KEYMAP:
            keyconfigs = bpy.context.window_manager.keyconfigs
            keymap_press = keyconfigs.addon.keymaps.new(
                name="3D View Generic",
                space_type="VIEW_3D"
            )

            # Associate with the current hotkey for viewing selected
            hotkey = find_hotkey("view3d.view_selected") or "F"
            cls.KEYMAP = keymap_press.keymap_items.new(
                "view3d.view_selected_marker", hotkey, "PRESS"
            )

            keymap_press.keymap_items.update()

        cls.KEYMAP.active = True

        # If "Orbit Around Selection" is enabled, camera uses selection as
        # the pivot point. So when marker is selected, its empty object's
        # origin will be used as orbiting point, which is at world center
        # by default. Therefore, we need to disable that temporarily. We
        # don't need that in manipulator mode anyway.
        i_ = bpy.context.preferences.inputs
        cls.PREFERENCE_BACKUP = {
            "use_rotate_around_active": i_.use_rotate_around_active,
        }
        i_.use_rotate_around_active = False

    @classmethod
    def deactivate(cls):
        if cls.KEYMAP:
            cls.KEYMAP.active = False

        backup = cls.PREFERENCE_BACKUP
        inputs = bpy.context.preferences.inputs
        inputs.use_rotate_around_active = backup["use_rotate_around_active"]

    def execute(self, context):
        # Find the 3D view area
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                break
        else:
            # NOTE: We pass through, rather than cancel,
            # to allow Blender's native hotkey to pick up on this
            return {"PASS_THROUGH"}

        # Get the 3D view region and region data
        for region in area.regions:
            if region.type == "WINDOW":
                break
        else:
            return {"PASS_THROUGH"}

        selection = bpx.selection(type="rdMarker", active=True)
        if not selection:
            return {"PASS_THROUGH"}

        marker = selection[0]
        entity = marker.data["entity"]

        # Take solver offset into account
        solver_entity = ragdollc.registry.get("SceneComponent", entity).entity
        solver_mtx = ragdollc.registry.get("RestComponent", solver_entity)
        solver_mtx = types.to_bltype(solver_mtx.value)

        # NOTE: This won't work without an active licence
        out_matrix = ragdollc.scene.outputMatrix(entity)
        out_matrix = types.to_bltype(out_matrix)
        out_matrix = solver_mtx @ out_matrix

        # Define the target position, in the middle of the Marker
        shape_offset = marker["shapeOffset"].read()
        target_position = out_matrix @ shape_offset

        space = area.spaces.active
        rv3d = space.region_3d

        # Set the view location
        rv3d.view_location = target_position

        # Distance should be the maximum size of the bounding box,
        # here approximated via the shape extents
        shape_extents = marker["shapeExtents"].read()
        rv3d.view_distance = max(shape_extents) * 2

        return {"FINISHED"}


def install():
    bpy.utils.register_class(ManipulatorOp)
    bpy.utils.register_class(FitToViewHotkey)


def uninstall():
    bpy.utils.unregister_class(ManipulatorOp)
    bpy.utils.unregister_class(FitToViewHotkey)
