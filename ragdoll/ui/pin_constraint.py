import bpy
from . import draw
from ..vendor import bpx


@draw.with_properties("rdPinConstraint.json")
class RD_PT_PinConstraint(draw.PropertiesPanel):
    bl_label = ""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "physics"

    @classmethod
    def poll(cls, context):
        xobj = bpx.BpxType(context.object)
        return xobj.type() == "rdPinConstraint"

    def draw_header(self, context):
        xobj = bpx.BpxType(context.object)
        if xobj["parentMarker"].read():
            text = "Attach Constraint"
            icon = "PIVOT_MEDIAN"
        else:
            text = "Pin Constraint"
            icon = "GP_ONLY_SELECTED"
        draw.ragdoll_header(self.layout, text=text, icon=icon)

    def draw(self, context):
        # TODO: Draw assigned marker.
        pass


def install():
    bpy.utils.register_class(RD_PT_PinConstraint)


def uninstall():
    bpy.utils.unregister_class(RD_PT_PinConstraint)
