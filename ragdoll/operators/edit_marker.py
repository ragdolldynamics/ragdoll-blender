import bpy
import blf

import ragdollc
from ragdollc import registry

from . import (
    tag_redraw,
    eyedropper,
    get_selected,
    find_transform,
    find_marker,
)
from .. import commands, scene
from ..vendor import bpx
from . import (
    PlaceholderOption,
    OperatorWithOptions,
)


def _get_scene_entity(xmember):
    member_entity = xmember.data["entity"]
    Scene = registry.get("SceneComponent", member_entity)
    return Scene.entity


def _has_same_solver(selection):
    solvers = set(_get_scene_entity(x) for x in selection)
    return len(solvers) == 1


class Reparent(bpy.types.Operator):
    bl_idname = "ragdoll.reparent"
    bl_label = "Reparent"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Change the parent of the selected marker"
    icon = "MOD_PARTICLES"

    @classmethod
    def poll(cls, context):
        selection = get_selected("rdMarker")

        if len(selection) == 2:
            if _has_same_solver(selection):
                return True

            else:
                cls.poll_message_set("Selected markers are not from the "
                                     "same solver.")
                return False
        else:
            cls.poll_message_set("Requires 2 markers selected, "
                                 "one child and then one parent.")
            return False

    def execute(self, context):
        child, parent = get_selected("rdMarker")
        child["parentMarker"] = parent.handle()

        self.report({"INFO"}, "Reparented %s -> %s" % (child, parent))
        return {"FINISHED"}


class Retarget(bpy.types.Operator):
    bl_idname = "ragdoll.retarget"
    bl_label = "Retarget"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Set recording targets to the selected marker"
    icon = "MOD_PARTICLES"

    @classmethod
    def poll(cls, context):
        selection = bpx.selection()

        if len(selection) < 1:
            cls.poll_message_set("Select one marker and one target transform")
            return False

        return True

    def execute(self, context):
        sel = bpx.selection()

        marker = find_marker(sel)
        transform = find_transform(sel)

        if not (marker and transform):
            self.report(
                {"WARNING"},
                "Select one Marker and one target transform",
            )
            return {"CANCELLED"}

        commands.retarget(transform, marker, append=False)

        self.report({"INFO"}, "Retargeted %s -> %s" % (marker, transform))

        return {"FINISHED"}


def disable_return_key_hotkeys():
    keyconfig = bpy.context.window_manager.keyconfigs.active

    # Track if any key has been keys_disabled
    keys_disabled = []

    # Iterate through all keymaps in the key configuration
    for keymap in keyconfig.keymaps:
        for keymap_item in keymap.keymap_items:
            # Check if the keymap item is bound to the Return key
            if keymap_item.type == "RET":
                keymap_item.active = False
                keys_disabled.append(keymap_item)

    return keys_disabled


class RetargetPicker(bpy.types.Operator):
    bl_idname = "ragdoll.retarget_picker"
    bl_label = "Retarget Picker"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = (
        "Interactively set recording target for the selected marker"
    )
    icon = "MOD_PARTICLES"

    @classmethod
    def poll(cls, context):
        selection = get_selected("rdMarker")

        if len(selection) != 1:
            cls.poll_message_set("Select one marker")
            return False

        return True

    def execute(self, _context):
        # It seems like, Blender freaks out when repeating a modal operator.
        # However, if that modal operator was invoked by another regular
        # operator, Blender is fine.
        # So to support "Repeat Last", here we are.
        bpy.ops.ragdoll._retarget_picker_internal("INVOKE_DEFAULT")
        return {"FINISHED"}


