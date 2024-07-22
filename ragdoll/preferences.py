import os
import json
import functools

import bpy
import ragdollc

from . import log
from .vendor import bpx
from .ui import icons

_DATA = dict()


def read(key, default=None, as_index=False) -> str | int | bool | float:
    """Read Ragdoll preference property value

    Args:
        key: Property name in `ragdoll{Name}` form, e.g. `ragdollSceneScale`.
        default: Return this value if key not exists.
        as_index: Return Enum item index instead of identifier.

    """

    define = _DATA["option"].get(key)
    if not define:
        return default

    pref = bpy.context.preferences.addons[__package__].preferences
    name = define["name"]

    if define["type"] == "Enum":
        prop = pref.__annotations__.get(name)
        items = prop.keywords["items"]
        if callable(items):
            items = items(prop, bpy.context)
        identifiers = [item[0] for item in items]
        default_ = define["default"]
        # Instead of getting value via `getattr(pref, name, None)`, here we
        # use the `__getitem__` trick to get enum index so that we don't get
        # blender rna warning when the enum items has been changed dynamically
        # and the previously saved value doesn't match any of those anymore.
        index = pref.get(name, default_)
        if 0 <= index < len(identifiers):
            value = identifiers[index]
        else:
            value = define["items"][default_]

        if as_index:
            value = identifiers.index(value)

    else:
        value = getattr(pref, name, None)
        value = default if value is None else value

    return value


