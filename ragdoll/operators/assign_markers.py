import bpy
import ragdollc
from ..vendor import bpx
from .. import util, scene, constants, commands
from . import (
    PlaceholderOption,
    OperatorWithOptions,
)


class AssignMarkers(OperatorWithOptions):
    """Assign a Ragdoll marker to each selected objects or pose bones

    Add a unique marker to the selected object or pose bones, such that
    Ragdoll can find and simulate it.

    """
    bl_idname = "ragdoll.assign_markers"
    bl_label = "Assign Markers"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = ("Assign a Ragdoll marker to each selected objects or "
                      "pose-bones")
    icon = "REC"

    solver: PlaceholderOption("markersAssignSolver")
    group: PlaceholderOption("markersAssignGroup")
    refit: PlaceholderOption("markersRefit")
    auto_limit: PlaceholderOption("markersAutoLimit")
    auto_scale: PlaceholderOption("markersAutoSceneScale")
    create_ground: PlaceholderOption("markersCreateGround")
    prevent_identical_marker: PlaceholderOption("markersPreventIdentical")

    # Property name MUST be `always_invoke` for UI drawing
    always_invoke: PlaceholderOption("markersAssignAlwaysInvokeDialog")

    @classmethod
    def _selection(cls):
        types = (bpx.BpxObject, bpx.BpxBone)
        selection = bpx.selection(type=types)

        # The armature is also an BpxObject, and is typically
        # selected whenever a bone is but we never want to
        # actually assign to it.
        selection = list(filter(
            lambda s: not isinstance(s, bpx.BpxArmature), selection)
        )

        # Exclude any Ragdoll object
        selection = list(filter(
            lambda s: not s.type().startswith("rd"), selection)
        )

        return selection

    @classmethod
    def poll(cls, context):
        selection = cls._selection()

        if not selection:
            cls.poll_message_set("No selected Object or PoseBone")
            return False

        return True

    def execute(self, context):
        selection = self._selection()
        active_object = bpy.context.object
        connect = active_object and active_object.mode == "POSE"

        # Prevent the case of two transforms sharing space
        # Users can accidentally attempt to assign to sub-controls
        # meant as an offset to their original control.
        #
        # But, preserve the last duplicate, rather than first. As that
        # would be the one that is visible to the user in the viewport
        #  _          _          _
        # |_|-------||_||-------|_|
        #             ^     ^
        #             |     | preserve this
        #             |
        #             | not this
        #
        if connect and self.prevent_identical_marker and len(selection) > 1:
            # Discard any bone less than 50x smaller than the longest
            lengths = []
            for index, tm in enumerate(selection[:-1]):
                a = selection[index].position()
                b = selection[index + 1].position()
                lengths.append((a - b).length)

            max_length = max(lengths)
            tolerance = max_length / 50.0

            next_pos = selection[-1].position()
            for tm in reversed(list(selection[:-1])):
                pos = tm.position()

                if bpx.is_equivalent(pos, next_pos, tolerance):
                    self.report(
                        {"WARNING"}, "Identical transform '%s' skipped" % tm
                    )
                    selection.remove(tm)

                next_pos = pos

        # Compute a scale suitable for multiple selection
        overall_draw_scale = 1.0

        if len(selection) > 1:
            positions = [x.position() for x in selection]
            distances = [
                (positions[n + 1] - positions[n]).length
                for n in range(len(positions[:-1]))
            ]
            overall_draw_scale = sum(distances) / len(distances)
            overall_draw_scale /= 2.0

        new_solver = False
        assembly = util.find_assembly()

        with bpx.maintained_selection(context):
            solver = scene.find_or_create_current_solver()

            if not solver:
                # TODO: Consider "Auto Create Ground" flag
                # TODO: Consider "Auto Compute Scene Scale" flag
                bpy.ops.ragdoll.create_solver()

                if self.create_ground:
                    bpy.ops.ragdoll.create_ground()

                new_solver = True

            solver = scene.find_or_create_current_solver()
            assert solver

            markers = []
            new_markers = []
            last_index = len(selection) - 1

            for index, xobj in enumerate(selection):
                existing_marker = scene.object_to_marker(xobj)

                if existing_marker is not None:
                    # Append to existing hierarchy
                    markers.append(existing_marker)
                    continue

                if isinstance(xobj, bpx.BpxBone):
                    # Include armature name
                    obj_name = "%s.%s" % (xobj.handle().name, xobj.name())
                else:
                    obj_name = xobj.name()

                marker = scene.create("rdMarker", "rMarker_%s" % obj_name)
                markers.append(marker)
                new_markers.append(marker)
                bpx.link(marker, assembly)

                # Fill this in as early as possible, such that it
                # is accessible without evaluation
                xobj.data["entity"] = marker.data["entity"]

                parent = selection[index - 1] if index > 0 else None
                parent_marker = None

                if connect and parent:
                    marker["recordTranslation"] = False
                else:
                    marker["angularStiffness"] = 0
                    marker["linearStiffness"] = 0

                children = None
                if index < last_index:
                    children = (selection[index + 1],)

                if connect:
                    # Root is kinematic per default
                    if index == 0:
                        # Unless it's the only one
                        if len(selection) > 1:
                            marker["inputType"] = constants.InputKinematic

                    elif parent:
                        parent_marker = scene.object_to_marker(parent)
                        marker["parentMarker"] = parent_marker.handle()

                marker["originMatrix"] = xobj.matrix()
                marker["color"] = util.random_color()

                if connect and children:
                    # The `children` was picked by selection, use them.
                    geo = util.infer_geometry(xobj, parent, children)
                else:
                    # Although `children` is not specified, `infer_geometry()`
                    # will still try to find them by object/bone hierarchy.
                    geo = util.infer_geometry(xobj)

                marker["shapeType"] = geo.type  # enum
                marker["shapeExtents"] = geo.extents
                marker["shapeLength"] = geo.length
                marker["shapeRadius"] = geo.radius
                marker["shapeRadiusEnd"] = geo.radius * 0.5
                marker["shapeRotation"] = geo.rotation
                marker["shapeOffset"] = geo.offset

                if index > 0:
                    previous_marker = selection[index - 1]
                    previous_marker = scene.object_to_marker(previous_marker)
                    draw_scale = previous_marker["drawScale"].read()

                elif len(selection) > 1:
                    draw_scale = overall_draw_scale

                else:
                    draw_scale = geo.scale

                marker["drawScale"] = draw_scale

                commands.reassign(xobj, marker)
                commands.retarget(xobj, marker)

                # Try getting geometry from here as a starting point
                if isinstance(xobj.handle().data, bpy.types.Mesh):
                    marker["inputGeometry"] = {"object": xobj.handle()}

                # Used as a basis for angular limits
                if connect and parent:
                    util.reset_constraint_frames(marker)

                # Off per default
                marker["limitRange"] = (0, 0, 0)

                # Append to solver
                solver["members"].append({"object": marker.handle()})

        if not new_markers:
            self.report({"WARNING"}, "No markers were created")
            return {"CANCELLED"}

        # Automatically group assignments greater than 1
        if len(markers) > 1:
            group_enum = self.enum_to_index("group")
            existing_group = scene.find_group(markers[0])

            if group_enum == constants.AddToExisting and not existing_group:
                group_enum = constants.CreateNewGroup

            if group_enum == constants.AddToExisting:
                commands.move_to_group(markers[1:], existing_group)

            if group_enum == constants.CreateNewGroup:
                name = "%s_rGroup" % selection[0].name()
                xgroup = commands.create_group(solver, name=name)
                commands.move_to_group(markers, xgroup)

            if group_enum == constants.SpecificGroup:
                specific_group = self.group
                specific_group = bpx.find(specific_group)

                # This is ensured by the property generator
                assert specific_group, (
                    "%s did not exist, this is a bug" % group_enum
                )

                commands.move_to_group(*markers, specific_group)

            if not connect:
                xgroup["selfCollide"] = True

        if new_solver and self.auto_scale:
            solver["sceneScale"] = util.compute_scene_scale(solver)

        # Automatically highlight entities
        ragdollc.scene.deselect()
        for marker in markers:
            entity = marker.data["entity"]
            ragdollc.scene.select(entity, append=True)

        util.touch_initial_state(context)

        if not bpy.app.background:
            ui_open_physics_tab(context)

        return {"FINISHED"}


def ui_open_physics_tab(context):
    """Open physics tab to show marker assignment"""

    biggest = None
    maxsize = 0

    # Find biggest properties panel
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "PROPERTIES":
                if area.width >= 0 and area.height >= 0:
                    size = area.width * area.height
                    if size > maxsize:
                        maxsize = size
                        biggest = area

    # Switch to physics tab
    if biggest:
        for space in biggest.spaces:
            if space.type == "PROPERTIES":
                try:
                    space.context = "PHYSICS"
                except TypeError:
                    # Possibly GUI is not updated yet, but that's fine.
                    # Could happen when building physics scene via script.
                    pass


def install():
    bpy.utils.register_class(AssignMarkers)


def uninstall():
    bpy.utils.unregister_class(AssignMarkers)
