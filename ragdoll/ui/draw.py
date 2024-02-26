import bpy
import blf

import os
import json
import fnmatch

from ..vendor import bpx
from . import icons


class PropertiesPanel(bpy.types.Panel):
    sub_panels: dict = None

    @classmethod
    def get_xobject(cls, context) -> bpx.BpxType | None:
        if context.object:
            return bpx.BpxType(context.object)

    @classmethod
    def register(cls):
        for sub_panel_cls in cls.sub_panels.values():
            bpy.utils.register_class(sub_panel_cls)

    @classmethod
    def unregister(cls):
        for sub_panel_cls in cls.sub_panels.values():
            bpy.utils.unregister_class(sub_panel_cls)
        cls.sub_panels.clear()


def with_properties(fname):
    def wrapper(cls):
        cls.sub_panels = dict()

        for title, properties_data, options in _iter_layout_data(fname):
            child_panel = _make_child_panel_class(
                parent_class=cls,
                title=title,
                properties_data=properties_data,
                options=options,
            )
            key = child_panel.__name__
            cls.sub_panels[key] = child_panel

        return cls

    return wrapper


def _iter_layout_data(fname):
    """Iterate properties and their sub-panel title from Ragdoll resources
    """
    dirname = os.path.dirname(os.path.dirname(__file__))  # ragdoll
    dirname = os.path.join(dirname, "resources", "archetypes")

    filepath = os.path.join(dirname, fname)

    with open(filepath, "r") as f:
        data = json.load(f)

    order = data["panel"].pop("__order__", None) or data["panel"].keys()
    expand = data["panel"].pop("__expand__", [])
    panel_count = len(order)

    for title in order:
        properties = data["panel"][title]

        if properties:
            options = set()  # Panel bl_options

            if title not in expand:
                options.add("DEFAULT_CLOSED")

            if panel_count == 1:
                options.add("HIDE_HEADER")

            properties_data = [
                # Note: empty string indicates a separator
                (name, data["property"][name] if name else None)
                for name in properties
            ]

            yield title, properties_data, options


def _make_child_panel_class(parent_class, title, properties_data, options):
    """Generate child panel class from parent panel class

    Arguments:
        parent_class: Parent panel class
        title: Title of child panel
        properties_data: A list of properties to draw in child panel
        options: A set for `bl_options`

    Returns:
        (type): Generated panel class

    """
    bl_parent_id = parent_class.__name__

    def draw(self, context):
        entity_object = parent_class.get_xobject(context)
        _draw_properties(self.layout, entity_object, properties_data)

    suffix = title.replace(" ", "_").upper()
    name = bl_parent_id + "_" + suffix  # Note: Maximum class name is 64 char
    attrs = dict(
        bl_label=title,
        bl_parent_id=bl_parent_id,
        bl_space_type="PROPERTIES",
        bl_region_type="WINDOW",
        bl_context="physics",
        poll=parent_class.poll,
        draw=draw,
    )
    if options:
        attrs.update(bl_options=options)

    return type(name, (bpy.types.Panel,), attrs)


def _draw_properties(
        layout,
        entity_object: bpx.BpxType,
        properties_data: list
):
    layout.use_property_split = True

    if len(properties_data) < 4:
        # Keep vertical when there's not much of them. Avoid text elide.
        sub_layout = layout.column()
    else:
        sub_layout = layout.grid_flow(row_major=False,
                                      columns=0,
                                      even_columns=True,
                                      even_rows=False,
                                      align=True)

    prop_group = entity_object.property_group()
    annotations = getattr(prop_group, "__annotations__", None)
    if annotations and properties_data:

        for name, data in properties_data:
            if name == "":
                col = sub_layout.column()
                col.separator_spacer()
                continue

            keywords = getattr(annotations.get(name), "keywords", None)
            if keywords is None:
                continue

            if "HIDDEN" not in keywords.get("options", {"HIDDEN"}):

                # Only render this property if any condition satisfied.
                con = data.get("conditions")
                if con and not any(_iter_conditions(entity_object, con)):
                    continue

                col = sub_layout.column()
                label = keywords.get("name", "")
                type_name = keywords.get("type", type).__name__

                if type_name == "RdPointerPropertyGroup":
                    _draw_pointer(col, prop_group, name, label)

                else:
                    col.prop(prop_group, name, text=label)

    else:
        box = sub_layout.box()
        box.label(text="No property to render, this is a bug.",
                  icon="ERROR")


def _iter_conditions(entity_object, conditions):
    for condition in conditions:
        yield entity_object[condition["name"]].read() == condition["equal"]


