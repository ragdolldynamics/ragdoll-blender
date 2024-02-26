import ragdollc
import mathutils


# Conversions from Blender -> Ragdoll


def to_rdevent(event):
    return {
        "x": event.mouse_region_x,
        "y": event.mouse_region_y,
        "ctrl": event.ctrl,
        "alt": event.alt,
        "shift": event.shift,
        "button": {
            "LEFTMOUSE": 0,
            "RIGHTMOUSE": 1,
            "MIDDLEMOUSE": 2,
        }.get(event.type, -1),
    }


def to_rdtype(value):
    if isinstance(value, mathutils.Matrix):
        return to_rdmatrix(value)
    elif isinstance(value, mathutils.Vector):
        return to_rdvector(value)
    elif isinstance(value, mathutils.Euler):
        return to_rdeuler(value)
    elif isinstance(value, mathutils.Color):
        return to_rdcolor(value)
    else:
        return value


def to_rdmatrix(matrix: mathutils.Matrix) -> ragdollc.types.Matrix4:
    assert isinstance(matrix, mathutils.Matrix)

    m = ragdollc.types.Matrix4()

    for i in range(4):
        v = matrix[i]

        for j in range(4):
            m[j, i] = v[j]

    return m


def to_rdvector(vector: mathutils.Vector) -> ragdollc.types.Vector3:
    return ragdollc.types.Vector3(vector[0], vector[1], vector[2])


def to_rdpoint(vector: mathutils.Vector) -> ragdollc.types.Point:
    return ragdollc.types.Point(vector[0], vector[1], vector[2], 1.0)


def to_rdcolor(vector: mathutils.Vector) -> ragdollc.types.Color3:
    return ragdollc.types.Color3(vector[0], vector[1], vector[2])


def to_rdeuler(vector: mathutils.Vector) -> ragdollc.types.Euler3:
    return ragdollc.types.Euler3(vector[0], vector[1], vector[2])


# Conversions from Ragdoll -> Blender


def to_bltype(value):
    if isinstance(value, ragdollc.types.Matrix4):
        return to_blmatrix(value)
    elif isinstance(value, ragdollc.types.Vector3):
        return to_blvector(value)
    elif isinstance(value, ragdollc.types.Vector4):
        raise NotImplementedError
    elif isinstance(value, ragdollc.types.Quaternion):
        raise NotImplementedError
    elif isinstance(value, ragdollc.types.Point):
        raise NotImplementedError
    elif isinstance(value, ragdollc.types.Color3):
        raise NotImplementedError
    else:
        return value


def to_blmatrix(matrix: ragdollc.types.Matrix4) -> mathutils.Matrix:
    assert isinstance(matrix, ragdollc.types.Matrix4)

    m = mathutils.Matrix()

    for i in range(4):
        v = matrix[i]

        for j in range(4):
            m[j][i] = v[j]

    return m


def to_blvector(vector: ragdollc.types.Vector3) -> mathutils.Vector:
    assert isinstance(vector, ragdollc.types.Vector3)

    return mathutils.Vector((
        vector.x,
        vector.y,
        vector.z,
    ))


# Utilities


def descale_matrix(matrix):
    loc, rot, sca = matrix.decompose()
    return mathutils.Matrix.LocRotScale(loc, rot, mathutils.Vector((1, 1, 1)))
