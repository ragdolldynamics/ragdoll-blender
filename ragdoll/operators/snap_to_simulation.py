import bpy

from . import OperatorWithOptions
from .. import commands
from ..vendor import bpx


class SnapToSimulation(OperatorWithOptions):
    """Snap animation to simulation

    Move animation to where the simulation is right now.

    Snapping is an 'iterative' algorithm, meaning it will try and match the
    simulated pose over and over until 'close enough'. How close it gets
    depends on the translation and rotation 'tolerance'. Trade accuracy for
    performance by lowering the number of iterations and tolerance.

    Generally, this command should take between 10-100 ms, but may climb to
    500-1000 in complex rigs with many controls.

    """

    bl_idname = "ragdoll.snap_to_simulation"
    bl_label = "Snap To Simulation"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Transfer simulated pose into keyframes"

    icon = "PROP_ON"

    keyframe: bpy.props.BoolProperty(
        name="Keyframe",
        description=(
            "Snap and also keyframe the destinations"
        ),
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        if not bpx.ls(type="rdSolver"):
            cls.poll_message_set("No Ragdoll solvers in the current scene")
            return False

        return True

    def execute(self, context):
        solvers = bpx.selection(type="rdSolver") or bpx.ls(type="rdSolver")
        opts = {"keyframe": self.keyframe}

        with bpx.timing("snap_to_simulation") as t:
            for solver in solvers:
                commands.snap_to_simulation(solver, opts)

        self.report({"INFO"}, "Finished in %.2f ms" % t.duration)
        return {"FINISHED"}


def install():
    bpy.utils.register_class(SnapToSimulation)


def uninstall():
    bpy.utils.unregister_class(SnapToSimulation)
