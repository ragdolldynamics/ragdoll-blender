import bpy

from . import OperatorWithOptions, get_selected
from .. import scene, util
from ..vendor import bpx


class CreatePinConstraint(OperatorWithOptions):
    """Create a new pin constraint

    Softly constrain the position and orientation of a marker in worldspace.

    """
    bl_idname = "ragdoll.create_pin_constraint"
    bl_label = "Create Pin Constraint"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Create a new pin constraint"

    icon = "GP_ONLY_SELECTED"

    def execute(self, context):
        solver = scene.find_or_create_current_solver()

        if not solver:
            self.report({"ERROR"}, "No solver found")
            return {"CANCELLED"}

        markers = get_selected("rdMarker")

        if not any(markers):
            self.report({"ERROR"}, "No markers selected")
            return {"CANCELLED"}

        new_constraints = []
        for xobj in markers:
            xcon = scene.create("rdPinConstraint", name="rPinConstraint")
            xcon["childMarker"] = xobj.handle()

            # More suitable default values
            xcon["linearStiffness"] = 0.01
            xcon["angularStiffness"] = 0.01

            # TODO: Make dependent on option
            transform = xobj["sourceTransform"].read()
            xcon.handle().matrix_world = transform.matrix()

            # Append to solver
            solver["members"].append({"object": xcon.handle()})
            new_constraints.append(xcon)
            bpx.link(xcon, util.find_assembly())

        # User convenience, for easy manipulation upon creation
        bpx.set_mode(bpx.ObjectMode)
        bpx.select(new_constraints)

        util.touch_initial_state(context)

        return {"FINISHED"}


def install():
    bpy.utils.register_class(CreatePinConstraint)


def uninstall():
    bpy.utils.unregister_class(CreatePinConstraint)
