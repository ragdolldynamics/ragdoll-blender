import os
import sys
import bpy

import ragdollc

from . import icons
from ..vendor import bpx
from ..operators import (
    create_pin_constraint,
    create_distance_constraint,
    create_attach_constraint,
    record_simulation,
    snap_to_simulation,
    assign_markers,
    assign_environment,
    delete_physics,
    edit_solver,
    edit_marker,
    retarget_ui,
    io,
    logging_level,
    licence,
)


def _soon(layout, text, icon):
    layout.operator(_ComingSoon.bl_idname, text=text, icon=icon)


def _with_ctrl(layout, cls, **kwargs):
    split = layout.split(align=True, factor=0.99)

    cls.bl_description += "\n\nTip: Ctrl + Click = Options Dialog"
    op = split.operator(cls.bl_idname, **kwargs)

    if sys.platform == "darwin":
        icon = icons.fname_to_icon_id["ctrl-mac.png"]
    else:
        icon = icons.fname_to_icon_id["ctrl.png"]

    split.separator(factor=0)  # Magic element for maintaining this layout.
    split.label(text="", icon_value=icon)

    return op


def menu_item(layout, item, **kwargs):
    """General menu item layout helper

    Arguments:
        layout:
        item:
        **kwargs:

    """

    icon = kwargs.pop("icon", getattr(item, "icon", None))

    if icon is not None:
        if "." in icon:
            icon = icons.fname_to_icon_id[icon]
            kwargs["icon_value"] = icon
        else:
            kwargs["icon"] = icon

    if isinstance(item, str):
        if item.strip():
            layout.label(text=item, **kwargs)
        else:
            # Empty string => separator
            layout.separator(factor=0.5)

    elif issubclass(item, bpy.types.Menu):
        layout.menu(item.bl_idname, **kwargs)

    elif issubclass(item, bpy.types.Operator):

        if hasattr(item, "__ctrl_invoke__"):
            _with_ctrl(layout, item, **kwargs)
        else:
            layout.operator(item.bl_idname, **kwargs)


class RagdollMainMenu(bpy.types.Menu):
    bl_label = "Ragdoll"
    bl_idname = "ANIMATION_MT_ragdoll_menu"

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "POSE"}

    def draw(self, context):
        layout = self.layout
        col = layout.column()

        menu_item(col, "Markers")
        text = "Assign and Connect" if context.mode == "POSE" else "Assign"
        menu_item(col, assign_markers.AssignMarkers, text=text)
        menu_item(col, assign_environment.AssignEnvironment)

        menu_item(col, "  ")
        menu_item(col, "Transfer")
        menu_item(col, record_simulation.RecordSimulation)
        menu_item(col, snap_to_simulation.SnapToSimulation)

        menu_item(col, "  ")
        menu_item(col, "IO")
        menu_item(col, io.ExportPhysics)
        _soon(col, "Import Physics", icon=io.ImportPhysics.icon)
        menu_item(col, io.LoadPhysics)
        _soon(col, "Update Physics", icon="CON_ARMATURE")

        menu_item(col, "  ")
        menu_item(col, "Manipulate")
        menu_item(col, RagdollConstrainMenu)
        menu_item(col, RagdollEditMenu)
        menu_item(col, RagdollFieldsMenu)

        menu_item(col, "  ")
        menu_item(col, "Utilities")
        menu_item(col, RagdollUtilitiesMenu)
        menu_item(col, RagdollSystemMenu)
        menu_item(col, "  ")
        menu_item(col, RagdollAssetsMenu)
        menu_item(col, "  ")
        text = "Ragdoll %s" % ragdollc.__version__
        menu_item(col, licence.Licence, text=text, icon="logo.png")


class RagdollUtilitiesMenu(bpy.types.Menu):
    bl_label = "Utilities"
    bl_idname = "ANIMATION_MT_ragdoll_menu_utilities"
    icon = "SNAP_ON"

    def draw(self, _context):
        layout = self.layout
        col = layout.column()

        menu_item(col, edit_marker.ReplaceMesh)

        menu_item(col, "  ")
        menu_item(col, record_simulation.ExtractSimulation)

        menu_item(col, "  ")
        _soon(col, "Auto Limit", icon="ORIENTATION_LOCAL")
        _soon(col, "Reset Shape", icon="MESH_CAPSULE")
        _soon(col, "Reset Origin", icon="PIVOT_BOUNDBOX")
        _soon(col, "Reset Constraint Frames", icon="RIGID_BODY_CONSTRAINT")
        _soon(col, "Edit Constraint Frames", icon="MOD_MESHDEFORM")


