"""Scripting interface for Ragdoll operators

Operators use this module to perform scene manipulation and anything that
does not involve user interactivity or selection.

This module shall not access any operators, and is intended for either
operators or scripting of Ragdoll via Python.

"""

import bpy
import ragdollc
from ragdollc import registry

from .vendor import bpx
from . import scene, util, constants, types, log


def reassign(transform, marker):
    assert isinstance(transform, bpx.BpxType), (
        "%s was not a BpxObject or BpxBone" % transform
    )
    assert marker and marker.type() in ("rdMarker", "rdEnvironment"), (
        "%s was not a rdMarker" % marker
    )

    entry = {
        "object": transform.handle(),
    }

    if isinstance(transform, bpx.BpxBone):
        entry.update({
            "boneid": transform.boneid(),
            "boneidx": transform.boneidx(),
        })

    marker["sourceTransform"] = entry


def retarget(transform, marker, append=False):
    """Retarget `marker` to `transform`

    When recording, write simulation from `marker` onto `transform`,
    regardless of where it is assigned.

    Arguments:
        marker (bpx.BpxType): Marker object.
        transform (bpx.BpxBone | bpx.BpxObject): An object or pose-bone to
            bake simulation to.
        append: Append one more transform into recording list if `True`.
            Previous targets will be replaced by `transform` if `False`.

    """

    assert marker and marker.type() == "rdMarker", (
        "%s was not a rdMarker" % marker
    )

    if not append:
        untarget(marker)

    entry = {
        "object": transform.handle(),
    }

    if isinstance(transform, bpx.BpxBone):
        entry.update({
            "boneid": transform.boneid(),
            "boneidx": transform.boneidx(),
        })

    marker["destinationTransforms"].append(entry)

    # Update recordability
    marker["recordTranslation"] = any(transform.unlocked_location())
    marker["recordRotation"] = any(transform.unlocked_rotation())

    marker.property_group().on_property_changed(
        marker.data["entity"], "destinationTransforms"
    )


def untarget(marker):
    """Remove all recording targets from `marker`

    Arguments:
        marker (bpx.BpxType): Marker object.

    """

    assert marker and marker.type() == "rdMarker", (
        "%s was not a rdMarker" % marker
    )

    count = 0

    # Remove `entity` from old target
    for dest in marker["destinationTransforms"]:
        xobj = scene.source_to_object(dest)
        xobj.data.pop("entity", None)
        count += 1

    marker["destinationTransforms"].clear()

    marker.property_group().on_property_changed(
        marker.data["entity"], "destinationTransforms"
    )

    return count


def replace_mesh(marker, mesh, maintain_offset=True, maintain_history=False):
    assert isinstance(marker, bpx.BpxObject) and marker.type() == "rdMarker", (
        "%s wasa not a marker" % marker
    )
    assert isinstance(mesh, bpx.BpxObject), (
        "%s was not a bpy.types.Mesh" % mesh
    )
    assert isinstance(mesh.handle().data, bpy.types.Mesh), (
        "%s was not a bpy.types.Mesh" % mesh
    )

    if not maintain_history:
        name = mesh.name() + "_copy"
        new_mesh = bpx.create_object(bpx.e_cube, name=name)
        new_mesh.handle().matrix_world = mesh.handle().matrix_world

        # Get the final evaluated mesh, rather than the undeformed one
        handle = mesh.handle()
        dg = bpy.context.evaluated_depsgraph_get()

        try:
            msh = handle.evaluated_get(dg).to_mesh()
        except RuntimeError:
            # No mesh here, this would mean the connected
            # object is not a mesh
            return

        new_mesh.handle().data = msh.copy()

        # Don't bother the user with this
        bpx.hide(new_mesh)

        mesh = new_mesh

    if maintain_offset:
        source = marker["sourceTransform"].read()
        source_mtx = source.matrix()
        mesh_mtx = mesh.matrix()
        mesh_mtx = source_mtx.inverted_safe() @ mesh_mtx
        marker["inputGeometryMatrix"] = mesh_mtx

    marker["shapeType"] = constants.MeshShape
    marker["inputGeometry"] = {"object": mesh.handle()}


