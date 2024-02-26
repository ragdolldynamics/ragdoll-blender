"""General utilities that take Blender and Ragdoll into account

This is different from bpx in that it knows about Ragdoll and do things
specific to Ragdoll.

NOTE: This may import all Ragdoll modules, but none other
      than operators may import this.

"""

import bpy
import random
import colorsys
import functools
from dataclasses import dataclass, field

from ragdollc import registry

from . import constants, viewport
from .vendor import bpx


# Components
@dataclass
class Geometry:
    type: int = constants.SphereShape
    extents: bpx.Vector = field(default_factory=lambda: bpx.Vector((1, 1, 1)))
    radius: float = 0.0
    length: float = 0.0
    orient: bpx.Quaternion = field(default_factory=bpx.Quaternion)
    offset: bpx.Quaternion = field(default_factory=bpx.Vector)
    rotation: bpx.Euler = field(default_factory=bpx.Euler)
    scale: float = 1.0


def find_assembly(context=None):
    context = context or bpy.context

    if len(bpy.data.scenes) > 1:

        # Make life prettier for defaults
        if context.scene.name == "Scene":
            assembly = "Ragdoll"

        else:
            assembly = "%s.Ragdoll" % context.scene.name
    else:
        assembly = "Ragdoll"

    if assembly in bpy.data.collections:
        assembly = bpy.data.collections[assembly]
    else:
        assembly = bpx.create_collection(assembly)

    return assembly


def touch_initial_state(context=None):
    context = context or bpy.context
    current_frame = context.scene.frame_current
    first_start_frame = current_frame

    for solver in bpx.ls("rdSolver"):
        entity = solver.data["entity"]
        Time = registry.get("TimeComponent", entity)

        if Time.startFrame < first_start_frame:
            first_start_frame = Time.startFrame

        # Anything affecting the initial state must also be initialised
        if solver["cache"]:
            solver["cache"] = 0

    # Don't bother if we're already there
    if first_start_frame < current_frame:
        context.scene.frame_set(first_start_frame)

    viewport.add_evaluation_reason("initial_state_changed")