class RagdollSystemMenu(bpy.types.Menu):
    bl_label = "System"
    bl_idname = "ANIMATION_MT_ragdoll_menu_system"
    icon = "DESKTOP"

    def draw(self, _context):
        layout = self.layout
        col = layout.column()

        menu_item(col, delete_physics.DeletePhysicsAll)
        menu_item(col, delete_physics.DeletePhysicsBySelection)

        menu_item(col, "  ")
        level = {
            10: dict(text="Logging: Debug", icon="INFO"),
            20: dict(text="Logging: Info", icon="INFO"),
            30: dict(text="Logging: Warning", icon="ERROR"),
            40: dict(text="Logging: Error", icon="ERROR"),
            50: dict(text="Logging: Off", icon="CANCEL"),
        }.get(
            bpx._LOG.level,
            dict(text="Logging: Undefined", icon="QUESTION")
        )
        menu_item(col, RagdollLoggingMenu, **level)


class RagdollConstrainMenu(bpy.types.Menu):
    bl_label = "Constrain"
    bl_idname = "ANIMATION_MT_ragdoll_menu_constrain"
    icon = "LINKED"

    def draw(self, _context):
        layout = self.layout
        col = layout.column()

        menu_item(col,
                  create_distance_constraint.CreateDistanceConstraint,
                  text="Distance")
        menu_item(col,
                  create_pin_constraint.CreatePinConstraint,
                  text="Pin")
        menu_item(col,
                  create_attach_constraint.CreateAttachConstraint,
                  text="Attach")
        _soon(col, "Weld", icon="ORIENTATION_LOCAL")


class RagdollEditMenu(bpy.types.Menu):
    bl_label = "Edit"
    bl_idname = "ANIMATION_MT_ragdoll_menu_edit"
    icon = "ORIENTATION_GLOBAL"

    def draw(self, _context):
        layout = self.layout
        col = layout.column()

        menu_item(col, "Hierarchy")
        menu_item(col, edit_marker.Reassign)
        menu_item(col, retarget_ui.RetargetMenuOp)
        menu_item(col, edit_marker.Reparent)
        menu_item(col, "  ")
        menu_item(col, edit_marker.Unparent)
        menu_item(col, edit_marker.Untarget)

        menu_item(col, "  ")
        menu_item(col, "Membership")
        menu_item(col, edit_marker.Group)
        menu_item(col, edit_marker.Ungroup)
        menu_item(col, edit_marker.MoveToGroup)

        menu_item(col, "  ")
        menu_item(col, "Collisions")
        _soon(col, "Assign Collision Group", icon="MOD_PHYSICS")
        _soon(col, "Add to Collision Group", icon="MOD_BOOLEAN")
        _soon(col, "Remove from Collision Group", icon="MOD_EDGESPLIT")

        menu_item(col, "  ")
        menu_item(col, "Solver")
        _soon(col, "Merge Solvers", icon="PIVOT_INDIVIDUAL")
        _soon(col, "Extract Markers", icon="PIVOT_ACTIVE")
        _soon(col, "Move to Solver", icon="PIVOT_MEDIAN")

        menu_item(col, "  ")
        menu_item(col, "Cache")
        menu_item(col, edit_solver.CacheAll)
        menu_item(col, edit_solver.Uncache)


class RagdollFieldsMenu(bpy.types.Menu):
    bl_label = "Fields"
    bl_idname = "ANIMATION_MT_ragdoll_menu_fields"
    icon = "FORCE_WIND"

    def draw(self, _context):
        layout = self.layout
        col = layout.column()

        _soon(col, "Air", icon="FORCE_WIND")
        _soon(col, "Drag", icon="FORCE_DRAG")
        _soon(col, "Gravity", icon="LIGHTPROBE_CUBEMAP")
        _soon(col, "Newton", icon="SORTBYEXT")
        _soon(col, "Radial", icon="PROP_CON")
        _soon(col, "Turbulence", icon="FORCE_TURBULENCE")
        _soon(col, "Uniform", icon="FORCE_FORCE")
        _soon(col, "Vortex", icon="FORCE_VORTEX")
        _soon(col, "Volume Axis", icon="MESH_CUBE")
        _soon(col, "Volume Curve", icon="FORCE_CURVE")


