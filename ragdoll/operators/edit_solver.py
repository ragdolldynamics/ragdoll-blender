import bpy

from ..vendor import bpx
from .. import commands, util


class CacheAll(bpy.types.Operator):
    bl_idname = "ragdoll.cache_all"
    bl_label = "Cache"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Cache the simulation, but to not record anything"
    icon = "NODE_SEL"

    @classmethod
    def poll(cls, context):
        if not bpx.ls(type="rdSolver"):
            cls.poll_message_set("No Ragdoll solvers in the current scene")
            return False

        return True

    def execute(self, context):
        solvers = bpx.selection(type="rdSolver") or bpx.ls(type="rdSolver")

        wm = context.window_manager
        wm.progress_begin(0, 100)

        for percentage in commands.cache_iter(solvers):
            wm.progress_update(int(percentage))

        wm.progress_end()
        return {"FINISHED"}


class Uncache(bpy.types.Operator):
    bl_idname = "ragdoll.uncache"
    bl_label = "Uncache"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Uncache the simulation"
    icon = "NODE"

    @classmethod
    def poll(cls, context):
        if not bpx.ls(type="rdSolver"):
            cls.poll_message_set("No Ragdoll solvers in the current scene")
            return False

        return True

    def execute(self, context):
        solvers = bpx.selection(type="rdSolver") or bpx.ls(type="rdSolver")

        for solver in solvers:
            commands.uncache(solver)

        util.touch_initial_state()
        return {"FINISHED"}


def install():
    bpy.utils.register_class(CacheAll)
    bpy.utils.register_class(Uncache)


def uninstall():
    bpy.utils.unregister_class(CacheAll)
    bpy.utils.unregister_class(Uncache)
