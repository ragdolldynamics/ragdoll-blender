import bpy
import bpy_types

import logging

from ..vendor import bpx
from .. import log, preferences
from ..ui import draw, icons

console_log = logging.getLogger("ragdoll")


def find_transform(xobjects):
    """Return the first transform from `xobjects`

    One that is not another Marker or Ragdoll object.

    """

    for xobj in xobjects:
        if not isinstance(xobj, bpx.BpxType):
            continue

        if find_marker((xobj,)):
            continue

        return xobj


def find_marker(xobjects):
    """Return the first marker from `xobjects`

    Including if it is a destination or source transform

    """

    for xobj in xobjects:
        if not isinstance(xobj, bpx.BpxType):
            continue

        if xobj.type() != "rdMarker":
            entity = xobj.data.get("entity")
            xobj = bpx.alias(entity, None)

        if not xobj or xobj.type() != "rdMarker":
            continue

        return xobj


def get_selected(archetype):
    """Return selected objects of a particular type

    Taking into account indirect relationships via the common entity

    """

    result = []

    for sel in bpx.selection():
        entity = sel.data.get("entity", None)
        if not entity:
            continue

        xobj = bpx.alias(entity, None)
        if not xobj:
            continue

        if xobj.type() == archetype:
            result.append(xobj)

    return result


def tag_redraw(screen):
    """Tag `VIEW_3D`, `PROPERTIES` area to redraw

    Arguments:
        screen (bpy.types.Screen): `screen` object from `bpy.context.`

    """

    for area in screen.areas:
        if area.type == "VIEW_3D" or area.ui_type == "PROPERTIES":
            area.tag_redraw()


def find_hotkey(operator_id):
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.user

    for km in kc.keymaps:
        for kmi in km.keymap_items:
            if kmi.idname != operator_id:
                continue
            # Only interested in keyboard
            if kmi.map_type != "KEYBOARD" or kmi.value != "PRESS":
                continue
            # Exclude keyboard modifiers
            if any([kmi.alt, kmi.ctrl, kmi.shift, kmi.oskey]):
                continue

            return kmi.type


def PlaceholderOption(name: str) -> str:
    """Annotation placeholder for preference property (option) of an operator

    In Ragdoll, some operator properties are synced with addon preferences.
    Meaning that the value you used for an operation will be saved as user
    preference and reused across sessions. Such properties are called "options"
    in Ragdoll operator.

    Usage:
        ```
        class MyOperator(OperatorWithOptions):
            my_option: PlaceholderOption("ragdollOptionKey")

        ```
        * Operator MUST be a subclass of `OperatorWithOptions`.
        * Option key `ragdollOptionKey` MUST exist in `resources/options.json`.

    """

    # NOTE: The option key string is returned directly, so why not just write
    #   this instead? E.g.
    #   ```
    #   solver: "markersAssignSolver"
    #   ```
    #   For 1), using a function is much readable.
    #   And 2), makes linter happy.
    return name


def _replace_options(cls, name, dct):
    """Replace `PlaceholderOption` with real blender Property

    Properties that annotated with `PlaceholderOption` will be replaced with
    Blender property instance (`bpy.props`) according to Ragdoll's preferences
    schema file (`resources/options.json`).

    """

    options = set()

    for key, value in dct.get("__annotations__", {}).items():
        if isinstance(value, str):
            options.add((key, value))

    if options:
        if not cls._DATA:
            cls._DATA = preferences._load_data()

        data = cls._DATA
        option_map = dict()
        option_properties = dict()

        for key, value in options:

            for ragdollKey, define in data["option"].items():
                if ragdollKey == value:
                    prop = preferences._make_property(ragdollKey, define)
                    option_map[key] = ragdollKey  # For sync
                    break
            else:
                log.error(
                    "Cannot install operator %r: option %r not found."
                    % (name, key)
                )
                continue

            option_properties[key] = prop

        dct["__annotations__"].update(option_properties)
        dct["_option_map"] = option_map

    return bool(options)


def _read_options(operator):
    """Read options value from preferences"""

    try:

        option_map = operator.__class__._option_map or {}
        for option, ragdollKey in option_map.items():
            value = preferences.read(ragdollKey)
            setattr(operator, option, value)

    except Exception as e:
        # This is a bug
        import traceback
        console_log.error("Error reading options from preferences:")
        traceback.print_exc()
        console_log.error("%s: %s" % (operator.__class__, str(e)))


