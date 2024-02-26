import bpy

from . import draw
from .. import constants, scene
from ..vendor import bpx
from ..operators import retarget_ui


def _update_selection_from_ui_index(solver_ui, context):
    if not solver_ui.targets_sel_sync:
        return

    if context.mode != "OBJECT":
        return  # Marker can only be selected in Object Mode.

    if not context.space_data:
        return  # Index changed programmatically, no ui data.

    if not context.space_data.use_pin_id:
        return  # We lost UI after selecting marker if not pinned.

    solver = solver_ui.id_data.rdSolver
    active = solver.members[solver_ui.targets_ui_index]
    if active.object:
        bpx.select([active.object.name_full])


def _update_ui_index_from_selection(solver_ui, context):
    if not solver_ui.targets_sel_sync:
        return

    if context.mode != "OBJECT":
        return  # Marker can only be active in Object Mode.

    solver = solver_ui.id_data.rdSolver
    if not len(solver.members):
        return

    selection = bpx.selection(type="rdMarker", active=True)
    if selection:
        marker_handle = selection[0].handle()

        @bpx.deferred
        def set_ui_index(ui_index):
            solver_ui.targets_ui_index = ui_index

        active = solver.members[solver_ui.targets_ui_index]
        if active.object != marker_handle:

            for index, item in enumerate(solver.members):
                if item.object == marker_handle:
                    set_ui_index(index)
                    break


class RdSolverUiPropertyGroup(bpy.types.PropertyGroup):
    type = "rdSolverUi"

    targets_ui_index: bpy.props.IntProperty(
        update=_update_selection_from_ui_index,
        description="The index of current retargeting marker"
    )

    targets_sel_sync: bpy.props.BoolProperty(
        default=True,
        description="Sync marker selection with scene. (require 'Pin ID' "
                    "toggled)",
    )

    # The hash value of one `bpy.types.Window` instance which was opened as
    # retargeting window.
    #
    # A Window?
    # To have a complete marker retargeting workflow in Blender, a persistent
    # recording target listing view is required. Instead of adding another tab
    # into 3D-View SideBar, we open another window for this. And that window
    # is set to show Properties Panel for target list. (solver object pinned)
    #
    # Why Hash Window?
    # In Properties Panel, solver object's properties and target list are both
    # displayed. But we are only interested in target list in that retargeting
    # window. Other panels should be hidden. So we compare hash value of that
    # `context.window` against our `targets_window` to decide if panel should
    # be rendered.
    targets_window: bpy.props.StringProperty()


@draw.with_properties("rdSolver.json")
class RD_PT_Solver(draw.PropertiesPanel):
    bl_label = ""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "physics"

    @classmethod
    def poll(cls, context):
        xobj = bpx.BpxType(context.object)
        if xobj.type() == "rdSolver":
            current_window = str(hash(context.window))
            retarget_window = xobj.handle().rdSolverUi.targets_window
            # We do not want any panel except "Targets" if this window is
            # created for Retargeting.
            return current_window != retarget_window
        return False

    def draw_header(self, _):
        draw.ragdoll_header(self.layout, text="Solver", icon="VIEW3D")

    def draw(self, context):
        pass


class RD_PT_Targets(bpy.types.Panel):
    bl_label = ""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "physics"

    @classmethod
    def poll(cls, context):
        xobj = bpx.BpxType(context.object)
        return xobj.type() == "rdSolver"

    def draw_header(self, _context):
        draw.ragdoll_header(self.layout, text="Targets", icon="CON_TRACKTO")

    def draw(self, context):
        layout = self.layout
        solver = context.object.rdSolver
        solver_ui = context.object.rdSolverUi

        is_in_window = solver_ui.targets_window == str(hash(context.window))
        if is_in_window:
            # Change row count with the height of retarget window
            row_count = retarget_ui.RetargetWindow.compute_row_count(context)
        else:
            row_count = 8

        # View
        column = layout.column()

        row = column.row()
        row.template_list(
            RD_UL_Targets.__name__,
            "",
            solver,
            "members",
            solver_ui,
            "targets_ui_index",
            rows=row_count,
            maxrows=row_count,
            type="DEFAULT",
        )

        column.separator()

        split = layout.split(factor=0.75)
        left = split.row(align=True)
        right = split.row()

        transform = retarget_ui.get_one_transform_from_selection()
        target_text = transform.name() if transform else ""

        marker_entity = 0
        if len(solver.members):
            active = solver.members[solver_ui.targets_ui_index]
            if active.object:
                member = bpx.BpxType(active.object)
                if member.type() == "rdMarker":
                    marker_entity = member.data["entity"]

        if not marker_entity:
            split.enabled = False

        op = left.operator(
            retarget_ui.Retarget.bl_idname,
            text="Retarget to.. %s" % target_text,
            icon="CON_TRACKTO",
        )
        op.marker = marker_entity
        op.append = False

        op = right.operator(
            retarget_ui.Untarget.bl_idname,
            text="Untarget",
            icon="RADIOBUT_OFF",
        )
        op.marker = marker_entity


