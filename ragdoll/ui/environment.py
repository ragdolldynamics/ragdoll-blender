import bpy
from . import draw
from ..vendor import bpx


@draw.with_properties("rdEnvironment.json")
class RD_PT_Environment(draw.PropertiesPanel):
    bl_label = ""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "physics"

    @classmethod
    def poll(cls, context):
        xobj = bpx.BpxType(context.object)
        return xobj.type() == "rdEnvironment"

    def draw_header(self, _):
        draw.ragdoll_header(self.layout, text="Environment", icon="MESH_GRID")

    def draw(self, _):
        pass


def install():
    bpy.utils.register_class(RD_PT_Environment)


def uninstall():
    bpy.utils.unregister_class(RD_PT_Environment)