def create_group(solver, name="rGroup"):
    group = scene.create("rdGroup", name=name)
    bpx.link(group, util.find_assembly())

    solver["members"].append({"object": group.handle()})
    return group


def move_to_group(markers, group):
    assert all(isinstance(m, bpx.BpxType) for m in markers), (
        "%s was not a series of markers"
    )
    assert isinstance(group, bpx.BpxObject) and group.type() == "rdGroup", (
        "%s was not a rdGroup"
    )

    for marker in markers:
        group["members"].append({"object": marker.handle()})

    # Dirty "members" property
    for xobj in bpx.ls(type="rdSolver"):
        entity = xobj.data.get("entity")
        ragdollc.scene.propertyChanged(entity, "members")


def remove_from_group(markers, group=None):
    """Remove `markers` from `group` or all groups"""
    if group is None:
        groups = bpx.ls(type="rdGroup")
    else:
        groups = (group,)

    for group in groups:
        for marker in markers:
            try:
                index = group["members"].index({"object": marker.handle()})
            except IndexError:
                continue

            # Ungroup
            group["members"].remove(index)

    # Dirty "members" property
    for xobj in bpx.ls(type="rdSolver"):
        entity = xobj.data.get("entity")
        ragdollc.scene.propertyChanged(entity, "members")


def merge_solvers(a, b):
    for member in a["members"]:
        if not member:
            continue

        b["members"].append({"object": member.object})

    bpx.delete(a)

    return True


def uncache(solver):
    solver["cache"] = False
    ragdollc.scene.evaluate(solver.data["entity"])


def cache(solver):
    for _ in cache_iter([solver]):
        pass  # Iter from start frame to end


def cache_iter(solvers):
    """Persistently store the simulated result of the `solvers`

    Use this to scrub the timeline both backwards and forwards without
    re-simulating anything.

    """

    context_scene = bpy.context.scene

    # Remember where we came from
    initial_frame = context_scene.frame_current

    entities = {s.data["entity"] for s in solvers}
    start_frame = min({
        registry.get("TimeComponent", solver_entity).startFrame
        for solver_entity in entities
    })
    start_frame = int(start_frame)
    end_frame = context_scene.frame_end
    total = end_frame - start_frame

    context_scene.frame_set(start_frame)
    for solver in solvers:
        # Clear existing cache
        solver["cache"] = False
        ragdollc.scene.evaluate(solver.data["entity"])

        # Updated cache
        solver["cache"] = True

    for frame in range(start_frame, end_frame + 1):
        context_scene.frame_set(frame)

        for solver_entity in entities:
            ragdollc.scene.evaluate(solver_entity)

        percentage = 100 * float(frame - start_frame) / total
        yield percentage

    # Restore where we came from
    context_scene.frame_set(initial_frame)