class RetargetPickerInternal(bpy.types.Operator):
    bl_idname = "ragdoll._retarget_picker_internal"
    bl_label = "Retarget"
    bl_options = {"INTERNAL"}
    bl_description = "Set recording target for the selected marker"

    DRAW_HANDLE = None
    DISABLED_HOTKEYS = []

    def __init__(self):
        self._marker = None
        self._target = None

    def execute(self, context):
        # Let the user know what they are retargeting
        if context.area.type == "VIEW_3D":
            self.install_draw(context)

        # Set the active tool to the Select tool in the 3D Viewport
        self._previous_mode = bpx.mode()
        self._previous_selection = bpx.selection()
        self._previous_tool = context.workspace.tools.from_space_view3d_mode(
            context.mode, create=False).idname

        bpy.ops.wm.tool_set_by_id(name="builtin.select")

        # The presence of a selected Marker is guaranteed by by the `poll`
        # method of the calling operator
        self._marker = get_selected("rdMarker")[0]

        # We need to listen for the Return key, which
        # may already be occupied by another key
        self.restore_hotkeys()
        RetargetPickerInternal.DISABLED_HOTKEYS[:] = (
            disable_return_key_hotkeys()
        )

        try:
            current_target = self._marker["destinationTransforms"][0]

        # There may not be a current target
        except IndexError:
            self._current_target = None

        else:
            current_target = scene.source_to_object(current_target)

            if isinstance(current_target, bpx.BpxBone):
                bpx.set_active(current_target.handle())
                bpx.set_mode(bpx.PoseMode)
            else:
                bpx.set_mode(bpx.ObjectMode)

            bpx.select(current_target)
            self._current_target = current_target

        context.window_manager.modal_handler_add(self)

        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            return self.cancelled(context)

        self._target = None
        sel = bpx.selection()

        if sel and sel[0] != self._marker:
            target = sel[0]

            if target.type() != "rdMarker":
                self._target = target

        valid_target = all((
            self._target is not None,
            self._target is not self._current_target
        ))

        if event.type == "RET" and valid_target:
            commands.retarget(self._target, self._marker)

            self.report({"INFO"}, "Retargeted %s -> %s" % (
                self._marker, self._target))

            return self.finished(context)

        return {"PASS_THROUGH"}

    def draw(self, context):
        # In case the operator fails to uninstall
        try:
            self._target
        except ReferenceError:
            RetargetPickerInternal.uninstall_draw()

        font_id = 0  # Default font
        blf.position(font_id, 75, 60, 0)
        blf.size(font_id, 16)
        blf.color(font_id, 1, 1, 1, 1)

        blf.draw(font_id, "MARKER:  %s" % self._marker)
        blf.position(font_id, 75, 40, 0)
        blf.draw(font_id, "TARGET:  %s" % self._target)

        if self._target:
            if self._target is self._current_target:
                status = "Already a target"
            else:
                status = "Press Return to accept"
        else:
            status = "Select new target or press Escape to cancel.."

        blf.position(font_id, 75, 20, 0)
        blf.draw(font_id, status)

    @classmethod
    def restore_hotkeys(cls):
        for keymap_item in cls.DISABLED_HOTKEYS:
            keymap_item.active = True

        cls.DISABLED_HOTKEYS[:] = []

    def exited(self, context):
        self.restore_hotkeys()

        if RetargetPickerInternal.DRAW_HANDLE:
            self.uninstall_draw()
            context.area.tag_redraw()

        bpx.set_mode(self._previous_mode)
        bpx.select(self._previous_selection)

        # Bpx should handle this..
        # TODO: Fix this
        ragdollc.scene.deselect()
        for s in self._previous_selection:
            entity = s.data.get("entity")
            if entity:
                ragdollc.scene.select(entity)

        bpy.ops.wm.tool_set_by_id(name=self._previous_tool)

    def cancelled(self, context):
        self.exited(context)
        return {"CANCELLED"}

    def finished(self, context):
        self.exited(context)
        return {"FINISHED"}

    def install_draw(self, context):
        RetargetPickerInternal.DRAW_HANDLE = (
            bpy.types.SpaceView3D.draw_handler_add(
                self.draw, (context,), "WINDOW", "POST_PIXEL"
            )
        )

    @classmethod
    def uninstall_draw(cls):
        bpy.types.SpaceView3D.draw_handler_remove(cls.DRAW_HANDLE, "WINDOW")


class Untarget(bpy.types.Operator):
    bl_idname = "ragdoll.untarget"
    bl_label = "Untarget"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Remove all targets from the selected marker"
    icon = "PIVOT_ACTIVE"

    @classmethod
    def poll(cls, context):
        selection = bpx.selection()

        if len(selection) < 1:
            cls.poll_message_set("Select one or more markers to untarget")
            return False

        return True

    def execute(self, context):
        count = 0

        for xobj in get_selected("rdMarker"):
            count += commands.untarget(xobj)

        if count > 0:
            self.report({"INFO"}, "Untargeted %d targets" % count)
        else:
            self.report({"WARNING"}, "No targets found")

        tag_redraw(context.screen)
        return {"FINISHED"}