class RagdollLoggingMenu(bpy.types.Menu):
    bl_label = "Logging Level"
    bl_idname = "ANIMATION_MT_ragdoll_menu_logging"

    def draw(self, _context):
        layout = self.layout
        col = layout.column()

        menu_item(col, logging_level.LogOff)
        menu_item(col, logging_level.LogDefault)
        menu_item(col, logging_level.LogLess)
        menu_item(col, logging_level.LogMore)


class RagdollAssetsMenu(bpy.types.Menu):
    bl_label = "Assets"
    bl_idname = "ANIMATION_MT_ragdoll_menu_assets"
    icon = "MESH_MONKEY"

    _icons = {
        "alien": "PACKAGE",
        "batty": "EXPERIMENTAL",
        "cowboy": "FCURVE",
        "dog": "RENDER_RESULT",
        "dude": "EMPTY_DATA",
        "lion": "RENDER_ANIMATION",
        "manikin": "ARMATURE_DATA",
        "pirate": "RNA",
        "rhino": "OUTLINER_OB_LATTICE",
        "shark": "META_CAPSULE",
        "skeleton": "FORCE_LENNARDJONES",
        "spaceman": "FORCE_BOID",
        "wasp": "CON_SIZELIMIT",
        "wyvern": "DRIVER",
    }

    def draw(self, _context):
        layout = self.layout
        col = layout.column()
        col.operator_context = "EXEC_DEFAULT"

        assets = _LoadAsset.assets.copy()

        # Easier to find our famous manikin :)
        manikin = "manikin"
        op = col.operator(_LoadAsset.bl_idname,
                          text=manikin.capitalize(),
                          icon=self._icons[manikin])
        op.filepath = assets.pop(manikin)

        col.separator(factor=0.5)

        for name, path in assets.items():
            icon = self._icons.get(name, "BLANK1")
            op = col.operator(_LoadAsset.bl_idname,
                              text=name.capitalize(),
                              icon=icon)
            op.filepath = path


class _ComingSoon(bpy.types.Operator):
    bl_idname = "ragdoll._coming_soon"
    bl_label = ""
    bl_options = {"INTERNAL"}
    bl_description = "Coming soon..."

    @classmethod
    def poll(cls, context):
        return False

    def execute(self, context):
        return {"FINISHED"}


class _LoadAsset(bpy.types.Operator):
    bl_idname = "ragdoll._load_asset"
    bl_label = "Load Physics Asset"
    bl_options = {"INTERNAL"}
    bl_description = "Load ragdoll physics"

    assets = dict()
    filepath: bpy.props.StringProperty()

    def execute(self, context):
        bpy.ops.ragdoll.load_physics(filepath=self.filepath)
        return {"FINISHED"}

    @classmethod
    def load_assets(cls):
        cls.assets.clear()

        dirname = os.path.dirname(os.path.dirname(__file__))  # ragdoll
        dirname = os.path.join(dirname, "resources", "assets")

        if not os.path.isdir(dirname):
            return

        for item in os.listdir(dirname):
            path = os.path.join(dirname, item)

            if item.endswith(".rag") and os.path.isfile(path):
                name, _ = os.path.splitext(item)
                cls.assets[name] = path


_classes = (
    RagdollMainMenu,
    RagdollUtilitiesMenu,
    RagdollSystemMenu,
    RagdollConstrainMenu,
    RagdollEditMenu,
    RagdollFieldsMenu,
    RagdollLoggingMenu,
    RagdollAssetsMenu,

    _ComingSoon,
    _LoadAsset
)


def _draw_menu(self, _context):
    layout = self.layout

    if layout.scale_x < 1.1:
        layout.scale_x = 1.1  # Wider space for icon

    layout.menu(
        RagdollMainMenu.bl_idname,
        icon_value=icons.fname_to_icon_id["logo2.png"],
    )


def install():
    _LoadAsset.load_assets()

    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.VIEW3D_MT_editor_menus.append(_draw_menu)


def uninstall():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)

    bpy.types.VIEW3D_MT_editor_menus.remove(_draw_menu)
