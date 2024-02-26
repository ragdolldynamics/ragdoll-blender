"""Help the user download and install the missing Ragdoll SDK"""

import bpy
from .vendor import bpx


MENU_ITEMS = []
DYNAMIC_CLASSES = {}


class PlaceholderOperator(bpy.types.Operator):
    def execute(self, context):
        self.command()
        return {"FINISHED"}

    def command(self, *args):
        pass


class PlaceholderMenu(bpy.types.Menu):
    bl_label = "Ragdoll"
    bl_idname = "ANIMATION_MT_ragdoll_menu"

    def draw(self, _context):
        layout = self.layout
        col = layout.column()

        for item in MENU_ITEMS:
            col.operator(item, icon="EXPORT")


def _draw_menu(self, _context):
    self.layout.menu(PlaceholderMenu.bl_idname)


@bpx.call_once
def install(id, label, command=lambda self: None):
    Class = type(label, (PlaceholderOperator,), {
        "bl_idname": "ragdoll.%s" % id,
        "bl_label": label,
        "bl_options": {"REGISTER"},
        "bl_description": "Patience is key",
        "command": command
    })

    DYNAMIC_CLASSES[id] = Class
    MENU_ITEMS.append(Class.bl_idname)

    bpy.utils.register_class(Class)
    bpy.utils.register_class(PlaceholderMenu)

    bpy.types.VIEW3D_MT_editor_menus.append(_draw_menu)

    bpx.unset_called(uninstall)


@bpx.call_once
def uninstall(id):
    bpy.utils.unregister_class(DYNAMIC_CLASSES[id])
    bpy.utils.unregister_class(PlaceholderMenu)

    bpy.types.VIEW3D_MT_editor_menus.remove(_draw_menu)

    MENU_ITEMS[:] = []
    DYNAMIC_CLASSES.clear()

    bpx.unset_called(install)
