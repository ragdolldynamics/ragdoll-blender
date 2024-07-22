import bpy
from . import tag_redraw
from ..vendor import bpx
from .. import util, scene

_physics_types = (
    "rdSolver",
    "rdMarker",
    "rdGroup",
    "rdPinConstraint",
    "rdFixedConstraint",
    "rdDistanceConstraint",
)


def delete_physics(xobjs):
    # Cannot delete objects from a collection excluded from the view layer
    # Gah, Blender..
    for xobj in xobjs:
        bpy.context.scene.collection.objects.link(xobj.handle())

    bpx.delete(*xobjs)
    util.touch_initial_state()


def delete_physics_all():
    delete_physics(bpx.ls(type=_physics_types))

    # Also delete master `Ragdoll` collection
    Ragdoll = bpx.find("Ragdoll")
    if Ragdoll is not None:
        bpx.delete(Ragdoll)


class DeletePhysicsByEntity(bpy.types.Operator):
    bl_idname = "ragdoll.delete_physics_by_entity"
    bl_label = "Delete Physics By Id"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Delete one Ragdoll entity"

    entity: bpy.props.IntProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        xobj = bpx.alias(self.entity, None)
        if xobj is None:
            return {"CANCELLED"}

        with bpx.object_mode():
            delete_physics([xobj])

        tag_redraw(context.screen)
        return {"FINISHED"}


class DeletePhysicsBySelection(bpy.types.Operator):
    bl_idname = "ragdoll.delete_physics_by_selection"
    bl_label = "Delete Physics from Selection"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Delete selected Ragdoll physics in scene"
    icon = "GHOST_DISABLED"

    def execute(self, context):
        to_delete = set()

        for xobj in bpx.selection():
            if xobj.type() in _physics_types:
                to_delete.add(xobj)
            else:
                marker = scene.object_to_marker(xobj)
                if marker:
                    to_delete.add(marker)

        with bpx.object_mode():
            delete_physics(to_delete)

        tag_redraw(context.screen)
        return {"FINISHED"}


class DeletePhysicsAll(bpy.types.Operator):
    bl_idname = "ragdoll.delete_physics_all"
    bl_label = "Delete All Physics"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Delete all Ragdoll physics in scene"
    icon = "GHOST_DISABLED"

    def execute(self, context):
        with bpx.object_mode():
            delete_physics_all()

        tag_redraw(context.screen)
        return {"FINISHED"}


def install():
    bpy.utils.register_class(DeletePhysicsByEntity)
    bpy.utils.register_class(DeletePhysicsBySelection)
    bpy.utils.register_class(DeletePhysicsAll)


def uninstall():
    bpy.utils.unregister_class(DeletePhysicsByEntity)
    bpy.utils.unregister_class(DeletePhysicsBySelection)
    bpy.utils.unregister_class(DeletePhysicsAll)