class RD_UL_Targets(bpy.types.UIList):
    marker_shape_icons = {
        constants.BoxShape: "MESH_CUBE",
        constants.SphereShape: "MESH_UVSPHERE",
        constants.CapsuleShape: "META_CAPSULE",
        constants.MeshShape: "MESH_ICOSPHERE",
    }

    def is_valid_marker(self, item):
        if not item.object:
            return False

        xobj = bpx.BpxType(item.object)

        if not xobj.is_alive():
            return False

        if not xobj.type() == "rdMarker":
            return False

        if not xobj["sourceTransform"].read():
            return False

        return True

    def draw_item(self,
                  context,
                  layout,
                  data,
                  item,
                  icon,
                  active_data,
                  active_property,
                  index=0,
                  flt_flag=0):
        # Always show filter
        self.use_filter_show = True  # noqa

        split = layout.split(factor=0.5)
        src_layout = split.row()
        dst_layout = split.row()

        if not self.is_valid_marker(item):
            return

        marker = bpx.BpxType(item.object)

        dst_name = ""
        dst_is_bone = False
        dst_is_object = False

        destinations = marker["destinationTransforms"]
        try:
            # We only take first destination
            #
            # Why?
            #
            # Because if we want to draw all destinations in UIList, we need
            # an additional collection property which each entry represents
            # one marker-destination pair.
            #
            # The cost of that implementation is that we will then need to
            # inform UI to rebuild that collection whenever solver members
            # updated, marker destinations changed and marker parent if we
            # want to draw marker hierarchy indention.
            #
            # Which is a bit complex to have a clean separation between UI
            # code and system evaluation code.
            #
            pointer = destinations[0]  # RdPointerPropertyGroup

        except IndexError:
            pass

        else:
            xdst = scene.source_to_object(pointer)
            if xdst.is_alive():
                dst_name = xdst.name()
                dst_is_bone = isinstance(xdst, bpx.BpxBone)
                dst_is_object = isinstance(xdst, bpx.BpxObject)

        icon_shape = marker["shapeType"].read()
        icon_shape = self.marker_shape_icons.get(icon_shape, "MESH_ICOSPHERE")
        icon_color = (*marker["color"], 1.0)

        spacing = src_layout.row()
        spacing.separator()

        # color dot
        subrow = src_layout.row()
        subrow.template_node_socket(color=icon_color)
        subrow.scale_x = 0.4

        # marker shape, name
        src_layout.label(text=marker.name(), icon=icon_shape)

        # transform icon, name
        icon = ("BONE_DATA" if dst_is_bone else
                "MESH_DATA" if dst_is_object else
                "GHOST_DISABLED")
        dst_layout.label(text=dst_name, icon=icon)

    def draw_filter(self, context, layout):
        solver_ui = context.object.rdSolverUi
        row = layout.row()

        subrow = row.row(align=True)
        _r = subrow.row(align=True)
        _r.prop(
            solver_ui,
            "targets_sel_sync",
            text="",
            icon="RESTRICT_SELECT_OFF",
            toggle=1,
            icon_only=True,
        )
        _r.enabled = (
            # Marker can only be selected in Object Mode.
            context.mode == "OBJECT" and
            # We lost UI after selecting marker if not pinned.
            context.space_data.use_pin_id
        )

        subrow = row.row(align=True)
        subrow.prop(self, "filter_name", text="")
        subrow.prop(
            self,
            "use_filter_invert",
            icon="ARROW_LEFTRIGHT",
            toggle=1,
            icon_only=True,
        )

        subrow = row.row(align=True)
        subrow.prop(
            self,
            "use_filter_sort_alpha",
            icon="SORTALPHA",
            toggle=1,
            icon_only=True,
        )
        subrow.prop(
            self,
            "use_filter_sort_reverse",
            icon="SORT_DESC" if self.use_filter_sort_reverse else "SORT_ASC",
            toggle=1,
            icon_only=True,
        )

    def filter_items(self, context, data, propname):
        solver = data
        members = getattr(solver, propname)

        # Default return values.
        flt_flags = []
        flt_neworder = []

        if self.filter_name:
            new_flt_flags = draw.filter_items_by_name(
                self.filter_name,
                self.bitflag_filter_item,
                members,
                "object.name",
                reverse=self.use_filter_invert,
            )
            flt_flags = draw.merge_flt_flags(flt_flags, new_flt_flags)

        if not flt_flags:
            flt_flags = [self.bitflag_filter_item] * len(members)

        # Filter out non-marker, dead-marker
        for idx, item in enumerate(members):
            if not self.is_valid_marker(item):
                flt_flags[idx] = 0

        if self.use_filter_sort_alpha:
            flt_neworder = draw.sort_items_by_name(members, "object.name")

        if self.use_filter_invert:
            for idx, flag in enumerate(flt_flags):
                flt_flags[idx] = 0 if flag else self.bitflag_filter_item

        # This `filter_items` function gets called whenever scene
        # selection changed. So we use it as a callback to update
        # ui_index.
        solver_ui = solver.id_data.rdSolverUi
        _update_ui_index_from_selection(solver_ui, context)

        return flt_flags, flt_neworder


def install():
    scene.register_property_group(RdSolverUiPropertyGroup)

    bpy.utils.register_class(RD_PT_Solver)
    bpy.utils.register_class(RD_PT_Targets)
    bpy.utils.register_class(RD_UL_Targets)


def uninstall():
    bpy.utils.unregister_class(RD_PT_Solver)
    bpy.utils.unregister_class(RD_PT_Targets)
    bpy.utils.unregister_class(RD_UL_Targets)

    scene.unregister_property_group(RdSolverUiPropertyGroup)
