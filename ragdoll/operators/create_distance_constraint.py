import bpy

from . import OperatorWithOptions, get_selected
from .. import scene, util
from ..vendor import bpx


class CreateDistanceConstraint(OperatorWithOptions):
    """Create a new distance constraint

    Softly constrain the position and orientation of a marker relative
    another marker.

    """

    bl_idname = "ragdoll.create_distance_constraint"
    bl_label = "Create Distance Constraint"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Create a new distance constraint"

    icon = "PIVOT_MEDIAN"

    @classmethod
    def poll(cls, context):
        solver = bpx.ls(type="rdSolver")

        if not solver:
            cls.poll_message_set("No solver in the scene")
            return False

        return True

    def execute(self, context):
        solver = scene.find_or_create_current_solver()

        markers = get_selected("rdMarker")

        if len(markers) != 2:
            self.report({"ERROR"}, "Select 2 markers to constrain")
            return {"CANCELLED"}

        xparent, xchild = markers

        xchild_source = xchild["sourceTransform"].read()
        xparent_source = xparent["sourceTransform"].read()

        if not (xchild_source and xparent_source):
            self.report({"ERROR"}, "Disconnected markers, this is a bug")
            return {"CANCELLED"}

        name = "rDistance_%s_to_%s" % (xparent_source.name(),
                                       xchild_source.name())
        xcon = scene.create("rdDistanceConstraint", name=name)
        xcon["parentMarker"] = xparent.handle()
        xcon["childMarker"] = xchild.handle()

        # Append to solver
        solver["members"].append({"object": xcon.handle()})
        bpx.link(xcon, util.find_assembly())

        with bpx.object_mode():
            bpx.select(xcon)

        util.touch_initial_state(context)

        return {"FINISHED"}


def install():
    bpy.utils.register_class(CreateDistanceConstraint)


def uninstall():
    bpy.utils.unregister_class(CreateDistanceConstraint)