class MergeSolvers(bpy.types.Operator):
    bl_idname = "ragdoll.merge_solvers"
    bl_label = "Merge Solvers"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Merges two solvers into one"
    icon = "PIVOT_INDIVIDUAL"

    @classmethod
    def poll(cls, context):
        selection = bpx.selection(type="rdSolver")

        if len(selection) != 2:
            cls.poll_message_set("Select two solvers to merge")
            return False

        return True

    def execute(self, context):
        solvers = bpx.selection(type="rdSolver")
        print("Merging %s" % solvers)
        commands.merge_solvers(*solvers)

        self.report({"INFO"}, "Successfully merged %s -> %s" % (
            solvers[0], solvers[1])
        )
        tag_redraw(context.screen)
        return {"FINISHED"}


class Reassign(bpy.types.Operator):
    bl_idname = "ragdoll.reassign"
    bl_label = "Reassign"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = (
        "Reassign a Marker, maintaining its mesh "
        "and destination transform(s)"
    )
    icon = "MOD_PARTICLES"

    @classmethod
    def poll(cls, context):
        selection = bpx.selection()

        if len(selection) != 2:
            cls.poll_message_set("Select one Marker and one new assignee")
            return False

        return True

    def execute(self, context):
        sel = bpx.selection()

        marker = find_marker(sel)
        transform = find_transform(sel)

        if not (marker and transform):
            self.report({"WARNING"}, "Select one Marker and one new assignee")
            return {"CANCELLED"}

        commands.reassign(transform, marker)

        self.report({"INFO"}, "Reassigned %s -> %s" % (marker, transform))

        return {"FINISHED"}


class Unparent(bpy.types.Operator):
    bl_idname = "ragdoll.unparent"
    bl_label = "Unparent"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Remove the parent from the selected marker"
    icon = "PIVOT_ACTIVE"

    @classmethod
    def poll(cls, context):
        selection = get_selected("rdMarker")

        if len(selection) == 1:
            return True

        cls.poll_message_set("Requires exactly 1 marker to be selected.")
        return False

    def execute(self, context):
        child, = get_selected("rdMarker")
        child["parentMarker"] = None
        return {"FINISHED"}


class Group(bpy.types.Operator):
    bl_idname = "ragdoll.group"
    bl_label = "Group"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Group the selected markers"
    icon = "PACKAGE"

    @classmethod
    def poll(cls, context):
        selection = get_selected("rdMarker")

        if len(selection) > 0:
            if _has_same_solver(selection):
                return True

            else:
                cls.poll_message_set(
                    "Selected markers are not from the "
                    "same solver."
                )
                return False

        else:
            cls.poll_message_set("Requires at least 1 marker selected.")
            return False

    def execute(self, context):
        selection = get_selected("rdMarker")
        commands.remove_from_group(selection)

        solver = bpx.alias(_get_scene_entity(selection[0]))

        # Name it by the root selection, for convenience
        name = "%s_rGroup" % selection[0].name()
        group = commands.create_group(solver, name=name)

        # Add selected markers to group
        commands.move_to_group(selection, group)

        tag_redraw(context.screen)
        bpx.set_active(group)

        return {"FINISHED"}


class Ungroup(bpy.types.Operator):
    bl_idname = "ragdoll.ungroup"
    bl_label = "Ungroup"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Ungroup the selected markers"
    icon = "UGLYPACKAGE"

    @classmethod
    def poll(cls, context):
        selection = get_selected("rdMarker")

        if len(selection) > 0:
            if _has_same_solver(selection):
                return True

            else:
                cls.poll_message_set("Selected markers are not from the "
                                     "same solver.")
                return False

        else:
            cls.poll_message_set("Requires at least 1 marker selected.")
            return False

    def execute(self, context):
        commands.remove_from_group(get_selected("rdMarker"))
        tag_redraw(context.screen)
        return {"FINISHED"}


class MoveToGroup(bpy.types.Operator):
    bl_idname = "ragdoll.move_to_group"
    bl_label = "Move to Group"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Move selected markers to group"
    icon = "COLLECTION_NEW"

    @classmethod
    def poll(cls, context):
        markers = get_selected("rdMarker")
        groups = get_selected("rdGroup")

        if len(markers) > 0 and len(groups) == 1:
            if _has_same_solver(markers + groups):
                return True

            cls.poll_message_set("Selected markers/group are not from the "
                                 "same solver.")
            return False

        cls.poll_message_set("Requires at least 1 marker, and only 1 group "
                             "selected.")
        return False

    def execute(self, context):
        markers = get_selected("rdMarker")
        group = get_selected("rdGroup")[0]

        commands.remove_from_group(markers)
        commands.move_to_group(markers, group)

        tag_redraw(context.screen)

        return {"FINISHED"}


