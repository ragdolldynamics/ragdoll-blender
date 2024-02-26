import bpy

from ragdollc import registry

from . import draw, marker as ui_marker
from .. import constants
from ..vendor import bpx


@draw.with_properties("rdGroup.json")
class RD_PT_Group(draw.PropertiesPanel):
    bl_label = ""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "physics"

    @classmethod
    def poll(cls, context):
        xobj = bpx.BpxType(context.object)
        return xobj.type() == "rdGroup"

    def draw_header(self, _):
        draw.ragdoll_header(self.layout, text="Group", icon="PACKAGE")

    def draw(self, _):
        pass


class RD_PT_GroupMembers(bpy.types.Panel):
    bl_label = ""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "physics"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        xobj = bpx.BpxType(context.object)
        return xobj.type() == "rdGroup"

    def draw_header(self, _context):
        draw.ragdoll_header(self.layout, text="Members", icon="MESH_CAPSULE")

    def draw(self, context):
        layout = self.layout

        xobj = bpx.BpxType(context.object)
        group_pg = xobj.property_group()

        column = layout.column()
        row = column.row()
        row.template_list(
            RD_UL_GroupMembers.__name__,
            "",
            group_pg,
            "members",
            group_pg,
            "members_ui_index",
            rows=4,
            maxrows=4,
            type="DEFAULT",
        )

        column.separator()


@draw.with_properties("rdGroup.json")
class RD_PT_Group_On_Marker(draw.PropertiesPanel):
    bl_label = ""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "physics"
    bl_options = {"DEFAULT_CLOSED"}

    @staticmethod
    def get_group(context):
        xobj = bpx.BpxType(context.object)
        marker_entity = xobj.data["entity"]
        group_com = registry.get("GroupComponent", marker_entity)
        return bpx.alias(group_com.entity, None)

    @classmethod
    def poll(cls, context):
        if ui_marker.RD_PT_Marker.poll(context):
            return cls.get_group(context) is not None

    @classmethod
    def get_xobject(cls, context) -> bpx.BpxType | None:
        return cls.get_group(context)

    def draw_header(self, context):
        row = draw.ragdoll_header(self.layout, text="Group", icon="PACKAGE")
        xobj = self.get_group(context)
        row.label(text=xobj.name(), icon="OUTLINER_OB_EMPTY")

    def draw(self, _):
        pass


class RD_UL_GroupMembers(bpy.types.UIList):
    marker_shape_icons = {
        constants.BoxShape: "MESH_CUBE",
        constants.SphereShape: "MESH_UVSPHERE",
        constants.CapsuleShape: "META_CAPSULE",
        constants.MeshShape: "MESH_ICOSPHERE",
    }

    def draw_item(self,
                  _context,
                  layout,
                  _data,
                  item,
                  _icon,
                  _active_data,
                  _active_property,
                  _index=0,
                  _flt_flag=0):
        # Always hide filter
        self.use_filter_show = False  # noqa

        entity_gp = item  # RdEntityPropertyGroup
        if not entity_gp.object:
            return

        marker_obj = bpx.BpxType(entity_gp.object)
        marker = marker_obj.property_group()

        marker_name = marker_obj.name()
        marker_shape = self.marker_shape_icons[marker["shapeType"]]
        marker_color = (*marker.color, 1.0)

        spacing = layout.row()
        spacing.separator()

        # color dot
        subrow = layout.row()
        subrow.template_node_socket(color=marker_color)
        subrow.scale_x = 0.2

        # marker shape, name
        layout.label(text=marker_name, icon=marker_shape)

    def filter_items(self, context, data, propname):
        group_pg = data
        members = getattr(group_pg, propname)

        flt_flags = [0] * len(members)
        flt_neworder = []

        # Note: Same as how `archetypes/solver.py evaluate_members()`
        #   filtering group members.
        for index, member in enumerate(members):

            # Could be disconnected
            if not member.object:
                continue

            xmember = bpx.BpxType(member.object)

            # Could have been removed
            if not xmember.is_alive():
                continue

            flt_flags[index] = self.bitflag_filter_item

        return flt_flags, flt_neworder


def install():
    bpy.utils.register_class(RD_PT_Group)
    bpy.utils.register_class(RD_PT_GroupMembers)
    bpy.utils.register_class(RD_PT_Group_On_Marker)
    bpy.utils.register_class(RD_UL_GroupMembers)


def uninstall():
    bpy.utils.unregister_class(RD_PT_Group)
    bpy.utils.unregister_class(RD_PT_GroupMembers)
    bpy.utils.unregister_class(RD_PT_Group_On_Marker)
    bpy.utils.unregister_class(RD_UL_GroupMembers)