def _draw_pointer(layout, prop_group, prop_name, label):
    pointer = getattr(prop_group, prop_name)

    row = layout.row()
    row.prop(pointer, "object", text=label, icon="OBJECT_DATA")

    if pointer.boneid:
        bone = bpx.find_bone_by_uuid(pointer.object, pointer.boneid)
        row.prop(bone, "name", text="", icon="BONE_DATA")


def ragdoll_header(layout, text, icon):
    row = layout.row(align=True)
    row.label(text="", icon_value=icons.fname_to_icon_id["logo2.png"])
    row.separator()
    row.label(text=text, icon=icon)
    return row


def merge_flt_flags(l1, l2):
    # https://github.com/blender/blender-addons/blob/main/
    # object_collection_manager/ui.py#L1210
    for idx, _ in enumerate(l1):
        l1[idx] &= l2.pop(0)
    return l1 + l2


def filter_items_by_name(
        pattern,
        bitflag,
        items,
        propname="name",
        flags=None,
        reverse=False,
):
    """Filter items in UI_list

    Modified from `bpy.types.UI_UL_list.filter_items_by_name()`, to support
    nested `propname`.

    """

    if not pattern or not items:  # Empty pattern or list = no filtering!
        return flags or []

    if flags is None:
        flags = [0] * len(items)

    # Implicitly add heading/trailing wildcards.
    pattern = "*" + pattern + "*"

    def get_nested_attr(it):
        path = propname.split(".")
        while path:
            it = getattr(it, path.pop(0), "")
        return it

    for i, item in enumerate(items):
        name = get_nested_attr(item)
        # This is similar to a logical xor
        if bool(name and fnmatch.fnmatch(name, pattern)) is not bool(reverse):
            flags[i] |= bitflag
    return flags


def sort_items_by_name(items, propname="name"):
    """Sort items in UI_list

    Modified from `bpy.types.UI_UL_list.sort_items_by_name()`, to support
    nested `propname`.

    """
    def get_nested_attr(it):
        path = propname.split(".")
        while path:
            it = getattr(it, path.pop(0), "")
        return it

    _sort = [
        (idx, get_nested_attr(it)) for idx, it in enumerate(items)
    ]
    _sort.sort(key=lambda e: e[1].lower(), reverse=False)

    neworder = [None] * len(_sort)
    for newidx, (orgidx, *_) in enumerate(_sort):
        neworder[orgidx] = newidx

    return neworder


def line_wrap(
        text: str,
        width: float,
        padding: int = 10,
) -> tuple[list[str], float]:
    """Split and wrap text into lines

    Arguments:
        text: Text to wrap
        width: GUI layout width
        padding: GUI layout padding, if any. Default 10

    Returns:
        lines: A list of lines
        line_height: The height for a single line, measured with char 'W'

    """

    lines = []

    font_id = 0  # default font
    pref = bpy.context.preferences
    width = (width - padding) * pref.system.ui_scale
    width *= 0.94  # magic number

    point_size = pref.ui_styles[0].widget_label.points
    point_size *= pref.system.ui_scale
    blf.size(font_id, point_size)

    for line in text.split("\n"):
        if not line:
            continue

        words = []
        line_width = 0
        for word in line.split():
            w, _ = blf.dimensions(font_id, word + " ")

            if (line_width + w) < width:
                words.append(word)
                line_width += w
            else:
                lines.append(" ".join(words))

                words = [word]
                line_width = w

        if words:
            lines.append(" ".join(words))

    _, line_height = blf.dimensions(font_id, "W")

    return lines, line_height


def multi_lines(layout, text: str, width: float, padding: int = 10) -> None:
    """Draw text into multiple lines

    Arguments:
        layout: An instance of `bpy.types.UILayout`
        text: Text to wrap
        width: GUI layout width
        padding: GUI layout padding, if any. Default 10

    """
    lines, line_height = line_wrap(text, width, padding)

    # Although we have line_height computed, but that cannot be used directly
    # by `ui_units_y`. We need to scale that value, but since we don't know
    # how layout height was computed..., these are magic numbers.
    h_scale = {
        "LAYOUT_COLUMN": 0.06,
        "LAYOUT_BOX": 0.04,
    }
    layout_type = layout.introspect()[0]["type"]
    ui_units_y = line_height * h_scale.get(layout_type, 0.06)

    for line in lines:
        row = layout.row()
        row.ui_units_y = ui_units_y
        row.label(text=line)

    layout.separator()  # bottom spacing