class ReplaceMesh(OperatorWithOptions):
    """Replace input of the 'Mesh' shape type with another polygonal mesh

    Replace input of the 'Mesh' shape type with another polygonal or NURBS
    mesh.

    """
    bl_idname = "ragdoll.replace_mesh"
    bl_label = "Replace Mesh"
    bl_options = {"REGISTER"}
    bl_description = ("Replace input of the 'Mesh' shape type with another "
                      "polygonal mesh")

    icon = "MOD_PARTICLE_INSTANCE"

    maintain_offset: PlaceholderOption("replaceMeshMaintainOffset")
    maintain_history: PlaceholderOption("replaceMeshMaintainHistory")

    @classmethod
    def poll(cls, context):
        if not get_selected("rdMarker"):
            cls.poll_message_set("Requires at least 1 markers selected.")
            return False

        return True

    def execute(self, _context):
        # It seems like, Blender freaks out when repeating a modal operator.
        # However, if that modal operator was invoked by another regular
        # operator, Blender is fine.
        # So to support "Repeat Last", here we are.
        bpy.ops.ragdoll._replace_mesh_internal(
            "INVOKE_DEFAULT",
            maintain_offset=self.maintain_offset,
            maintain_history=self.maintain_history,
        )
        return {"FINISHED"}


class ReplaceMeshInternal(OperatorWithOptions, eyedropper.EyedropperMixin):
    bl_idname = "ragdoll._replace_mesh_internal"
    bl_label = ReplaceMesh.bl_label
    bl_options = {"INTERNAL", "UNDO"}
    bl_description = ReplaceMesh.bl_description

    maintain_offset: PlaceholderOption("replaceMeshMaintainOffset")
    maintain_history: PlaceholderOption("replaceMeshMaintainHistory")

    def hit_types(self) -> set[str]:
        return {"MESH"}

    def on_clicked(self, hit_object, context):
        selection = get_selected("rdMarker")
        if not len(selection):
            self.report({"WARNING"}, "No marker selected.")
            return {"CANCELLED"}

        marker = selection[0]
        mesh = hit_object
        if not (isinstance(mesh, bpy.types.Object) and mesh.type == "MESH"):
            self.report({"WARNING"}, "No mesh was picked.")
            return {"CANCELLED"}

        mesh = bpx.BpxObject(mesh)

        opts = {
            "maintain_history": self.maintain_history,
            "maintain_offset": self.maintain_offset,
        }

        commands.replace_mesh(marker, mesh, **opts)

        return {"FINISHED"}


def install():
    bpy.utils.register_class(Reparent)
    bpy.utils.register_class(Retarget)
    bpy.utils.register_class(Reassign)
    bpy.utils.register_class(Unparent)
    bpy.utils.register_class(MergeSolvers)
    bpy.utils.register_class(RetargetPicker)
    bpy.utils.register_class(RetargetPickerInternal)
    bpy.utils.register_class(Untarget)
    bpy.utils.register_class(Group)
    bpy.utils.register_class(Ungroup)
    bpy.utils.register_class(MoveToGroup)
    bpy.utils.register_class(ReplaceMeshInternal)
    bpy.utils.register_class(ReplaceMesh)


def uninstall():
    bpy.utils.unregister_class(Reparent)
    bpy.utils.unregister_class(Retarget)
    bpy.utils.unregister_class(Reassign)
    bpy.utils.unregister_class(Unparent)
    bpy.utils.unregister_class(MergeSolvers)
    bpy.utils.unregister_class(RetargetPicker)
    bpy.utils.unregister_class(RetargetPickerInternal)
    bpy.utils.unregister_class(Untarget)
    bpy.utils.unregister_class(Group)
    bpy.utils.unregister_class(Ungroup)
    bpy.utils.unregister_class(MoveToGroup)
    bpy.utils.unregister_class(ReplaceMesh)
    bpy.utils.unregister_class(ReplaceMeshInternal)