def requires_install(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not bpx.been_called(install):
            return
        return func(*args, **kwargs)
    return wrapper


@requires_install
def write(key, value=None) -> None:
    """Write Ragdoll preference property

    Args:
        key: Property name in `ragdoll{Name}` form, e.g. `ragdollSceneScale`.
        value: If None, reset back to default value.

    """

    define = _DATA["option"].get(key)
    if not define:
        raise KeyError("%r not exists in Ragdoll preferences." % key)

    name = define["name"]
    pref = bpy.context.preferences.addons[__package__].preferences
    value = define["default"] if value is None else value
    setattr(pref, name, value)


@requires_install
def reset():
    """Reset all Ragdoll preferences back to default"""

    context = bpy.context
    pref = context.preferences.addons[__package__].preferences

    for define in _DATA["option"].values():
        key = define["name"]

        if define["type"] == "Enum":
            pref[key] = define["default"]

        pref.property_unset(key)


def _make_update_callback(key, property_name):
    def preference_changed(preference, _context):
        typ = preference.bl_rna.properties[property_name]
        value = getattr(preference, property_name)

        if isinstance(typ, bpy.types.EnumProperty):
            enum_to_index = {
                enum.name: enum.value
                for enum in typ.enum_items
            }

            value = enum_to_index.get(value, 0)

        ragdollc.options.write(key, value)

    return preference_changed


class RagdollPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    def draw(self, _context):
        layout = self.layout

        # Main title
        row = layout.row(align=True)
        col = row.column()
        col.label(
            text="Ragdoll Options:",
            icon_value=icons.fname_to_icon_id["logo2.png"]
        )
        # Reset button
        col = row.column()
        col.alignment = "RIGHT"
        col.operator(
            ResetPreferences.bl_idname,
            icon="LIBRARY_DATA_BROKEN",
            text="Reset Options"
        )
        # Preference by sections
        body = layout.column()
        body.use_property_split = True

        panel = _DATA["panel"]
        sections = panel.get("__order__") or panel.keys()

        for title in sections:
            # Expander
            box = body.box()
            is_expanded = getattr(self, f"show_section_{title}")
            row = box.row(align=True)

            # Expand/Collapse by clicking on icon
            col = row.column()
            col.alignment = "LEFT"
            op = col.operator(
                SectionExpander.bl_idname,
                text=title,
                icon="DOWNARROW_HLT" if is_expanded else "RIGHTARROW",
                emboss=False,
            )
            op.section = title

            # Expand/Collapse by clicking on the area of icon's right
            col = row.column()
            op = col.operator(
                SectionExpander.bl_idname,
                text="",
                emboss=False,
            )
            op.section = title

            if not is_expanded:
                continue

            # Preferences
            flow = box.column_flow(columns=0, align=True)
            for name in panel[title]:
                if name == "__":
                    col = flow.column()
                    col.separator_spacer()
                    continue

                prop = self.__annotations__.get(name)
                if prop is None or not hasattr(prop, "keywords"):
                    continue

                if "HIDDEN" not in prop.keywords.get("options", {"HIDDEN"}):
                    col = flow.column()
                    col.prop(self, name)


class ResetPreferences(bpy.types.Operator):
    bl_idname = "ragdoll.reset_preferences"
    bl_label = ""
    bl_options = {"INTERNAL"}
    bl_description = "Reset all Ragdoll preferences back to default"

    def execute(self, _context):
        reset()
        return {"FINISHED"}


class SectionExpander(bpy.types.Operator):
    bl_idname = "ragdoll.section_expand"
    bl_label = ""
    bl_options = {"INTERNAL"}
    bl_description = "Expand/Collapse preference panel"

    section: bpy.props.StringProperty(
        name="Section",
        description="Section name of the add-on preference to expand",
    )

    def execute(self, context):
        pref = context.preferences.addons[__package__].preferences
        key = f"show_section_{self.section}"
        setattr(pref, key, not getattr(pref, key))
        return {"FINISHED"}


def _load_data():
    dirname = os.path.dirname(__file__)  # ragdoll
    dirname = os.path.join(dirname, "resources")

    filepath = os.path.join(dirname, "options.json")

    with open(filepath, "r") as f:
        data = json.load(f)

    # Exclude comments
    data["option"].pop("#", None)

    return data


def _build_preferences():
    data = _load_data()

    # Make preference properties
    RagdollPreferences.__annotations__ = dict()
    properties = RagdollPreferences.__annotations__

    for key, define in data["option"].items():
        prop = _make_property(key, define)
        if prop:
            properties[define["name"]] = prop

    # Preferences GUI panel expanders' state
    sections = data["panel"].get("__order__") or data["panel"].keys()
    for title in sections:
        key = f"show_section_{title}"
        properties[key] = bpy.props.BoolProperty(
            name=key,
            default=False,
            options={"HIDDEN", "SKIP_SAVE"},
        )

    return data


def _make_property(key, define):
    property_name = define["name"]
    typ = define["type"]

    try:
        cls = {
            "Enum": bpy.props.EnumProperty,
            "Path": bpy.props.StringProperty,
            "Float": bpy.props.FloatProperty,
            "String": bpy.props.StringProperty,
            "Integer": bpy.props.IntProperty,
            "Boolean": bpy.props.BoolProperty,
        }[typ]

    except KeyError:
        log.warning(
            "Option %s not registered: Unknown type: %s, this is a bug"
            % (property_name, typ)
        )
        return

    kwargs = dict(
        name=define["label"],
        description=define["help"].replace("<br>", "\n"),
        default=define["default"],
        options=set(),
    )
    for opt in ["min", "max", "subtype", "unit", "precision"]:
        if define.get(opt):
            kwargs[opt] = define[opt]

    if define.get("hide"):
        kwargs["options"].add("HIDDEN")

    if define.get("items"):
        if define.get("isDynamicEnum"):

            enum_function = globals()["_enum_%s" % define["name"]]

            kwargs["items"] = enum_function(define["items"])
        else:
            kwargs["items"] = [
                (item, item, "", i) for i, item in enumerate(define["items"])
            ]

    if define.get("monitor"):
        kwargs["update"] = _make_update_callback(key, property_name)

    return cls(**kwargs)


def _enum_markers_assign_solver(base_items):
    """Enum function for `markersAssignSolver` option"""

    def enum_function(self, context):
        items = []

        for solver in bpx.ls(type="rdSolver"):
            items.append(solver.name())

        items += base_items
        return [(item, item, "", i) for i, item in enumerate(items)]

    return enum_function


def _enum_markers_assign_group(base_items):
    """Enum function for `markersAssignGroup` option"""

    def enum_function(self, context):
        items = base_items[:]

        for group in bpx.ls(type="rdGroup"):
            items.append(group.name())

        return [(item, item, "", i) for i, item in enumerate(items)]

    return enum_function


@bpx.call_once
def install():
    dirname = os.path.dirname(__file__)  # ragdoll
    dirname = os.path.join(dirname, "resources")

    data = _build_preferences()

    bpy.utils.register_class(SectionExpander)
    bpy.utils.register_class(ResetPreferences)
    bpy.utils.register_class(RagdollPreferences)

    _DATA.clear()
    _DATA.update(data)

    pref = bpy.context.preferences

    dpi_scale = (pref.view.ui_scale * pref.system.ui_scale)

    # Install values from Blender into core
    for key, value in _DATA["option"].items():
        if not value.get("monitor", False):
            continue

        property_name = value["name"]
        default_value = read(key)
        write(key, default_value)

    # Defined by Blender and used by Ragdoll too
    write("dpiScale", dpi_scale)
    write("resourcePath", dirname)

    bpx.unset_called(uninstall)


@bpx.call_once
def uninstall():
    bpy.utils.unregister_class(RagdollPreferences)
    bpy.utils.unregister_class(ResetPreferences)
    bpy.utils.unregister_class(SectionExpander)

    _DATA.clear()
    bpx.unset_called(install)
