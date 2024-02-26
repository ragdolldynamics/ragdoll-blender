import bpy
from . import draw
from ..vendor import bpx


@draw.with_properties("rdDistanceConstraint.json")
class RD_PT_DistanceConstraint(draw.PropertiesPanel):
    bl_label = ""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "physics"

    @classmethod
    def poll(cls, context):
        xobj = bpx.BpxType(context.object)
        return xobj.type() == "rdDistanceConstraint"

    def draw_header(self, _):
        draw.ragdoll_header(
            self.layout, text="Distance Constraint", icon="PIVOT_MEDIAN"
        )

    def draw(self, context):
        # TODO: Draw assigned marker.
        pass


def install():
    bpy.utils.register_class(RD_PT_DistanceConstraint)


def uninstall():
    bpy.utils.unregister_class(RD_PT_DistanceConstraint)