def _save_options(operator):
    """Save options back to preferences"""

    try:
        option_map = operator.__class__._option_map or {}
        for option, ragdollKey in option_map.items():
            value = getattr(operator, option)
            preferences.write(ragdollKey, value)

    except Exception as e:
        # This is a bug
        import traceback
        console_log.error("Error saving options to preferences:")
        traceback.print_exc()
        console_log.error("%s: %s" % (operator.__class__, str(e)))


class _OperatorMeta(bpy_types.RNAMeta):

    _DATA = None

    def __new__(cls, name, bases, dct):

        # Install option property
        has_options = _replace_options(cls, name, dct)
        instance = bpy_types.RNAMeta.__new__(cls, name, bases, dct)

        # Take first line of class docstring as tooltip
        if instance.__doc__:
            instance.bl_description = instance.__doc__.split("\n")[0]

        if not has_options:
            return instance

        # Wrap invoke() to sync options from preferences
        if hasattr(instance, "invoke"):
            subclass_invoke = getattr(instance, "invoke")

            def new_invoke(self, context, event):
                _read_options(self)
                return subclass_invoke(self, context, event)

            setattr(instance, "invoke", new_invoke)

        # Add invoke() for properties dialog
        # - when Ctrl pressed or `always_invoke` checked.
        else:
            def invoke(self, context, event):
                _read_options(self)

                if event.ctrl or getattr(self, "always_invoke", False):
                    return context.window_manager.invoke_props_dialog(self)
                else:
                    return self.execute(context)

            setattr(instance, "invoke", invoke)
            # Breadcrumb for menu item drawing
            setattr(instance, "__ctrl_invoke__", True)

        # Add draw() for options dialog
        if not hasattr(instance, "draw"):

            def draw_dialog(self, context):
                layout = self.layout
                layout.use_property_split = True

                # 300 is the default value of `invoke_props_dialog()`
                width = getattr(self, "dialog_width", 300)

                # Render description
                if instance.__doc__:
                    paragraphs = instance.__doc__.split("\n\n")
                    paragraphs = paragraphs[1:]  # First line is tooltip

                    description_block = layout.row()
                    description_block.separator()

                    icon_area = description_block.column()
                    if hasattr(instance, "icon"):
                        if "." in instance.icon:
                            icon_id = icons.fname_to_icon_id[instance.icon]
                            icon_area.label(icon_value=icon_id)
                        else:
                            icon_area.label(icon=instance.icon)

                    text_area = description_block.column()
                    for text in paragraphs:
                        draw.multi_lines(text_area.column(),
                                         text.replace("\n", " ").strip(),
                                         width,
                                         padding=20)

                    layout.separator()

                # Render options
                for key, value in self.__annotations__.items():
                    if hasattr(value, "keywords"):
                        if "HIDDEN" in value.keywords.get("options", []):
                            continue

                    if key == "filepath":  # file-select dialog thing
                        continue

                    if key != "always_invoke":
                        layout.prop(self, key)

                layout.separator()

                # Render "Always show dialog" checkbox
                if hasattr(self, "always_invoke"):
                    layout.prop(self, "always_invoke")

            setattr(instance, "draw", draw_dialog)

        # Wrap execute() to sync options back to preferences
        if hasattr(instance, "execute"):
            subclass_execute = getattr(instance, "execute")

            def new_execute(self, context):
                _save_options(self)
                return subclass_execute(self, context)

            setattr(instance, "execute", new_execute)

        return instance


class OperatorWithOptions(bpy.types.Operator, metaclass=_OperatorMeta):
    """Ragdoll operator base class"""

    _option_map = None

    def enum_to_index(self, enum) -> int:
        """Return index of enum property, -1 if not found"""

        prop = type(self).__annotations__[enum]
        assert "items" in prop.keywords, "%s was not an enum" % enum

        items = {
            i[0]: i[-1]  # Key: Index
            for i in prop.keywords["items"](prop, bpy.context)
        }

        key = getattr(self, enum, None)

        return items.get(key, -1)
