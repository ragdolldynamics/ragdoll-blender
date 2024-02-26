import bpy

from ..vendor import bpx
from .. import scene, util


class CreateSolver(bpy.types.Operator):
    bl_idname = "ragdoll.create_solver"
    bl_label = "Create Solver"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Create a new solver"

    def execute(self, context):
        solver = scene.create("rdSolver", name="rSolver")
        assembly = util.find_assembly()
        bpx.link(solver, assembly)

        util.touch_initial_state(context)

        return {"FINISHED"}


def install():
    bpy.utils.register_class(CreateSolver)


def uninstall():
    bpy.utils.unregister_class(CreateSolver)