def snap_to_simulation(solver, opts=None):
    """Transfer current simulated pose into keyframes

    Wherever Markers are within a solver, this function transfers them
    out into the "real world" as actual keyframes on anything that isn't
    locked or kinematic.

    """

    opts = dict({
        "iterations": 2,
        "keyframe": False,
    }, **(opts or {}))

    def transfer(dst):
        entity = dst.data["entity"]

        mtx = ragdollc.scene.outputMatrix(entity)

        # Maintain whatever offset exists between the pure FK
        # marker and the current controller.
        # TODO: Need to store the destination rest matrix
        src_rest_mtx = registry.get("RestComponent", entity).value
        dst_rest_mtx = src_rest_mtx
        offset_mtx = dst_rest_mtx @ src_rest_mtx.inverted()

        mtx = offset_mtx @ mtx

        if isinstance(dst, bpx.BpxBone):
            armature = dst.handle()

            if armature is None:
                log.warning("%s wasn't an armature, this is a bug." % dst)
                return

            handle = dst.pose_bone()
            handle.matrix_basis = armature.convert_space(
                pose_bone=handle,
                matrix=types.to_bltype(mtx),
                from_space="WORLD",
                to_space="LOCAL",
            )
        else:
            handle = dst.handle()
            handle.matrix_world = types.to_bltype(mtx)

    current_frame = bpy.context.scene.frame_current

    # Find roots
    #
    # We find the root of each Marker here and apply the simulation
    # onto the entire hierarchy. Since we cannot affect a child without
    # also affects its parent. They affect each other.
    #
    roots = set()
    for el in solver["members"]:
        # May have been disconnected/deleted
        if not el.object:
            continue

        marker = bpx.BpxType(el.object)

        if marker.type() != "rdMarker":
            continue

        entity = marker.data["entity"]

        rigid = registry.get("RigidComponent", entity)
        if rigid.kinematic:
            continue

        dsts = marker["destinationTransforms"]

        # May not have a target
        if len(dsts) > 0 and dsts[0].object:
            roots.add(dsts[0].object)

    # Find destinations
    dsts = []
    for root in roots:
        if isinstance(root.data, bpy.types.Armature):
            for bone in root.pose.bones:
                xbone = bpx.BpxBone(bone)
                entity = xbone.data.get("entity")

                if not entity:
                    continue

                rigid = registry.get("RigidComponent", entity)
                if rigid and rigid.kinematic:
                    continue

                level = len(bone.parent_recursive)

                # Sort both by armature and level, such that
                # each armature gets transferred in full before
                # the next one.
                dsts.append((xbone, id(root) + level))
        else:
            xobj = bpx.BpxObject(root)
            marker = bpx.alias(entity)

            level = 0
            parent = root.parent
            while parent:
                level += 1
                parent = parent.parent

            dsts.append((xobj, level))

    # Filter by recordTranslation/Rotation property
    filtered_dsts = []
    for x, _ in dsts[:]:
        entity = x.data.get("entity")
        marker = bpx.alias(entity)

        record_translation = marker["recordTranslation"].read()
        record_rotation = marker["recordRotation"].read()

        if any((record_translation, record_rotation)):
            filtered_dsts.append((x, _))

        else:
            log.info(
                "%s skipped because recordTranslation "
                "and recordRotation was both disabled." % x
            )
    dsts = filtered_dsts

    for it in range(opts["iterations"]):
        last_iteration = it == (opts["iterations"] - 1)

        for dst, _ in sorted(dsts, key=lambda i: i[1]):
            transfer(dst)

            # Keyframe ahead of updating the dependency graph,
            # otherwise existing keyframe animation or constraints
            # would override what we've just transferred.
            if last_iteration and opts["keyframe"]:
                if isinstance(dst, bpx.BpxBone):
                    handle = dst.pose_bone()
                else:
                    handle = dst.handle()

                entity = dst.data.get("entity")
                marker = bpx.alias(entity)

                record_translation = marker["recordTranslation"].read()
                record_rotation = marker["recordRotation"].read()

                if record_rotation:
                    if handle.rotation_mode == "AXIS_ANGLE":
                        handle.keyframe_insert("rotation_axis_angle",
                                               frame=current_frame)
                    elif handle.rotation_mode == "QUATERNION":
                        handle.keyframe_insert("rotation_quaternion",
                                               frame=current_frame)

                    else:
                        # Euler angles can be individually locked,
                        # which is only really relevant to Euler and not
                        # axis-angle or quaternions.
                        for axis in dst.unlocked_rotation():
                            handle.keyframe_insert("rotation_euler",
                                                   frame=current_frame,
                                                   index=axis)

                if record_translation:
                    for axis in dst.unlocked_location():
                        handle.keyframe_insert("location",
                                               frame=current_frame,
                                               index=axis)

            # We've moved what is possibly a parent and need
            # children to update to their new position before
            # attempting to transfer more matrices.
            dg = bpy.context.evaluated_depsgraph_get()
            dg.update()


def return_to_start(solver=None):
    start = 1e9

    if solver is None:
        solvers = bpx.ls(type="rdSolver")
    else:
        solvers = [solver]

    # Find the first out of potentially many start frames
    for solver in solvers:
        entity = solver.data["entity"]
        Time = registry.get("TimeComponent", entity)
        if Time.startFrame < start:
            start = Time.startFrame

    if start != 1e9:
        bpy.context.scene.frame_set(start)
        bpx.info("Returned to %d" % start)
