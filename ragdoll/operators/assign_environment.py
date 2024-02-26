import bpy
import ragdollc
from ..vendor import bpx
from .. import util, scene, constants, commands
from . import (
    PlaceholderOption,
    OperatorWithOptions,
)


class AssignEnvironment(OperatorWithOptions):
    """Assign a Ragdoll environment to the selected mesh

    Treat the selected mesh as a collider with support for polygonal
    geometry that does not need to be convex. It cannot be animated
    nor deforming.

    """

    bl_idname = "ragdoll.assign_environment"
    bl_label = "Assign Environment"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Assign a Ragdoll environment to the selected mesh"
    icon = "MESH_GRID"

    @classmethod
    def _selection(cls):
        selection = bpx.selection(type=bpx.BpxObject)

        # Only meshes are supported
        meshes = list(filter(
            lambda s: isinstance(
                s.handle().data, bpy.types.Mesh), selection)
        )

        return meshes

    @classmethod
    def poll(cls, context):
        selection = cls._selection()

        if not selection:
            cls.poll_message_set("No selected Object")
            return False

        return True

    def execute(self, context):
        selection = self._selection()
        assembly = util.find_assembly()

        with bpx.maintained_selection(context):
            solver = scene.find_or_create_current_solver()

            if not solver:
                # TODO: Consider "Auto Create Ground" flag
                # TODO: Consider "Auto Compute Scene Scale" flag
                bpy.ops.ragdoll.create_solver()

                if self.create_ground:
                    bpy.ops.ragdoll.create_ground()

                new_solver = True

            solver = scene.find_or_create_current_solver()
            assert solver

            environments = []
            last_index = len(selection) - 1

            for index, xobj in enumerate(selection):
                existing_marker = scene.object_to_marker(xobj)

                if existing_marker is not None:
                    # Append to existing hierarchy
                    environments.append(existing_marker)
                    continue

                if isinstance(xobj, bpx.BpxBone):
                    # Include armature name
                    obj_name = "%s.%s" % (xobj.handle().name, xobj.name())
                else:
                    obj_name = xobj.name()

                env = scene.create("rdEnvironment", "rEnvironment_%s" % obj_name)
                environments.append(env)
                bpx.link(env, assembly)

                # Fill this in as early as possible, such that it
                # is accessible without evaluation
                xobj.data["entity"] = env.data["entity"]
                env["inputGeometry"] = {"object": xobj.handle()}

                # Append to solver
                solver["members"].append({"object": env.handle()})

        if not environments:
            self.report({"WARNING"}, "No environments were created")
            return {"CANCELLED"}

        util.touch_initial_state(context)

        if not bpy.app.background:
            ui_open_physics_tab(context)

        return {"FINISHED"}


def ui_open_physics_tab(context):
    """Open physics tab to show env assignment"""

    biggest = None
    maxsize = 0

    # Find biggest properties panel
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "PROPERTIES":
                if area.width >= 0 and area.height >= 0:
                    size = area.width * area.height
                    if size > maxsize:
                        maxsize = size
                        biggest = area

    # Switch to physics tab
    if biggest:
        for space in biggest.spaces:
            if space.type == "PROPERTIES":
                try:
                    space.context = "PHYSICS"
                except TypeError:
                    # Possibly GUI is not updated yet, but that's fine.
                    # Could happen when building physics scene via script.
                    pass


def install():
    bpy.utils.register_class(AssignEnvironment)


def uninstall():
    bpy.utils.unregister_class(AssignEnvironment)
