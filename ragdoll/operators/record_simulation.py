import bpy
import traceback
import collections

import ragdollc
from ragdollc import registry

from . import OperatorWithOptions, PlaceholderOption
from .. import scene, constants, types, log
from ..ui import icons
from ..vendor import bpx


class RecordSimulation(OperatorWithOptions):
    """Transfer simulation into animation

    Record the simulation as animation onto the marker targets.

    """
    bl_idname = "ragdoll.record_simulation"
    bl_label = "Record Simulation"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Record Ragdoll physics simulation into keyframes"

    icon = "record.png"

    auto_cache: PlaceholderOption("markersRecordAutoCache")
    update_viewport: PlaceholderOption("markersRecordUpdateViewport")

    extract_only: bpy.props.BoolProperty(
        name="Extract Only",
        description=(
            "Generate an independent hierarchy of "
            "Blender objects of the simulation"
        ),
        default=False,
        options={"SKIP_SAVE", "HIDDEN"},
    )

    attach_only: bpy.props.BoolProperty(
        name="Attach Only",
        description="Attach to simulation, but do not generate any keyframes",
        default=False,
        options={"SKIP_SAVE", "HIDDEN"},
    )

    # Property name MUST be `always_invoke` for UI drawing
    always_invoke: PlaceholderOption("markersRecordAlwaysInvokeDialog")

    @classmethod
    def poll(cls, context):
        if not bpx.ls(type="rdSolver"):
            cls.poll_message_set("No Ragdoll solvers in the current scene")
            return False

        return True

    def execute(self, context):
        solvers = bpx.selection(type="rdSolver") or bpx.ls(type="rdSolver")

        if len(solvers) < 1:
            self.report({"ERROR"}, "No solver found")
            return {"CANCELLED"}

        if len(solvers) > 1:
            self.report({"ERROR"}, "Select exactly 1 solver")
            return {"CANCELLED"}

        solver = solvers[0]
        entity = solver.data["entity"]
        Time = registry.get("TimeComponent", entity)

        state = {
            "initialFrame": context.scene.frame_current,
            "wasCached": solver["cache"].read(),

            "startFrame": Time.startFrame,
            "endFrame": Time.endFrame,

            "solver": solver,
            "solverEntity": entity,
        }

        state["markers"] = _find_markers(solver)
        state["markerToDst"] = _find_destinations(state["markers"])
        state["markerToSrc"] = _generate_kinematic_hierarchy(solver)
        state["cache"] = {marker: {} for marker in state["markers"]}

        self._state = state
        self._runner_it = self._runner(context)

        self._temporary_objects = []
        self._temporary_constraints = []

        # These need to vanish as well
        self._temporary_objects.extend(state["markerToSrc"].values())

        # Try to step the recording process this quickly.
        # The viewport will redraw inbetween each step, making
        # the process visible to the end user.
        self._step_timer = context.window_manager.event_timer_add(
            # Fastest possible recording rate.
            # The timer will not be called until
            # the previous frame has finished anyway.
            0.001,

            window=context.window
        )

        if bpy.app.background or not self.update_viewport:
            self._headless_run(context)
            return {"FINISHED"}
        else:
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}

    def _headless_run(self, context):
        # Minimum progress indicator on mouse cursor if in GUI
        context.window_manager.progress_begin(0, 100)

        reported = set()
        for msg, progress in self._runner_it:
            context.window_manager.progress_update(progress)

            msg: str = "  %s %3d%%" % (msg.ljust(30, "."), progress // 5 * 5)
            if msg not in reported:
                reported.add(msg)
                print(msg)

        context.window_manager.progress_end()

    def modal(self, context, event):
        if event.type == "ESC":
            return self._on_cancelled(context)

        if event.type == "TIMER":
            return self._on_timer(context, event)

        return {"RUNNING_MODAL"}

    def _runner(self, context):
        """Perform all recording tasks in order

        Recording involves reading data out of Ragdoll, followed by
        transferring this worldspace data onto a vanilla set of empties
        in the scene. The characters/controls are then constrained to these
        empties and baked akin to any normal bake process.

        """

        solver = self._state["solver"]
        solver["cache"] = constants.StaticCache
        start, end = self._state["startFrame"], self._state["endFrame"]
        total = end - start

        with bpx.maintained_time(context), bpx.Timing() as t:
            for progress in self._sim_to_cache(context):
                yield "simulating", progress * 0.49

        log.info("_sim_to_cache in %.2fms (%d fps)" % (t.ms, total / t.s))

        yield "cache to curves", 50
        self._cache_to_curves(context)

        if self.extract_only:
            yield "finished", 100
            return

        yield "attaching", 60
        self._attach(context)

        if self.attach_only:
            yield "finished", 100
            return

        with bpx.maintained_time(context), bpx.Timing() as t:
            for progress in self._bake(context):
                yield "baking", 60 + progress * ((95 - 60) / 100)

        log.info("_bake in %.2fms (%d fps)" % (t.ms, total / t.s))

        yield "cleanup", 95
        self._cleanup(context)

        if not self.auto_cache:
            solver["cache"] = constants.Off

        yield "finished", 100

    def _cleanup(self, context):
        for xobj, con in self._temporary_constraints:
            if isinstance(xobj, bpx.BpxBone):
                obj = xobj.pose_bone()
            else:
                obj = xobj.handle()

            obj.constraints.remove(con)

        for xobj in self._temporary_objects:
            obj = xobj.handle()
            bpy.data.objects.remove(obj)

        self._temporary_objects.clear()
        self._temporary_constraints.clear()

    def _on_timer(self, context, event):
        try:
            msg, progress = next(self._runner_it)

        except StopIteration:
            return self._on_finished(context)

        except Exception:
            # Printed in the console, for the developer
            traceback.print_exc()

        else:
            return {"RUNNING_MODAL"}

        self.report({"ERROR"}, "Failed, this is a bug.")
        return self._on_cancelled(context)

    def _on_cancelled(self, context):
        duration = self._step_timer.time_duration
        self.report({"WARNING"}, "Interrupted after %.2f s" % duration)

        context.window_manager.event_timer_remove(self._step_timer)
        return {"CANCELLED"}

    def _on_finished(self, context):
        duration = self._step_timer.time_duration
        self.report({"INFO"}, "Finished in %.2fs" % duration)

        context.window_manager.event_timer_remove(self._step_timer)
        return {"FINISHED"}

    def _sim_to_cache(self, context):
        r"""Evaluate every frame between `start` and `end`

        We'll need to start from the solver start frame, even if the user
        provides a later frame. Since the simulation won't be accurate
        otherwise.


               |
               |
               |      |
               |  |   |
               | _|___|
                /     \
               |       |
               |       |
                \_____/

        ______________________

        """

        cache = self._state["cache"]
        start, end = self._state["startFrame"], self._state["endFrame"]
        solver = self._state["solver"]
        solver_entity = self._state["solverEntity"]
        frames = list(range(start, end + 1))  # End frame inclusive
        total = len(frames)

        # Erase any existing cache, unless having one is intended
        if not self._state["wasCached"]:
            solver["cache"] = False
            context.scene.frame_set(start)
            ragdollc.scene.evaluate(solver_entity)
            solver["cache"] = True

        # Ensure time is restored
        for frame in frames:
            # Step simulation
            context.scene.frame_set(frame)
            ragdollc.scene.evaluate(solver_entity)

            # Record results
            for marker in self._state["markers"]:
                entity = marker.data["entity"]
                out_matrix = ragdollc.scene.outputMatrix(entity)
                out_matrix = types.to_bltype(out_matrix)
                rigid = registry.get("RigidComponent", entity)

                cache[marker][frame] = {
                    "recordTranslation": marker["recordTranslation"].read(),
                    "recordRotation": marker["recordRotation"].read(),
                    "outputMatrix": out_matrix,

                    # Value is the sum of both the Marker and Group
                    "isKinematic": rigid.kinematic,
                }

            progress = frame - start
            percentage = 100.0 * progress / total
            yield percentage

    @bpx.with_cumulative_timing
    def _cache_to_curves(self, context):
        r"""Convert worldspace matrices into translate/rotate channels

                                 ___ z
        x |______       ____    /
          |   ___\_____/____\__/
        y |--/--  \___/      \
          | /   \________     \_____ x
          |/             \__________ y
        z o--------------------------

        """

        cache = self._state["cache"]
        marker_to_src = self._state["markerToSrc"]
        start, end = self._state["startFrame"], self._state["endFrame"]
        frames = range(start, end + 1)

        # Generate animation
        for marker, xjoint in marker_to_src.items():

            # In the rare case of markers being part of a hierarchy
            # of other markers, that is not part of any scene. They
            # would get picked up during the kinematic_hierarchy call,
            # but not be viable to cache. Let the user know something
            # is not right
            if marker not in cache:
                log.warning("%s was skipped" % marker)
                continue

            parent = marker["parentMarker"].read()
            use_parent = (
                parent in cache and
                _is_enabled(parent)
            )

            handle = xjoint.handle()

            for frame in frames:
                values = cache[marker][frame]
                matrix = values["outputMatrix"]

                if use_parent:
                    parent_matrix = cache[parent][frame]["outputMatrix"]
                    matrix = parent_matrix.inverted_safe() @ matrix

                # Note: scale is needed for e.g. a scaled armature
                handle.matrix_local = matrix

                handle.keyframe_insert(data_path="location", frame=frame)
                handle.keyframe_insert(data_path="rotation_euler", frame=frame)

    def _attach(self, context):
        marker_to_src = self._state["markerToSrc"]
        marker_to_dst = self._state["markerToDst"]
        cache = self._state["cache"]
        start = self._state["startFrame"]

        with bpx.maintained_time(context):
            # Maintain offset from here, markers and controls
            # are guaranteed to be aligned here.
            context.scene.frame_set(start)

            objs, cons = _attach(marker_to_src, marker_to_dst, cache)
            self._temporary_objects.extend(objs)
            self._temporary_constraints.extend(cons)

    def _bake(self, context):
        marker_to_dst = self._state["markerToDst"].copy()
        start, end = self._state["startFrame"], self._state["endFrame"]
        frames = list(range(start, end + 1))
        cache = self._state["cache"]

        # Skip markers that are entirely kinematic
        # Ragdoll isn't adding any new information here
        for marker, dst in self._state["markerToDst"].items():
            if all(frame["isKinematic"] for frame in cache[marker].values()):
                marker_to_dst.pop(marker)

        # The locked-state of channels do not change at run-time,
        # so it's safe and more performant to evaluate these up-front
        location_dofs = collections.defaultdict(set)
        rotation_dofs = collections.defaultdict(set)

        for dst in marker_to_dst.values():
            for axis in dst.unlocked_rotation():
                rotation_dofs[dst].add(axis)

            for axis in dst.unlocked_location():
                location_dofs[dst].add(axis)

        # Always bake to XYZ Euler
        for dst in marker_to_dst.values():
            if isinstance(dst, bpx.BpxBone):
                dst.pose_bone().rotation_mode = "XYZ"
            else:
                dst.handle().rotation_mode = "XYZ"

        with bpx.maintained_time(context):
            for frame in frames:
                context.scene.frame_set(frame)

                for marker, dst in marker_to_dst.items():
                    f = cache[marker][frame]

                    # Do not keyframe any kinematic frame
                    if f["isKinematic"]:
                        continue

                    if isinstance(dst, bpx.BpxBone):
                        armature = dst.handle()
                        handle = dst.pose_bone()

                        handle.matrix_basis = armature.convert_space(
                            pose_bone=handle,
                            matrix=dst.matrix(world=False),
                            from_space="POSE",
                            to_space="LOCAL",
                        )

                    else:
                        handle = dst.handle()
                        matrix = dst.matrix()
                        parent = dst.parent()

                        if parent:
                            matrix = parent.matrix().inverted_safe() @ matrix
                            handle.matrix_basis = matrix
                        else:
                            handle.matrix_basis = matrix

                    for axis in rotation_dofs[dst]:
                        handle.keyframe_insert("rotation_euler",
                                               frame=frame,
                                               index=axis)

                    for axis in location_dofs[dst]:
                        handle.keyframe_insert("location",
                                               frame=frame,
                                               index=axis)

                yield 100 * frame / (end - start)

    def _fast_bake(self, context):
        """Transfer cache directly to targets

        Only relevant for object destinations without parents

        """

        cache = self._state["cache"]
        marker_to_dst = self._state["markerToDst"]
        start, end = self._state["startFrame"], self._state["endFrame"]
        frames = list(range(start, end + 1))

        with bpx.maintained_time(context):
            for frame in frames:
                context.scene.frame_set(frame)

                for marker, dst in marker_to_dst.items():
                    values = cache[marker][frame]
                    matrix = values["outputMatrix"]

                    if isinstance(dst, bpx.BpxBone):
                        handle = dst.pose_bone()
                        handle.rotation_mode = "XYZ"
                        handle.matrix = matrix
                    else:
                        handle = dst.handle()
                        handle.rotation_mode = "XYZ"
                        handle.matrix_world = matrix

                    handle.keyframe_insert("rotation_euler", frame=frame)
                    handle.keyframe_insert("location", frame=frame)

                yield 60 + (frame - start) * ((95 - 60) / 100)


def _find_markers(solver):
    markers = []
    for el in solver["members"]:
        obj = el.object

        # May have been deleted
        if not obj:
            continue

        xobj = bpx.BpxType(obj)
        if xobj.type() == "rdMarker":
            markers.append(xobj)
    return markers


def _find_destinations(markers: list):
    # destinations = collections.defaultdict(list)
    destinations = {}  # TODO: There can be multiple destinations
    for marker in markers:
        for dst in marker["destinationTransforms"]:
            try:
                xdst = scene.source_to_object(dst)
            except bpx.ExistError:
                # May have been deleted
                continue

            destinations[marker] = xdst
    return destinations


# TODO: Needs a new name
def _find_destinations2(marker_to_dst: dict,
                        cache: dict,
                        include_animated=False):
    for marker, dst in marker_to_dst.items():
        if not _is_enabled(marker):
            continue

        if not include_animated:
            frames = cache[marker].values()
            if all(frame["isKinematic"] for frame in list(frames)):
                continue

        if not any((marker["recordTranslation"].read(),
                    marker["recordRotation"].read())):
            continue

        rotation = [False] * 3
        location = [False] * 3

        if marker["recordTranslation"].read():
            for axis in dst.unlocked_location():
                location[axis] = True

        if marker["recordRotation"].read():
            for axis in dst.unlocked_rotation():
                rotation[axis] = True

        yield marker, (dst, location, rotation)


def _find_hierarchy(solver):
    markers = _find_markers(solver)

    hierarchy = collections.defaultdict(list)
    for m in markers:
        parent = m["parentMarker"].read()

        if parent is None:
            continue

        parent = bpx.BpxType(parent)
        hierarchy[parent].append(m)

    return hierarchy


def _is_enabled(xobj):
    entity = xobj.data.get("entity")
    return entity and registry.get("EnabledComponent", entity).value


def _generate_kinematic_hierarchy(solver, root=None):
    markers = _find_markers(solver)
    marker_to_object = {}

    def _find_roots():
        roots_ = set()
        for marker in markers:
            parent = marker["parentMarker"].read()
            if parent is not None and _is_enabled(parent):
                continue

            roots_.add(marker)
        return roots_

    roots = _find_roots() if root is None else [root]
    hierarchy = _find_hierarchy(solver)

    def recurse(marker, parent=None):
        if not _is_enabled(marker):
            return

        name = "_temp_%s" % marker.name()
        xobj = bpx.create_object(bpx.e_empty_cube, name)
        xobj.handle().empty_display_size = 0.04

        if parent:
            bpx.reparent(xobj, parent)

        marker_to_object[marker] = xobj
        children = hierarchy.get(marker, [])

        for child in children:
            recurse(child, parent=xobj)

    for root in roots:
        recurse(root)

    return marker_to_object


def _attach(marker_to_src, marker_to_dst, cache):
    """Constrain destination controls to extracted simulated hierarchy

             o
             |
          o--o--o
         /   |   \
        /    |    \
       o   o-o-o   o
      /    |   |    \
     /     |   |     \
    o      |   |      o
           o   o
           |   |
           |   |
           |   |
         --o   o--

    """

    new_objects = []
    new_constraints = []

    def make_empty(name, type, size):
        xobj = bpx.create_object(bpx.e_empty_cube, name)
        xobj.handle().empty_display_type = type
        xobj.handle().empty_display_size = size
        new_objects.append(xobj)

        return xobj

    def make_dst_offset(_src, _dst):
        xoffset = make_empty(
            name="temp_dstOffset_%s" % _dst.name(),
            type="CONE",
            size=0.03,
        )

        xoffset_rot = make_empty(
            name="temp_dstOffsetRot_%s" % _dst.name(),
            type="SPHERE",
            size=0.02,
        )

        offset = xoffset.handle()
        offset_rot = xoffset_rot.handle()

        offset.matrix_world = _src.matrix()
        offset_rot.parent = offset
        offset_rot.matrix_local = (
            _src.matrix().inverted() @ _dst.matrix()
        )
        return xoffset, xoffset_rot

    # maintain = self._maintain_offset == constants.FromStart
    maintain = True

    for marker, dst in _find_destinations2(marker_to_dst, cache):
        (dst, unlocked_location, unlocked_rotation) = dst
        src = marker_to_src.get(marker, None)

        if not src:
            log.warning("%s had no source, this is a bug" % marker)
            continue

        # It's all locked!
        if not any(unlocked_location) and not any(unlocked_rotation):
            continue

        dst_offset, dst_offset_rot = make_dst_offset(src, dst)

        # Make the offsets follow their original
        if any(unlocked_location):
            objs, cons = _parent_space_constraint(
                dst_offset,
                dst,

                # Either from wherever it's being constrained
                # or from the offset at the time of being retargeted
                maintain_offset=maintain,

                # Account for locked channels
                use=unlocked_location,
            )

            new_objects.extend(objs)
            new_constraints.extend(cons)

        if any(unlocked_rotation):
            con = _orient_constraint(
                dst_offset_rot,
                dst,

                # Account for locked channels
                use=unlocked_rotation,
            )

            new_constraints.append(con)

        copy_loc = bpx.create_constraint(dst_offset, type="COPY_LOCATION")
        copy_rot = bpx.create_constraint(dst_offset, type="COPY_ROTATION")

        copy_loc.target = src.handle()
        copy_rot.target = src.handle()

        if isinstance(src, bpx.BpxBone):
            copy_loc.subtarget = src.pose_bone().name
            copy_rot.subtarget = src.pose_bone().name

    return new_objects, new_constraints


def _parent_space_constraint(xsrc: bpx.BpxType,
                             xdst: bpx.BpxType,
                             maintain_offset: bool,
                             use: list):
    assert isinstance(xsrc, bpx.BpxType), "%s was not a BpxType" % xsrc
    assert isinstance(xdst, bpx.BpxType), "%s was not a BpxType" % xdst

    new_constraints = []
    new_objects = []

    xempty = bpx.create_object(bpx.e_empty_plain_axes, name=xdst.name())
    xempty.handle().empty_display_size = 0.0  # As small as possible
    new_objects.append(xempty)

    if maintain_offset:
        mat_world = xdst.matrix()
        pos_world = mat_world.to_translation()
        xempty.handle().matrix_world = bpx.Matrix.Translation(pos_world)

    constraint = bpx.create_constraint(xempty, type="CHILD_OF")
    constraint.target = xsrc.handle()

    if isinstance(xsrc, bpx.BpxBone):
        constraint.subtarget = xsrc.pose_bone().name

    constraint.use_scale_x = False
    constraint.use_scale_y = False
    constraint.use_scale_z = False

    constraint = bpx.create_constraint(xdst, type="COPY_LOCATION")
    constraint.target = xempty.handle()

    new_constraints.append((xdst, constraint))

    constraint.target_space = "WORLD"
    if isinstance(xdst, bpx.BpxBone) and False:
        constraint.owner_space = "POSE"
    else:
        constraint.owner_space = "WORLD"

    if use:
        constraint.use_x = use[0]
        constraint.use_y = use[1]
        constraint.use_z = use[2]

    return new_objects, new_constraints


def _orient_constraint(xsrc: bpx.BpxType,
                       xdst: bpx.BpxType,
                       use: list):
    # How many degrees of freedom are there?
    dofs = list(xdst.unlocked_rotation())

    # Hinge axis
    #
    # o------------
    #  \
    #   \
    #    \
    #     \
    #      \
    #
    if len(dofs) == 1:
        # Make a new target along the Y axis of this source, and aim towards it
        #
        #  o----------->
        #
        aim_target = bpy.data.objects.new(name="aimTarget", object_data=None)
        bpy.context.collection.objects.link(aim_target)
        aim_target.parent = xsrc.handle()
        aim_target.location.y = 1

        constraint = bpx.create_constraint(xdst, type="TRACK_TO")
        constraint.target = aim_target
        constraint.track_axis = "TRACK_Y"
        constraint.up_axis = "UP_Z"
        constraint.use_target_z = True

    else:
        constraint = bpx.create_constraint(xdst, type="COPY_ROTATION")
        constraint.target = xsrc.handle()

        if isinstance(xsrc, bpx.BpxBone):
            constraint.subtarget = xsrc.pose_bone().name

        constraint.mix_mode = "REPLACE"
        constraint.owner_space = "WORLD"
        constraint.target_space = "WORLD"

        constraint.use_x = use[0]
        constraint.use_y = use[1]
        constraint.use_z = use[2]

    return (xdst, constraint)


class ExtractSimulation(bpy.types.Operator):
    bl_idname = "ragdoll.extract_simulation"
    bl_label = "Extract Simulation"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = (
        "Bake Ragdoll physics simulation to a new hierarchy of empties"
    )
    icon = "MOD_ARMATURE"

    @classmethod
    def poll(cls, context):
        if not bpx.ls(type="rdSolver"):
            cls.poll_message_set("No Ragdoll solvers in the current scene")
            return False

        return True

    def execute(self, context):
        return bpy.ops.ragdoll.record_simulation(extract_only=True)


class AttachSimulation(bpy.types.Operator):
    bl_idname = "ragdoll.attach_simulation"
    bl_label = "Attach to Simulation"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = (
        "Attach objects to Ragdoll physics simulation"
    )

    @classmethod
    def poll(cls, context):
        if not bpx.ls(type="rdSolver"):
            cls.poll_message_set("No Ragdoll solvers in the current scene")
            return False

        return True

    def execute(self, context):
        return bpy.ops.ragdoll.record_simulation(attach_only=True)


def install():
    bpy.utils.register_class(RecordSimulation)
    bpy.utils.register_class(AttachSimulation)
    bpy.utils.register_class(ExtractSimulation)


def uninstall():
    bpy.utils.unregister_class(RecordSimulation)
    bpy.utils.unregister_class(AttachSimulation)
    bpy.utils.unregister_class(ExtractSimulation)