def affects_initial_state(func):
    """Recipients of this decorator affect the initial state in some way

    Initial state can only be modified when on (or before) the start frame
    and without the use of any cache.

    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            touch_initial_state()

    return wrapper


def infer_geometry(root: bpx.BpxType,
                   parent=constants.Auto,
                   children=constants.Auto,
                   geometry=None):
    """Find length and orientation from `root`

    This function looks at the child and parent of any given root for clues as
    to how to orient it. Length is simply the distance between `root` and its
    first child.

    Arguments:
        root (transform): The root from which to derive length and orientation
        parent (transform, optional): Use this for direction
        children (list of transforms, optional): Use this for size
        geometry (Geometry, optional): Build upon this geometry

    """
    geometry = _infer_geometry(root, parent, children, geometry)

    # Align the edge flow
    if geometry.type == constants.SphereShape:
        geometry.rotation.rotate_axis("X", bpx.radians(90))

    # Find a suitable draw scale
    if isinstance(root, bpx.BpxBone):
        if geometry.length < 0.3:
            geometry.scale = geometry.length * 0.5  # for foot or hand
        else:
            geometry.scale = geometry.length * 0.25
    else:
        geometry.scale = sum(geometry.extents) / 3.0

    return geometry


def _get_inverted_scale_matrix(root: bpx.BpxType):
    if isinstance(root, bpx.BpxBone):
        armature = root.handle()
        return bpx.Matrix.LocRotScale(
            bpx.Vector(),
            bpx.Quaternion(),
            armature.matrix_world.inverted_safe().to_scale(),
        )
    else:
        return bpx.Matrix.LocRotScale(
            bpx.Vector(),
            bpx.Quaternion(),
            root.matrix().inverted_safe().to_scale(),
        )


def _infer_geometry(root: bpx.BpxType,
                    parent=None,
                    children=None,
                    geometry=None):
    geometry = geometry or Geometry()

    original = root

    # Automatically find children
    if children is constants.Auto:
        children = _find_children(root)

    if not (parent or children or isinstance(root, bpx.BpxBone)):
        return _find_geometry_from_lone_transform(root)

    # Compute root matrix and pos
    #
    root_tm = root.matrix()  # bpx.Matrix
    root_tm = _get_inverted_scale_matrix(root) @ root_tm
    root_pos = root_tm.to_translation()  # bpx.Vector

    # Compute Length and Orient
    #
    if not children and isinstance(root, bpx.BpxBone):
        # Tip bone without children, use the native length of the bone
        pose_bone = root.pose_bone()
        geometry.length = (pose_bone.tail - pose_bone.head).length
        geometry.orient = root_tm.to_quaternion()
        geometry.orient @= bpx.Quaternion((0, 0, 1), bpx.radians(90))

    else:
        # There is a lot we can gather from the childhood
        length, orient = _length_and_orient_from_childhood(
            root, parent, children)

        geometry.length = length
        geometry.orient = orient

    # Find Radius and Offset
    #
    #   ________________________  ___
    #  / _                      \  |
    # | / \_________.            | |  radius (1.0)
    # | \_/         |            | |
    #  \____________|___________/ _|_
    #               |
    #            offset (1, 0, 0)
    #
    if geometry.length > 0.0:
        offset = bpx.Vector((geometry.length / 2.0, 0, 0))
        offset.rotate(geometry.orient)

        # If we don't have that, try and establish one from the bounding box
        if not geometry.radius > 0.0:
            handle = root.handle()

            if isinstance(handle, bpy.types.Object):
                bbox = handle.bound_box
                bbox_x = sorted(b[0] for b in bbox)
                bbox_y = sorted(b[1] for b in bbox)
                bbox_z = sorted(b[2] for b in bbox)

                extents = bpx.Vector((
                    bbox_x[-1] - bbox_x[0],
                    bbox_y[-1] - bbox_y[0],
                    bbox_z[-1] - bbox_z[0],
                ))

                radius = sorted([extents.x, extents.y, extents.z])

                # A bounding box will be either flat or long
                # That means 2/3 axes will be similar, and one
                # either 0 or large.
                #  ___________________
                # /__________________/|
                # |__________________|/
                #
                radius = radius[1]  # Pick middle one
                radius *= 0.5  # Width to radius
                radius *= 0.5  # Controls are typically larger than the model

            else:
                # If there's no visible geometry whatsoever, we have
                # very little to go on in terms of establishing a radius.
                geometry.radius = geometry.length * 0.1

        geometry.extents = bpx.Vector((
            geometry.length,
            geometry.radius * 2,
            geometry.radius * 2
        ))

    else:
        size, center = _hierarchy_bounding_size(root)
        tm = root_tm.copy()

        if all(axis == 0 for axis in size):
            geometry.length = 0
            geometry.radius = 1
            geometry.extents = bpx.Vector((1, 1, 1))

        else:
            geometry.length = size.x
            geometry.radius = min([size.y, size.z])
            geometry.extents = size

            # Embed length
            tm = bpx.Matrix.Translation(bpx.Vector((0, size.x * -0.5, 0))) @ tm

        offset = center - tm.translation

    # Compute final shape matrix with these ingredients
    shape_tm = bpx.Matrix.LocRotScale(root_pos,
                                      geometry.orient,
                                      bpx.Vector((1, 1, 1)))
    shape_tm = bpx.Matrix.Translation(offset) @ shape_tm
    shape_tm = root_tm.inverted_safe() @ shape_tm

    geometry.offset = shape_tm.translation
    geometry.rotation = shape_tm.to_quaternion().to_euler("XYZ")

    # Special case of having a length but nothing else
    if geometry.length > 0 and geometry.type == constants.SphereShape:
        geometry.type = constants.CapsuleShape

    # Apply possible negative scale to shape rotation
    # Use `original` in case we're at the tip
    orig_scale = original.matrix().to_scale()
    scale_mtx = (
        bpx.Matrix.Scale(orig_scale[0], 4, bpx.Vector((1, 0, 0))) @
        bpx.Matrix.Scale(orig_scale[1], 4, bpx.Vector((0, 1, 0))) @
        bpx.Matrix.Scale(orig_scale[2], 4, bpx.Vector((0, 0, 1)))
    )
    geometry.rotation = (scale_mtx @ shape_tm).to_quaternion().to_euler("XYZ")

    # Keep radius at minimum 10% of its length to avoid stick-figures
    geometry.radius = max(geometry.length * 0.1, geometry.radius)

    if not geometry.radius > 0:
        geometry.radius = 1.0

    return geometry


def compute_scene_scale(solver):
    """Determine scene scale of contained markers

    Arguments:
        solver (rdSolver): Solver node from which to query contained Markers

    """

    positions = []
    markers = []
    for el in solver["members"]:
        # May be disconnected
        if not el.object:
            continue

        object = bpx.BpxType(el.object)

        if object.type() != "rdMarker":
            continue

        markers.append(object)

    if not markers:
        return 1

    # Determine scale solely based on the 1 shape extents
    elif len(markers) < 2:
        marker = markers[0]
        source = marker["sourceTransform"].read()
        mtx = source.matrix()
        scale = mtx.to_scale()
        extents = marker["shapeExtents"].read()
        extents *= max(scale)
        max_length = max(extents)
        max_length *= 2

    # Determine scale based on the distance between markers
    else:
        for marker in markers:
            source = marker["sourceTransform"].read()
            mtx = source.matrix()
            position = mtx.to_translation()
            positions.append(position)

        # Assume transforms are provided in increasing distance from each other
        max_length = (positions[0] - positions[-1]).length

    scene_scale = 1

    # Below this scale, the user is mad. Leave them be.
    if max_length < 3:
        scene_scale = 1

    elif max_length < 30:
        scene_scale = 10

    # 300 cm, the tallest of humans
    elif max_length < 300:
        scene_scale = 100

    # Beyond this scale, the user is mad. Leave them be.
    else:
        pass

    return scene_scale


def _find_children(root: bpx.BpxType):
    children = []

    # Consider cases where children have no distance from their parent,
    # common in offset groups without an actual offset in them. Such as
    # for organisational purposes
    #
    # | hip_grp
    # .-o offset_grp    <-- Some translation
    #   .-o hip_ctl
    #     .-o hip_loc   <-- Identity matrix
    #
    root_pos = root.position()
    for child in root.children():
        child_pos = child.position()

        if not bpx.is_equivalent(root_pos, child_pos):
            children += [child]

    return children


def _find_geometry_from_lone_transform(root: bpx.BpxType):
    """Given a transform without parent or children, figure out its shape"""
    assert not isinstance(root, bpx.BpxBone), "%s was a bone" % root
    return _interpret_shape(root)


def _length_and_orient_from_childhood(root: bpx.BpxType, parent, children):
    """Return length and orientation from childhood

    Use the childhood to look for clues as to how a shape may
    be oriented.

    """

    if isinstance(children, list):
        children = tuple(children)

    assert isinstance(children, tuple), (
        "%s was not a list" % str(children)
    )

    length = 0.0
    orient = bpx.Quaternion()
    root_pos = root.position()

    # Support multi-child scenarios
    #
    #         o
    #        /
    #  o----o--o
    #        \
    #         o
    #
    positions = []
    for child in children:
        positions += [child.position()]

    pos2 = bpx.Vector((0, 0, 0))
    for pos in positions:
        pos2 += pos
    pos2 /= len(positions)

    # Find center joint if multiple children
    #
    # o o o  <-- Which is in the middle?
    #  \|/
    #   o
    #   |
    #
    distances = []
    for pos in positions + [root_pos]:
        distances += [(pos - pos2).length]
    center_index = distances.index(min(distances))
    center_node = (children + (root,))[center_index]

    # Roots typically get this, where e.g.
    #
    #      o  <-- Parent
    #      |
    #      o  <-- Root
    #     / \
    #    o   o  <-- One of them should be the Center Node
    #
    if center_node != root:
        direction = pos2 - root_pos
        orient = direction.to_track_quat("X", "Z")
        center_node_pos = center_node.position()

        de_scale = _get_inverted_scale_matrix(root)
        center_node_pos = de_scale @ center_node_pos
        root_pos = de_scale @ root_pos

        length = (center_node_pos - root_pos).length

    return length, orient


def _interpret_shape(xobj: bpx.BpxType):
    """Translate `shape` into marker shape attributes"""

    bbox = xobj.handle().bound_box
    bbox_x = sorted(b[0] for b in bbox)
    bbox_y = sorted(b[1] for b in bbox)
    bbox_z = sorted(b[2] for b in bbox)

    extents = bpx.Vector((
        bbox_x[-1] - bbox_x[0],
        bbox_y[-1] - bbox_y[0],
        bbox_z[-1] - bbox_z[0],
    ))
    center = 0.125 * sum(
        (bpx.Vector(b) for b in bbox), bpx.Vector((0, 0, 0))
    )  # 0.125 = 1 / 8

    extents_avg = sum(extents.xyz) / 3
    is_bbox_cubic = all(
        abs(v - extents_avg) < bpx.LinearTolerance for v in extents.xyz
    )

    # Account for flat shapes, like a circle
    radius = extents.x
    length = max(extents.y, extents.x)

    # Account for X not necessarily being
    # represented by the width of the bounding box.
    if radius < bpx.LinearTolerance:
        radius = length * 0.5

    geo = Geometry()
    geo.offset = center
    geo.extents = extents
    geo.radius = radius * 0.5
    geo.length = length

    # Could be an e.g. `Camera`
    data = xobj.handle().data
    if hasattr(data, "vertices"):
        geo.type = constants.MeshShape  # Guilty until proven innocent
        vert_count = len(data.vertices)

        if vert_count == 8 and is_bbox_cubic:
            # Call it a cube
            geo.type = constants.BoxShape

        elif vert_count > 40:
            # Take sample vertices and compute their distance to the center,
            #   then if all equal, this shape *might* be a sphere.
            sample_count = 20
            step = vert_count // sample_count

            reference = (data.vertices[0].co - center).length

            for i in range(1, sample_count):
                i *= step
                dist = (data.vertices[i].co - center).length

                if abs(dist - reference) >= bpx.LinearTolerance:
                    break
            else:
                if is_bbox_cubic and not data.name.startswith("Cylinder"):
                    geo.type = constants.SphereShape

    # In case of a zero-sized data
    if geo.radius < 0.001:
        geo.radius = 1
        geo.extents = bpx.Vector((1, 1, 1))

    return geo


def _hierarchy_bounding_size(root: bpx.BpxObject):
    """Bounding size taking immediate children into account

            _________
         o |    a    |
    ---o-|-o----o----o--
         | |_________|
         |      |
        o-o    bbox of a
        | |
        | |
        o o
        | |
        | |
       -o o-

    DagNode.boundingBox on the other hand takes an entire
    hierarchy into account.

    """

    pos1 = root.position()
    positions = [pos1]

    # Start by figuring out a center point
    for child in root.children():
        positions += [child.position()]

    # There were no children, consider the parent instead
    if len(positions) < 2:

        # It's possible the immediate parent is an empty
        # group without translation. We can't use that, so
        # instead walk the hierarchy until you find the first
        # parent with some usable translation to it.
        for parent in root.lineage():
            pos2 = parent.position()

            if bpx.is_equivalent(pos2, pos1):
                continue

            # The parent will be facing in the opposite direction
            # of what we want, so let's invert that.
            pos2 -= pos1
            pos2 *= -1
            pos2 += pos1

            positions += [pos2]

            break

    # There were neither parent nor children,
    # we don't have a lot of options here.
    if len(positions) < 2:
        return (
            # No size
            bpx.Vector((0, 0, 0)),

            # Original center
            pos1
        )

    center = bpx.Vector((0, 0, 0))
    for pos in positions:
        center += pos
    center /= len(positions)

    # Then figure out a bounding box, relative this center
    min_ = bpx.Vector((0, 0, 0))
    max_ = bpx.Vector((0, 0, 0))

    for pos2 in positions:
        dist = pos2 - center

        min_.x = min(min_.x, dist.x)
        min_.y = min(min_.y, dist.y)
        min_.z = min(min_.z, dist.z)

        max_.x = max(max_.x, dist.x)
        max_.y = max(max_.y, dist.y)
        max_.z = max(max_.z, dist.z)

    size = [
        max_.x - min_.x,
        max_.y - min_.y,
        max_.z - min_.z,
    ]

    # Keep the smallest value within some sensible range
    minimum = size.index(min(size))
    size[minimum] = max(size) * 0.5

    return bpx.Vector(size), center


def random_color():
    """Return a nice random color"""

    # Rather than any old color, limit colors to
    # the first 250 degress, out of 360 total
    # These all fall into a nice pastel-scheme
    # that fits with the overall look of Ragdoll
    hue = int(random.random() * 250) / 360

    value = 0.7
    saturation = 0.7

    rgb = colorsys.hsv_to_rgb(hue, saturation, value)
    color = bpx.Color(rgb)

    return color


def reset_constraint_frames(marker: bpx.BpxType, symmetrical=True):
    parent_marker = marker["parentMarker"].read()

    if parent_marker:
        parent_marker = bpx.BpxObject(parent_marker)
        parent = parent_marker["sourceTransform"].read()
        parent_matrix = parent.matrix()
    else:
        # It's connected to the world
        parent_matrix = bpx.Matrix.Identity(4)

    child = marker["sourceTransform"].read()
    child_matrix = child.matrix()
    child_frame = bpx.Matrix.Identity(4)

    # Reuse the shape offset to determine
    # the direction in which each axis is facing.
    main_axis = marker["shapeOffset"].read()

    # The offset isn't necessarily only in one axis, it may have
    # small values in each axis. The largest axis is the one that
    # we are most likely interested in.
    main_axis_abs = [
        abs(main_axis.x),
        abs(main_axis.y),
        abs(main_axis.z),
    ]

    largest_index = main_axis_abs.index(max(main_axis_abs))
    largest_axis = bpx.Vector((0, 0, 0))
    largest_axis[largest_index] = main_axis[largest_index]

    x_axis = bpx.Vector((1, 0, 0))
    y_axis = bpx.Vector((0, 1, 0))
    z_axis = bpx.Vector((0, 0, 1))

    if any(axis < 0 for axis in largest_axis):
        if largest_axis.x < 0:
            flip = bpx.Quaternion(y_axis, bpx.pi)

        elif largest_axis.y < 0:
            flip = bpx.Quaternion(x_axis, bpx.pi)

        else:
            flip = bpx.Quaternion(x_axis, bpx.pi)

        if symmetrical and largest_axis.x < 0:
            flip = bpx.Quaternion(x_axis, bpx.pi) @ flip

        if symmetrical and largest_axis.y < 0:
            flip = bpx.Quaternion(y_axis, bpx.pi) @ flip

        if symmetrical and largest_axis.z < 0:
            flip = bpx.Quaternion(y_axis, bpx.pi) @ flip

        child_frame = bpx.Matrix.LocRotScale(
            child_frame.to_translation(),
            flip @ child_frame.to_quaternion(),
            child_frame.to_scale(),
        )

    # Align parent matrix to wherever the child matrix is
    parent_frame = parent_matrix.inverted_safe() @ child_matrix @ child_frame

    # Blender always use Y-axis as the primary axis of a joint/bone.
    # But Ragdoll prefers to use the X-axis for twist so here we
    # re-orient constraint frames to align with that.
    re_orient = bpx.Matrix.Rotation(bpx.pi / 2, 4, "Z")

    parent_frame @= re_orient
    child_frame @= re_orient

    marker["limitRange"] = (bpx.pi / 4, bpx.pi / 4, bpx.pi / 4)
    marker["parentFrame"] = parent_frame
    marker["childFrame"] = child_frame
