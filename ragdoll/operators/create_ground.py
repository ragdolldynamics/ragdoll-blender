import bpy

from .. import scene, constants
from ..vendor import bpx


class CreateGround(bpy.types.Operator):
    bl_idname = "ragdoll.create_ground"
    bl_label = "Create Ground"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Create a ground for the current solver"

    @classmethod
    def poll(cls, context):
        if not scene.find_or_create_current_solver():
            cls.poll_message_set("No solver present")
            return False

        return True

    def execute(self, context):
        cube = bpx.create_object(bpx.e_cube, name="rGround")

        handle = cube.handle()
        handle.location = (0, 0, -0.025)
        handle.scale = (2, 2, 0.025)
        handle.display_type = "WIRE"

        with bpx.object_mode():
            bpx.select(cube)
            bpy.ops.ragdoll.assign_markers()

            marker = scene.object_to_marker(cube)
            marker["inputType"] = constants.InputKinematic
            marker["displayType"] = constants.DisplayWire

        return {"FINISHED"}


def install():
    bpy.utils.register_class(CreateGround)


def uninstall():
    bpy.utils.unregister_class(CreateGround)
