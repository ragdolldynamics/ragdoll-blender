import bpy

from . import draw
from .. import scene
from ..vendor import bpx
from ..operators import (
    delete_physics,
    assign_markers,
)


@draw.with_properties("rdMarker.json")
class RD_PT_Marker(draw.PropertiesPanel):
    bl_label = ""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "physics"

    @classmethod
    def poll(cls, context):
        xobj = bpx.BpxType(context.object)
        return xobj.type() == "rdMarker"

    def draw_header(self, context):
        row = draw.ragdoll_header(self.layout, text="Marker", icon="REC")
        xobj = bpx.BpxType(context.object)
        xsource = xobj["sourceTransform"].read()

        if not xsource:
            return

        if isinstance(xsource, bpx.BpxBone):
            row.label(text=xsource.name(), icon="BONE_DATA")
        else:
            row.label(text=xsource.name(), icon="OBJECT_DATAMODE")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True

        xobj = bpx.BpxType(context.object)
        xsource = xobj["sourceTransform"].read()

        # Disconnected or source was removed
        if not xsource:
            return

        row = layout.row()
        row.prop(xsource.handle(), "name",
                 text="Source Transform",
                 icon="OBJECT_DATA")

        if isinstance(xsource, bpx.BpxBone):
            row.prop(xsource.bone(), "name", text="", icon="BONE_DATA")

        row.separator(factor=0.4)
        op = row.operator(
            PanelSetActive.bl_idname,
            text="",
            icon="FORWARD",
            emboss=False,
        )

        op.object_name = xsource.name()

        if isinstance(xsource, bpx.BpxBone):
            op.object_name = xsource.handle().name_full
            op.bone_name = xsource.name()
            op.panel = "BONE"
        else:
            op.panel = "OBJECT"


class _ActorPanel(bpy.types.Panel):
    def draw_link_to_marker(self, marker):
        if not marker.is_alive():
            return

        layout = self.layout
        row = layout.row(align=True)

        op = row.operator(
            delete_physics.DeletePhysicsByEntity.bl_idname,
            text="",
            icon="X"
        )
        op.entity = marker.data.get("entity")

        row.prop(marker.handle(), "name", text="", icon="REC")
        # row.separator(factor=0.4)

        op = row.operator(
            PanelSetActive.bl_idname,
            text="",
            icon="FORWARD",
            # emboss=False,
        )
        op.object_name = marker.name()
        op.panel = "PHYSICS"


class RD_PT_Marker_On_Object(_ActorPanel):
    bl_label = ""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "physics"

    @classmethod
    def poll(cls, context):
        if context.mode == "OBJECT" and context.object:
            xobj = bpx.BpxType(context.object)
            return (
                not xobj.type() == "rdMarker" and
                scene.object_to_marker(xobj) is not None
            )
        return False

    def draw_header(self, context):
        row = draw.ragdoll_header(self.layout, text="Marker", icon="REC")
        row.label(text=context.object.name, icon="OBJECT_DATAMODE")

    def draw(self, context):
        marker = scene.object_to_marker(bpx.BpxType(context.object))
        self.draw_link_to_marker(marker)


class RD_PT_Marker_On_Bone(_ActorPanel):
    bl_label = ""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "physics"

    @classmethod
    def poll(cls, context):
        if context.mode == "POSE" and context.active_pose_bone:
            xbone = bpx.BpxType(context.active_pose_bone)
            return scene.object_to_marker(xbone) is not None
        return False

    def draw_header(self, context):
        row = draw.ragdoll_header(self.layout, text="Marker", icon="REC")
        row.label(text=context.active_pose_bone.name, icon="BONE_DATA")

    def draw(self, context):
        marker = scene.object_to_marker(bpx.BpxType(context.active_pose_bone))
        self.draw_link_to_marker(marker)


class PanelSetActive(bpy.types.Operator):
    bl_idname = "ragdoll.panel_set_active"
    bl_label = "Go to.."
    bl_options = {"INTERNAL", "UNDO"}
    bl_description = "Set object/bone active and show properties"

    object_name: bpy.props.StringProperty()
    bone_name: bpy.props.StringProperty()
    panel: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        if context.space_data.use_pin_id:
            cls.poll_message_set("Cannot work with 'Pin ID' toggled.")
            return False
        return True

    def execute(self, context):
        panel = self.panel
        space = context.space_data
        object_ = context.scene.objects[self.object_name]
        bone_name = self.bone_name

        context.view_layer.objects.active = object_
        mode = "OBJECT"

        if object_.pose and bone_name in object_.pose.bones:
            mode = "POSE"
            bone = object_.pose.bones[bone_name]
            object_.data.bones.active = bone.bone

        bpy.ops.object.mode_set(mode=mode)

        def to_panel():
            # Note: 'BONE' tab is only available if the active object is an
            #   armature, and Blender need some time to get 'BONE' tab ready.
            try:
                space.context = panel
            except TypeError:
                return 0.01

        if space:
            bpy.app.timers.register(to_panel)

        return {"FINISHED"}


def install():
    bpy.utils.register_class(RD_PT_Marker)
    bpy.utils.register_class(RD_PT_Marker_On_Object)
    bpy.utils.register_class(RD_PT_Marker_On_Bone)

    # Operator
    bpy.utils.register_class(PanelSetActive)


def uninstall():
    bpy.utils.unregister_class(RD_PT_Marker)
    bpy.utils.unregister_class(RD_PT_Marker_On_Object)
    bpy.utils.unregister_class(RD_PT_Marker_On_Bone)

    # Operator
    bpy.utils.unregister_class(PanelSetActive)
