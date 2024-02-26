# -*- coding: utf-8 -*-

import os
import sys
import time
import uuid
import typing
import logging
import traceback
import contextlib
import collections
import functools
import ctypes  # For SessionUuid
import itertools
import math

import bpy
import bmesh
import mathutils

# Convenience
bpx = sys.modules[__name__]

# Expose native mathutils types
Vector = mathutils.Vector
Matrix = mathutils.Matrix
Color = mathutils.Color
Euler = mathutils.Euler
Quaternion = mathutils.Quaternion

# Expose native math types
radians = math.radians
degrees = math.degrees
pi = math.pi

e_cube = 2
e_empty = 11

e_mesh_plane = 1
e_mesh_cube = 2
e_mesh_circle = 3
e_mesh_uv_sphere = 4
e_mesh_ico_sphere = 5
e_mesh_cylinder = 6
e_mesh_cone = 7
e_mesh_torus = 8
e_mesh_grid = 9
e_mesh_suzanne = 10

e_empty_plain_axes = 12
e_empty_arrows = 13
e_empty_single_arrow = 14
e_empty_circle = 15
e_empty_cube = 16
e_empty_sphere = 17
e_empty_cone = 18
e_empty_image = 19

e_armature_empty = 20
e_armature_single_bone = 21

# Aliases
Object = bpy.types.Object
PoseBone = bpy.types.PoseBone
Bone = bpy.types.Bone

# Some nifty defaults
LinearTolerance = 0.0001  # i.e. 0.01 cm
AngularTolerance = 0.01


class _Timing:
    def __init__(self):
        self.duration = 0.0
        self.count = 0
        self.max = 0.0
        self.min = 0xffffff


# Developer flags
BPX_DEVELOPER = bool(os.getenv("BPX_DEVELOPER", False))
USE_PROFILING = BPX_DEVELOPER
USE_ORDERED_SELECTION = True

# End-user constants
BLENDER_3 = bpy.app.version[0] == 3
BLENDER_4 = bpy.app.version[0] == 4

#
# Internal state below, do not access internally or externally
#

# Use the experimental session_uuid, only tested in Blender 4.0
# It has better support for file linking and object duplication,
# at the expense of using internals of Blender's source which may change
_USE_SESSION_UUID = True

_SUSPENDED_CALLBACKS = False

# Maintain a list of selected objects and bones, in the order of selection
_ORDERED_SELECTION = []
_LAST_SELECTION = []

# Alternative name for a given BpxType
_ALIASES = {}

# bpx timings, in milliseconds
_TIMINGS = collections.defaultdict(_Timing)

# Internal logger, use `info()` etc.
_LOG = logging.getLogger("bpx")

# Is the file opened in a test environment?
_BACKGROUND = False

# Handle writing to bpxProperties.bpxId from another
# thread or restricted context, such as during rendering
_DEFERRED_BPXIDS = {}

_INSTALLED = False

# Public bpx callbacks
handlers = {

    "selection_changed": [],

    # An object was removed but can be undone
    "object_removed": [],

    # A previously removed object we undone
    "object_unremoved": [],

    # An object is permanently removed
    "object_destroyed": [],

    # An object was created
    "object_created": [],

    # An object was duplicated
    "object_duplicated": [],

    # Something, anything, changed
    "depsgraph_changed": [],

    # The global Blender mode has changed
    "mode_changed": [],
}

# Thrown when accessing a property that does not exist
ExistError = type("ExistError", (RuntimeError,), {})

# Global dirty states, if *anything* has changed since last depsgraph update
DirtyObjectMode = True
DirtyPoseMode = True

ObjectMode = "OBJECT"
PoseMode = "POSE"
SculptMode = "SCULPT"
EditMode = "EDIT"
EditMeshMode = "EDIT_MESH"
EditArmatureMode = "EDIT_ARMATURE"

HierarchyOrder = False
SelectionOrder = True


@contextlib.contextmanager
def timing(name, verbose=False):
    t = _Timing()
    t0 = time.perf_counter()

    try:
        yield t
    finally:
        t1 = time.perf_counter()
        t.duration = (t1 - t0) * 1000

        if verbose:
            info("%s in %.2fms" % (
                name, t.duration
            ))


@contextlib.contextmanager
def cumulative_timing(name):
    timing = _TIMINGS[name]

    try:
        t0 = time.perf_counter()
        yield timing
    finally:
        t1 = time.perf_counter()
        duration = (t1 - t0) * 1000  # milliseconds
        timing.duration += duration
        timing.count += 1

        if duration > timing.max:
            timing.max = duration

        if duration < timing.min:
            timing.min = duration


def with_timing(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()

        try:
            return func(*args, **kwargs)
        finally:
            t1 = time.perf_counter()
            duration = t1 - t0
            info("%s.%s in %.2fms" % (
                func.__module__, func.__name__, duration * 1000
            ))

    return wrapper


def _requires_install(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not _INSTALLED:
            install()
        return func(*args, **kwargs)
    return wrapper


def with_cumulative_timing(func):
    """Aggregate timings for `func` such that the sum may be inspected

    Use this, and then call `report_cumulative_timings()` to view
    the result of a function once called on multiple occasions.

    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()

        try:
            return func(*args, **kwargs)
        finally:
            t1 = time.perf_counter()
            duration = (t1 - t0) * 1000  # milliseconds
            key = func.__module__.rsplit(".", 1)[-1]  # lib.vendor.bpx -> bpx
            key += "." + func.__name__
            timing = _TIMINGS[key]
            timing.duration += duration
            timing.count += 1

            if duration > timing.max:
                timing.max = duration

            if duration < timing.min:
                timing.min = duration

    if USE_PROFILING:
        return wrapper
    else:
        return func


def reset_cumulative_timings():
    """Remove all prior timings"""
    _TIMINGS.clear()


def report_cumulative_timings():
    """Print a table for the user to see what's going on

    E.g.
     ____________________________________________________________________
    | Call                     | Duration  | Count | Min/Max             |
    |--------------------------|-----------|-------|---------------------|
    | _is_valid                |   0.00 ms |    34 | 0.00 < 1.24 ms/call |
    | ls                       |  36.98 ms |   689 | 0.05 < 1.24 ms/call |
    | flush_attribute_sets     |   0.00 ms |   686 | 0.00 < 1.24 ms/call |
    | _post_depsgraph_changed  |   1.00 ms |    20 | 0.05 < 1.24 ms/call |
    |__________________________|___________|_______|_____________________|

    """

    if not USE_PROFILING:
        return

    timings = sorted(_TIMINGS.items(),
                     key=lambda item: item[1].duration,
                     reverse=True)

    msg = []

    longest_function_call = 1
    for func, timing in timings:
        if len(func) > longest_function_call:
            longest_function_call = len(func)

    template = "| {:%s} | {:>9.2f} ms | {:>7} | {:>5.3f} < {:<7.2f} ms |" % (
        longest_function_call + 1,
    )

    msg.append("Cumulative Timings Report")

    # Top line
    msg.append(" " + ("_" * (len(template.format("", 0, 0, 0, 0)) - 2)) + " ")

    # Header
    header = "| Call  " + " " * (longest_function_call - len("Call"))
    header += "| Total        | Count   | Per call           |"

    msg.append(header)

    footer = "|--" + "-" * longest_function_call
    footer += "-|--------------|---------|--------------------|"
    msg.append(footer)

    for func, timing in timings:
        msg.append(template.format(
            func,
            timing.duration,
            timing.count,
            timing.min,
            timing.max
        ))

    footer = "|__" + "_" * longest_function_call
    footer += "_|______________|_________|____________________|"

    msg.append(footer)
    msg = "\n".join(msg)

    info(msg)

    return msg


class Timing:
    def __init__(self):
        self._t0 = time.perf_counter()

    @property
    def s(self):
        return self._seconds

    @property
    def ms(self):
        return self._seconds * 1000

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, tb):
        t1 = time.perf_counter()
        self._seconds = t1 - self._t0


@contextlib.contextmanager
def maintained_time(context):
    """Maintain time whilst manipulating the scene"""

    initial_frame = context.scene.frame_current

    try:
        yield

    finally:
        context.scene.frame_set(initial_frame)


@contextlib.contextmanager
def suspension():
    global _SUSPENDED_CALLBACKS
    _SUSPENDED_CALLBACKS = True
    bpy.app.handlers.depsgraph_update_post.remove(_post_depsgraph_changed)

    try:
        yield
    finally:
        _SUSPENDED_CALLBACKS = False
        bpy.app.handlers.depsgraph_update_post.append(_post_depsgraph_changed)


def with_suspension(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with suspension():
            return func(*args, **kwargs)

    return wrapper


def with_tripwire(func):
    """Prevent `func` from throwing a recurring exception

    Because many things in bpx are cached, an error is likely to repeat
    itself using previously cached data. Therefore, this decorator
    breaks the cache on any exception, thus preventing this kind of error

    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            _clear_all_caches()
            traceback.print_exc()

    return wrapper


def debug(msg):
    _LOG.debug(msg)


def info(msg):
    _LOG.info(msg)


def warning(msg):
    _LOG.warning(msg)


@contextlib.contextmanager
def maintained_selection(context=None):
    """Maintain selection whilst manipulating the scene"""

    context = context or bpy.context
    active_object = context.active_object
    selected_objects = context.selected_objects

    if active_object:
        previous_mode = active_object.mode
    else:
        previous_mode = ObjectMode

    try:
        yield

    finally:
        if not active_object:
            return bpy.ops.object.select_all(action="DESELECT")

        context.view_layer.objects.active = active_object

        if previous_mode == PoseMode:
            bpy.ops.object.mode_set(mode=PoseMode)

        if previous_mode == ObjectMode and selected_objects:
            bpy.ops.object.mode_set(mode=ObjectMode)
            bpy.ops.object.select_all(action="DESELECT")
            for obj in selected_objects:

                try:
                    obj.select_set(True)
                except ReferenceError:
                    # May have been deleted
                    pass


def _persistent(func):
    """Ensure that `func` has a valid underlying Python object

    Blender invalidates references to datablocks like objects during
    undo, redo and file-open.

    """

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if self._dirty and not self._destroyed:
            _restore(self)

        return func(self, *args, **kwargs)

    return wrapper


class ObjectHandle:
    def __init__(self, obj):
        self._obj = obj
        self._valid = True

    def __getattribute__(self, name):
        if not self._valid:
            raise ExistError("%s no longer exists" % self)

        try:
            return getattr(self._obj, name)
        except Exception:
            self._valid = False
            raise


class SingletonProperty(type):
    def __call__(cls, xobj, name, *args, **kwargs):
        assert isinstance(xobj, BpxType)

        # Properties are unique per {object, name}
        key = (hash(xobj), name)

        index = None

        # Handle `myAttrY` etc, but avoid `myAttrXYZ`
        if not name.endswith("XYZ"):
            if name.endswith("X"):
                name = name[:-1]
                index = 0

            if name.endswith("Y"):
                name = name[:-1]
                index = 1

            if name.endswith("Z"):
                name = name[:-1]
                index = 2

            if name.endswith("W"):
                name = name[:-1]
                index = 3

        if kwargs.get("exists", True):
            try:
                prop = xobj._cached_properties[key]

            except KeyError:
                pass

            except AssertionError:
                # He's dead Jim
                xobj._cached_properties.pop(key)

            else:
                return prop

        group = xobj.property_group()

        try:
            prop = getattr(group, name)
        except AttributeError:
            raise ExistError("%s.%s did not exist" % (xobj, name))

        if hasattr(prop, "add"):
            sup = BpxCollectionProperty
        else:
            sup = BpxProperty

        self = super(SingletonProperty, sup).__call__(
            xobj, name, index, *args, **kwargs
        )
        xobj._cached_properties[key] = self

        return self


class InvalidObject:
    def __getattribute__(self, name):
        raise ReferenceError("%s cannot be accessed" % name)


class SingletonType(type):
    """Re-use previous instances of Blender object

    This enables persistent state of each object, even when
    a object is discovered at a later time, such as via
    :func:`Object.parent()` or :func:`Object.descendents()`

    Arguments:
        object (bpy.types.Object): Blender API object to wrap
        exists (bool, optional): Whether or not to search for
            an existing Python instance of this node

    Examples:
        >>> new()
        >>> a = create_object(e_empty_cube, name="myCube")
        >>> BpxType("myCube") is a
        True
        >>> a.handle().location[0]
        0.0
        >>> a.handle().location[0] = 1.0
        >>> a.handle().location[0]
        1.0

    """

    _key_to_instance = {}
    _instance_to_key = {}

    def __call__(cls, object, **kwargs):
        # Called with an existing BpxType instance
        # E.g. BpxObject(xobj)
        if isinstance(object, BpxType):
            return object

        # Called with the intent to convert a string to BpxType
        # E.g. BpxObject("Cube.001")
        if isinstance(object, str):
            obj = bpy.context.scene.objects.get(object, None)

            if obj is not None:
                object = obj
            else:
                raise ValueError("%s not found" % object)

        supported_types = (
            bpy.types.Object,
            bpy.types.Bone,

            # Implicitly converted to Bone
            bpy.types.PoseBone,
        )

        assert isinstance(object, supported_types), (
            "%s was not an object nor pose bone" % object
        )

        # Object references are not persistent during undo
        # so instead we create a new, persistent, identifier
        key = _get_uuid(object)

        if kwargs.get("exists", True):
            try:
                node = cls._key_to_instance[key]

            except KeyError:
                pass

            # TODO: How can this happen?
            except AssertionError:
                # He's dead Jim
                cls._key_to_instance.pop(key)
                cls._instance_to_key.pop(node)

            else:
                return node

        # It hasn't been instantiated before, let's do that.
        # But first, make sure we instantiate the right type
        if isinstance(object, bpy.types.Bone):
            sup = BpxBone
        elif isinstance(object, bpy.types.PoseBone):
            sup = BpxBone
        elif isinstance(object.data, bpy.types.Armature):
            sup = BpxArmature
        elif isinstance(object, bpy.types.Object):
            sup = BpxObject
        else:
            raise TypeError("Unsupported type: %r(%s)" % (
                object, type(object))
            )

        self = super(SingletonType, sup).__call__(object)
        cls._key_to_instance[key] = self
        cls._instance_to_key[self] = key

        for handler in handlers["object_created"]:
            try:
                handler(self)
            except Exception:
                traceback.print_exc()

        return self

    @classmethod
    def invalidate(cls):
        for xobj in cls._instance_to_key:
            xobj._handle = InvalidObject()

    @classmethod
    def destroy_all(cls):
        for xobj in cls._instance_to_key.copy():
            _destroy(xobj)


class BpxProperty(metaclass=SingletonProperty):
    def __init__(self, xobj, name, index=None):
        assert isinstance(xobj, BpxType), "%s was not a BpxType" % xobj

        self._xobj = xobj
        self._name = name
        self._index = index

        # Track dirty state and only return last up-to-date value
        self._dirty = True
        self._last_value = None

        # Blender doesn't store the indices of enums,
        # nor does it return the index when queried.
        # -> bpx always returns indices.
        self._enum_to_index = None
        self._index_to_enum = None
        self._is_enum = False

        group = xobj.property_group()
        typ = group.bl_rna.properties[self._name]

        if isinstance(typ, bpy.types.EnumProperty):
            self._enum_to_index = {
                enum.name: enum.value
                for enum in typ.enum_items
            }
            self._index_to_enum = {
                enum.value: enum.name
                for enum in typ.enum_items
            }
            self._is_enum = True

        # Determine whether this property is driven or not
        self._driven = False

        # Determine whether property is driven
        handle = xobj._handle
        anim = handle.animation_data

        if anim:
            action = handle.animation_data.action
            kwargs = {}

            if index is not None:
                kwargs = {"index": index}

            curve_name = "%s.%s" % (group.type, name)
            if action.fcurves.find(curve_name, **kwargs) is not None:
                self._driven = True

            elif anim.drivers:
                for fcurve in anim.drivers:
                    if fcurve.data_path != fcurve:
                        continue

                    if fcurve.array_index != index:
                        continue

                    self._driven = True
                    break

    def __str__(self):
        return str(self.read())

    def __repr__(self):
        return "bpx.BpxProperty(%s=%s)" % (self._name, self.read())

    def __getitem__(self, name):
        # Index into a e.g. Vector
        if isinstance(name, int):
            value = self.read()[name]
        else:
            value = getattr(self.read(), name)

        return value

    def __setitem__(self, name, value):
        group = self._xobj.property_group()
        prop = getattr(group, self._name)

        if isinstance(name, int):
            prop[name] = value
        else:
            setattr(prop, name, value)

        self.post_process()

    def dirty(self):
        self._dirty = True

    def clean(self):
        self._dirty = False

    def is_driven(self):
        return self._driven

    def touch(self):
        """Trigger any update callbacks without changing its value"""
        value = self.read()

        # Was the property a PointerProperty?
        if isinstance(value, BpxObject):
            value = {"object": value}

        self.write(value)

    def post_process(self):
        group = self._xobj.property_group()
        Type = group.bl_rna.properties[self._name]

        # Create a reverse relationship between pointer and pointee#
        # Such that you can query the object carrying the pointer,
        # and also the object for whom it is pointing to.
        if isinstance(Type, bpy.types.PointerProperty):
            other = self.read()

            if isinstance(other, bpy.types.Object):
                xother = BpxType(other)
                xother._output_connections[self._name] = self._xobj

    def write(self, value):
        """Write `value` to property

        This method converts indices to enums automatically,
        along with dictionaries to property groups.

        Examples:
            obj = create_object()

        """

        group = self._xobj.property_group()
        assert hasattr(group, self._name), (
            "'%s.%s' did not exist" % (group, self._name)
        )

        if self._is_enum and isinstance(value, int):
            value = self._index_to_enum[value]

        # Support for setting pointer properties
        if isinstance(value, BpxObject):
            value = value.handle()

        elif isinstance(value, BpxBone):
            value = value.bone()

        if isinstance(value, dict):
            for key, value in value.items():
                if isinstance(value, BpxType):
                    value = value.handle()

                ptr = getattr(group, self._name)
                setattr(ptr, key, value)
        else:
            if self._index is not None:
                self[self._index] = value
            else:
                setattr(group, self._name, value)

    @with_cumulative_timing
    def read(self, animated=True):
        """Read this property, or return latest cached

        Reading properties is expensive, so unless the property is
        marked "dirty" it won't ask Blender for an updated value.
        Instead it will output the last computed value.

        Update heuristic:
            1. A property is dirty, update
            2. A property is driven, update

        Arguments:
            animated (bool, optional): Whether to forcibly read this property
                even when not driven and not dirty

        """

        if animated or self._dirty or self._driven:
            self.update()

        return self._last_value

    @with_cumulative_timing
    def update(self):
        """Store value of Blender property in _last_value

        This works alongside `_dirty` to ensure performance is up to snuff

        """

        group = self._xobj.property_group()
        value = getattr(group, self._name)

        if self._is_enum:
            value = self._enum_to_index[value]

        if self._index is not None:
            value = value[self._index]

        # Is this a { armature: boneid } pair?
        if isinstance(value, bpy.types.PropertyGroup):
            pg = value

            if hasattr(value, "object") and hasattr(value, "boneidx"):
                obj = pg.object
                is_armature = obj and isinstance(obj.data, bpy.types.Armature)

                value = None
                xobj = None

                if is_armature:
                    bone = None
                    if pg.boneidx is not None:
                        bone = find_bone_by_index(obj, pg.boneidx)

                    if bone is None and pg.boneid is not None:
                        bone = find_bone_by_uuid(obj, pg.boneid)

                        # Re-compute boneidx for next time
                        if bone is not None:
                            pg.boneidx = BpxBone(bone).boneidx(cached=False)

                    if bone is not None:
                        xobj = BpxBone(bone)

                elif isinstance(obj, bpy.types.Object):
                    xobj = BpxObject(obj)

                if xobj and xobj.is_alive():
                    value = xobj

        # Was the property a PointerProperty?
        if isinstance(value, bpy.types.Object):
            value = BpxType(value)

        self._dirty = False

        previous = self._xobj._previous_values.get(self._name)
        self._changed = str(value) != previous

        # Since the BpxProperty is destroyed on undo, we can't
        # store history here. But we *can* store it in the object.
        self._xobj._previous_values[self._name] = str(value)

        self._last_value = value

    def changed(self):
        """Return whether the value of this property has changed

        This is different from being dirty, since an attribute can change
        to the same value as earlier, and can also be manually dirtied in
        which case the value will not have changed.

        """

        # In order to know whether it has changed, we first need to read it.
        self.read()

        return self._changed

    def enum(self, converter=None):
        assert self._is_enum, "%s was not an enum" % self
        group = self._xobj.property_group()
        value = getattr(group, self._name)

        if converter:
            value = getattr(converter, value)

        return value


class BpxCollectionProperty(BpxProperty):
    def __len__(self):
        return len(self.read())

    def clear(self):
        """Remove all items from collection"""
        pg = self.read()
        while len(pg) > 0:
            pg.remove(len(pg) - 1)

    def append(self, default=None):
        item = self.read().add()

        if isinstance(default, dict):
            for key, value in default.items():
                assert hasattr(item, key), "%s did not have '%s'" % (item, key)
                setattr(item, key, value)

        return item

    def pop(self, default=None):
        pg = self.read()
        last = len(pg) - 1
        if last < 0:
            raise ValueError("Empty collection")

        pg.remove(last)

    def exists(self, query):
        try:
            self.index(query)
        except IndexError:
            return False
        else:
            return True

    def index(self, query):
        """Find collection item by matching its property values

        Arguments:
            query (str | dict): Item name, or a dict for matching item
                with key-value.

        Returns:
            int: Index of found item.

        Raises:
            IndexError: If not found.
            TypeError: If `query` is not a str nor dict.

        """

        if isinstance(query, str):
            return self._index_by_name(query)
        elif isinstance(query, dict):
            return self._index_from_dict(query)
        else:
            raise TypeError("%s was not str or dict" % query)

    def _index_from_dict(self, match: dict) -> int:
        """Find collection item by matching its property values

        Arguments:
            match: A dict for matching item with key-value.

        Returns:
            int: Index of found item.

        Raises:
            IndexError: If not found.

        """

        property_group = self.read()

        def is_match(it):
            for key, value in match.items():
                if getattr(it, key) != value:
                    return False
            return True

        for i, item in enumerate(property_group):
            try:
                if is_match(item):
                    return i
            except AttributeError:
                # Collection must be containing same type of property group,
                # therefore it is meaningless to continue if attr missing.
                break

        raise IndexError("%s was not found in %s" % (match, self))

    def _index_from_name(self, name: str) -> int:
        """Find collection item by its name

        Arguments:
            name: Item name.

        Returns:
            int: Index of found item.

        Raises:
            IndexError: If not found.

        """

        property_group = self.read()
        index = property_group.find(name)

        if index < 0:
            raise IndexError("%s not found in %s" % (name, self))

        return index

    def remove(self, index):
        """Uses undocumented method of CollectionProperty

        Raises:
            IndexError: if not found

        """

        pg = self.read()
        if index >= len(pg) or index < 0:
            raise IndexError("Index out of range.")

        pg.remove(index)


# Interface for underlying C struct
# https://github.com/blender/blender/blob/9c0bffcc89f174f160805de042b00ae7c201c40b/source/blender/makesdna/DNA_ID.h#L441
#
# NOTE: The order and type of members must match that of the struct.
#       At least up until the member we want, i.e. session_uuid
#       The below was derived from Blender 4.0
#
_PLACEHOLDER = type("_PLACEHOLDER", (ctypes.Structure,), {})

_ID = type("_ID", (ctypes.Structure,), {
    "_fields_": [
        ("next", ctypes.c_void_p),
        ("prev", ctypes.c_void_p),
        ("newid", ctypes.POINTER(_PLACEHOLDER)),
        ("lib", ctypes.POINTER(_PLACEHOLDER)),
        ("asset_data", ctypes.POINTER(_PLACEHOLDER)),
        ("name", ctypes.c_char * 66),
        ("flag", ctypes.c_short),
        ("tag", ctypes.c_int),
        ("us", ctypes.c_int),
        ("icon_id", ctypes.c_int),
        ("recalc", ctypes.c_uint),
        ("recalc_up_to_undo_push", ctypes.c_uint),
        ("recalc_after_undo_push", ctypes.c_uint),
        ("session_uuid", ctypes.c_uint),  # This is it.
    ]
})

# https://github.com/blender/blender/blob/9c0bffcc89f174f160805de042b00ae7c201c40b/source/blender/makesdna/DNA_ID.h#L530
_LIBRARY = type("_LIBRARY", (ctypes.Structure,), {
    "_fields_": [("id", _ID)]
})


class SessionUuid:
    """Interface to Blender's internal unique `session_uuid`

    Reference:
        - https://projects.blender.org/blender/blender/src/commit/4b47b46f9c8ff16dcfae5fcd1c07520b4dd32650/source/blender/makesdna/DNA_ID.h#L496

    """

    @classmethod
    def get(cls, obj):
        if isinstance(obj, bpy.types.Bone):
            return cls._get_from_bone(obj)

        elif isinstance(obj, bpy.types.Object):
            return cls._get_from_object(obj)

        else:
            raise TypeError("%s was not a Object or Bone" % obj)

    @classmethod
    def _get_from_object(cls, obj):
        """Get the session_uuid for a Blender-native `obj`"""
        ptr = obj.as_pointer()
        ptr = ctypes.cast(ptr, ctypes.POINTER(_LIBRARY))

        # If this isn't working, our understanding of the Blender source
        # code is incomplete, or the version of Blender is different enough
        # from when this was written.
        assert ptr, "%s could not cast, this is a bug" % obj

        return ptr.contents.id.session_uuid

    @classmethod
    def _get_from_bone(cls, bone):
        """Get pair of {session_uui, boneid}

        Blender does not provide a session_uuid for bones (correct m
        if I'm wrong) and so instead we consider a combination of
        a unique object uuid + a bespoke bpxId as their session_id.

        """

        if not _bpxid(bone):
            _make_bpxid(bone)

        armature = bone.id_data
        assert isinstance(armature, bpy.types.Armature)

        for obj in bpy.data.objects:
            if not isinstance(obj.data, bpy.types.Armature):
                continue

            if obj.data is armature:
                break

        else:
            raise ValueError(
                "Object for armature data '%s' did not exist, this is a bug"
                % armature
            )

        uuid = cls._get_from_object(obj)
        return (uuid, bone.bpxProperties.bpxId)


@with_cumulative_timing
def _get_uuid(obj):
    """Get a unique ID for `obj`

    The ID is persistent across undo and does not
    repeat when duplicating an object.

    """

    assert isinstance(obj, (bpy.types.Object,
                            bpy.types.Bone,
                            bpy.types.PoseBone)), (
        "%s was not an Object or Bone" % obj)

    if isinstance(obj, bpy.types.PoseBone):
        obj = obj.bone

    if _USE_SESSION_UUID:
        return SessionUuid.get(obj)

    if not _bpxid(obj):
        _make_bpxid(obj)

    return _bpxid(obj)


class BpxType(metaclass=SingletonType):
    def __init__(self, object: bpy.types.Object, **kwargs):
        self._uuid = _get_uuid(object)
        self._handle = object

        # Is the reference potentially invalidated?
        self._dirty = False

        # Has this object been permanently destroyed?
        self._destroyed = False

        # Has this object been temporarily removed, but may be undone?
        self._removed = False

        self._last_name = object.name_full

        # For change-monitoring in contained BpxProperty instances
        # We can't store these in BpxProperty itself, as they are
        # destroyed when this type is dirtied.
        self._previous_values = {}

        # Remember property group, this won't change
        self._property_group = None

        # Cached value, for performance
        self._bpxtype = None

        # Transient metadata for this object
        self._metadata = {}

        # Track objects this object connects to
        self._output_connections = collections.defaultdict(dict)

        # Properties of this instance are cached and reused here
        self._cached_properties = {}

        assert isinstance(object, bpy.types.Object), (
            "%s(%r) was not bpy.types.Object" % (object, object)
        )

    def __hash__(self):
        return int(self._uuid)

    def __str__(self):
        return self._last_name

    def __repr__(self):
        name = self.__class__.__name__

        if self._removed or self._destroyed or self._handle is None:
            name += "<removed>"

        return "bpx.%s('%s')" % (
            name, self._last_name
        )

    @_persistent
    def property_group(self) -> bpy.types.PropertyGroup:
        assert self.is_valid(), "%s was dead" % self

        if self._property_group is None:
            try:
                group = getattr(self._handle, self.type())

            except (KeyError, AttributeError):
                # The user must provide a bpxType in order to use `["attr"]`
                raise ExistError("No property group for %s" % self)

            else:
                self._property_group = group

        return self._property_group

    @_persistent
    def __getitem__(self, name):
        """Get property from the property group associated with this bpxType

        Supports accessing indices as `["attrX"]` in addition to `["attr"][0]

        Raises:
            bpx.ExistError: If no bpxType property group, or `name` does not
                exist in property group.

        """

        return BpxProperty(self, name)

    @_persistent
    def __setitem__(self, name, value):
        xprop = self[name]
        xprop.write(value)

    def alias(self, key):
        return self._metadata.get(key)

    @_persistent
    def attr(self, name):
        return self._handle[name]

    def type(self):
        # Cache for performance, this can never change
        if not self._bpxtype and self.is_valid():
            self._bpxtype = _bpxtype(self._handle)

        return self._bpxtype

    @property
    def data(self):
        """Transient metadata associated with the object

        Store data that disappears alongside the object,
        stored exclusively in memory and incurs zero overhead
        from setting and writing.

        """

        return self._metadata

    @_persistent
    def visible(self):
        """Is the object visible?

        Taking all visibility flags into account, this value
        represents the final value of whether an object is visible

        """

        # It may have been removed or destroyed
        if not self.is_alive() or not self.is_valid():
            return False

        # Linked objects are always visible
        if self._handle.library is not None:
            return True

        return self._handle.visible_get()

    @_persistent
    def name(self):
        """Return last known name of self"""

        # When an object has been removed or destroyed,
        # we cannot query the name for it. So, let's remember
        # the last name it had, such that we can still print it
        # once destroyed. For easier debugging.
        if self.is_alive() and self.is_valid():
            self._last_name = self._handle.name_full

        return self._last_name

    def path(self):
        """Return name including all parents, separated by forward slash"""
        names = [self.name()]
        current = self.parent()

        while current:
            names.append(current.name())
            current = self.parent()

        return "/".join(names.reversed())

    @_persistent
    def lineage(self):
        """Recursively yield each parent until the root"""
        current = self._handle

        while current.parent:
            yield BpxObject(current)
            current = current.parent

    @_persistent
    def collections(self):
        """Return collection(s) containing this object"""
        return self._handle.users_collection

    @_persistent
    def parent(self):
        parent = self._handle.parent
        if parent is not None:
            return BpxObject(parent)

    @_persistent
    def children(self):
        for child in self._handle.children:
            yield BpxObject(child)

    @_persistent
    @with_cumulative_timing
    def matrix(self, world=True):
        if world:
            return self._handle.matrix_world
        else:
            return self._handle.matrix

    @_persistent
    def position(self, world=True) -> Vector:
        """Return the position of this object"""
        if world:
            return self.matrix().to_translation()
        else:
            return self._handle.location

    @_persistent
    def orientation(self, world=True) -> Quaternion:
        """Return the orientation of this object"""
        if world:
            return self.matrix().to_quaternion()
        else:
            return self._handle.location

    def is_dirty(self):
        return self._dirty

    def dirty(self):
        """Indicate that this object may need its reference restored"""
        self._dirty = True

    def clean(self):
        self._dirty = False

    def rearrange(self):
        """Indicate that this object has changed its hierarchy location"""
        pass

    @_persistent
    def handle(self, safe=False):
        """Retrieve a bpy.types.Object instance

        Arguments:
            safe (bool): Whether to guarantee a valid instance

        """

        return self._handle

    def key(self):
        return self._uuid

    @_persistent
    def unlocked_location(self):
        for axis in range(3):
            if not self._handle.lock_location[axis]:
                yield axis

    @_persistent
    def unlocked_rotation(self):
        for axis in range(3):
            if not self._handle.lock_rotation[axis]:
                yield axis

    @_persistent
    def is_valid(self):
        return not self._destroyed

    @_persistent
    def is_alive(self):
        return not self._removed


@with_cumulative_timing
def _is_valid(xobj):
    """Is reference to object accessible in memory"""
    if not isinstance(xobj, BpxType):
        debug("Not valid, beause it's not a BpxType")
        return False

    if xobj._destroyed:
        debug("Not valid, beause it's destroyed")
        return False

    if xobj._handle is None:
        debug("Not valid, beause it has no handle")
        return False

    valid = is_object_valid(xobj._handle)

    # An object can be valid, but not be present in the active scene
    if not valid:
        debug("Not valid, beause bad %s" % xobj._handle)
        return False

    # Blender allows access to objects via bpy.data.objects[""]
    # but since a linked file may contain an object of the same name,
    # this is no good.
    #
    # Therefore, we need to explicitly iterate over all objects and compare
    # against their bpxId to they are valid
    #
    # TODO: Optimise this
    if len(bpy.data.libraries):
        for obj in bpy.data.objects:
            if _get_uuid(obj) == xobj._uuid:
                return True

        # Didn't exist? Then it's invalid
        return False

    # No linked libraries? Then there are no remaining indications
    # that this xobj is not valid.
    else:
        return True


@with_cumulative_timing
def _restore(xobj):
    assert isinstance(xobj, BpxType), (
        "%s was not BpxType" % xobj._last_name
    )

    # This is lazily re-computed upon request
    xobj._property_group = None

    # No matter what happens, we've handled it
    xobj._dirty = False

    # These can no longer be trusted
    xobj._cached_properties.clear()

    if isinstance(xobj, BpxBone):
        xobj._bone = None
        xobj._pose_bone = None

    xobj._handle = find_object_by_uuid(xobj._uuid)

    if not xobj._handle:
        _remove(xobj)
        return False

    if isinstance(xobj, BpxBone):
        armature = xobj._handle

        # Try the fast route first
        xobj._bone = find_bone_by_index(armature, xobj._boneidx)

        # Try the slow route
        if not xobj._bone:
            xobj._bone = find_bone_by_uuid(armature, xobj._boneid)

        if not xobj._bone:
            _remove(xobj)
            return False

        # Also restore pose bone, for `matrix()`
        xobj._pose_bone = armature.pose.bones[xobj._bone.name]

    # If we made it this far and the object was previously removed,
    # it has been recreated via undo.
    if xobj._removed:
        _unremove(xobj)

    if not _is_valid(xobj):
        _destroy(xobj)
        return False

    return True


class BpxObject(BpxType):
    pass


class BpxArmature(BpxObject):
    """An object of type bpy.types.Armature

    Example:
        >>> new()
        >>> obj = create_object(e_armature_empty)
        >>> isinstance(obj, BpxArmature)
        True

    """


class BpxBone(BpxType):
    """An armature and bone reference rolled into one

    Example:
        >>> new()
        >>> arm = create_object(e_armature_empty)

        >>> with edit_mode(arm):
        ...    with Chain() as c:
        ...        _ = c.add("hip", (0, 0, 1))
        ...        _ = c.add("torso", (0, 0, 2))
        ...
        >>> bone = arm.handle().data.bones["hip"]
        >>> bone = BpxBone(bone)
        >>> bone.name()
        'hip'

    """

    def __init__(self, bone, *args, **kwargs):
        if isinstance(bone, bpy.types.PoseBone):
            pose_bone = bone
            bone = bone.bone

            # This is the object
            armature = pose_bone.id_data

        # The id_data of an edit bone is the bpy.types.Armature, not the object
        elif isinstance(bone, bpy.types.EditBone):
            armature = bpy.data.objects[bone.id_data.name]
            pose_bone = armature.pose.bones[bone.name]
            bone = bone.id_data.bones[bone.name]

        elif isinstance(bone, bpy.types.Bone):
            # The name of the types.Armature and of the corresponding
            # object can differ, e.g. Armature -> Armature.001
            # Thus, we need to iterate over all possible objects to
            # find which one carries the Armature.
            armature = next(
                obj for obj in bpy.data.objects
                if isinstance(obj.data, bpy.types.Armature)
                and obj.data is bone.id_data
            )
            pose_bone = armature.pose.bones[bone.name]

        else:
            raise TypeError(
                "%s was not a Bone, EditBone or PoseBone" % bone
            )

        assert isinstance(armature.data, bpy.types.Armature)
        super(BpxBone, self).__init__(armature, *args, **kwargs)

        self._bone = pose_bone.bone
        self._pose_bone = pose_bone
        self._last_name = bone.name

        assert isinstance(self._bone, bpy.types.Bone), (
            "%s was not a Bone" % self._bone)
        assert isinstance(self._pose_bone, bpy.types.PoseBone), (
            "%s was not a PoseBone" % self._pose_bone)

        # To rediscover bone if invalidated
        self._boneid = _bpxid(bone)
        self._boneidx = armature.data.bones.keys().index(self._last_name)

    def __hash__(self):
        return int(self._boneid)

    def boneid(self) -> str:
        return self._boneid

    @_persistent
    def boneidx(self, cached=True) -> int:
        if self._boneidx is None or not cached:
            armature = self._handle.data
            bones = armature.bones.keys()
            self._boneidx = bones.index(self.name())

        return self._boneidx

    def rearrange(self):
        """Indicate that this object has changed its location in hierarchy"""
        self._boneidx = None

    @_persistent
    def name(self) -> str:
        if self.is_alive() and self.is_valid():
            self._last_name = self.bone().name
        return self._last_name

    def type(self):
        # Cache for performance, this can never change
        if not self._bpxtype and self.is_valid():
            self._bpxtype = _bpxtype(self._bone)

        return self._bpxtype

    @_persistent
    def visible(self):
        return super().visible() and not self._bone.hide

    @_persistent
    def bone(self) -> bpy.types.Bone:
        return self._bone

    @_persistent
    def pose_bone(self) -> bpy.types.PoseBone:
        return self._pose_bone

    @_persistent
    def length(self) -> float:
        return self.bone().length

    @_persistent
    def parent(self):
        parent = self._bone.parent
        if parent is not None:
            return BpxBone(parent)

    @_persistent
    def children(self):
        for child in self._bone.children:
            yield BpxBone(child)

    @_persistent
    def unlocked_location(self):
        for axis in range(3):
            if not self._pose_bone.lock_location[axis]:
                yield axis

    @_persistent
    def unlocked_rotation(self):
        for axis in range(3):
            if not self._pose_bone.lock_rotation[axis]:
                yield axis

    @_persistent
    @with_cumulative_timing
    def matrix(self, world=True) -> Matrix:
        if world:
            return self._handle.matrix_world @ self.pose_bone().matrix
        else:
            return self.pose_bone().matrix

    @_persistent
    def rest_matrix(self, world=True) -> Matrix:
        if world:
            return self._handle.matrix_world @ self.bone().matrix_local
        else:
            return self._handle.matrix_local


def _remove(xobj, notify=True):
    assert isinstance(xobj, BpxType), "%s was not a BpxType" % xobj

    if xobj._removed:
        return

    # These can no longer be trusted
    ObjectCache.clear()
    BoneCache.clear()

    xobj._removed = True

    if isinstance(xobj, BpxArmature):
        # The body cannot live without the mind
        for xbone in SingletonType._instance_to_key:
            armature_uuid = xobj._uuid
            if isinstance(xbone, BpxBone) and xbone._uuid == armature_uuid:
                # Its removal state will be determined on next query
                xbone.dirty()

    if notify:
        for handler in handlers["object_removed"]:
            try:
                handler(xobj)
            except Exception:
                traceback.print_exc()


def _unremove(xobj, notify=True):
    assert isinstance(xobj, BpxType), "%s was not a BpxType" % xobj

    if not xobj._removed:
        return

    ObjectCache.clear()
    BoneCache.clear()

    xobj._removed = False

    if isinstance(xobj, BpxArmature):
        # The body can live with a mind
        for xbone in SingletonType._instance_to_key:
            if xbone._uuid == xobj._uuid:

                # We cannot immediately unremove it, because it's
                # possible it was removed due to a reason other than
                # its parent armature having been removed
                xbone.dirty()

    if notify:
        for handler in handlers["object_unremoved"]:
            try:
                handler(xobj)
            except Exception:
                traceback.print_exc()


@with_cumulative_timing
def _destroy(xobj):
    assert isinstance(xobj, BpxType), "%s was not a BpxType" % xobj

    if xobj._destroyed:
        return

    # Also remove from scene
    _remove(xobj, notify=False)

    xobj._destroyed = True

    # This can no longer be referenced
    key = SingletonType._instance_to_key.pop(xobj)

    # May have been removed by Python garbage collection
    SingletonType._key_to_instance.pop(key, None)

    for handler in handlers["object_destroyed"]:
        try:
            handler(xobj)
        except Exception:
            # Callbacks cannot throw actual exceptions
            traceback.print_exc()


def is_equivalent(a, b, tolerance=LinearTolerance):
    return (abs(a.x - b.x) < tolerance and
            abs(a.y - b.y) < tolerance and
            abs(a.z - b.z) < tolerance)


@with_cumulative_timing
def _bpxid(obj):
    assert isinstance(obj, (bpy.types.Object, bpy.types.Bone))

    if obj in _DEFERRED_BPXIDS:
        return _DEFERRED_BPXIDS[obj]

    id_ = ""
    if hasattr(obj, "bpxProperties"):
        id_ = obj.bpxProperties.bpxId

    return id_


@with_cumulative_timing
def _bpxtype(obj):
    assert isinstance(obj, (bpy.types.Object, bpy.types.Bone)), (
        "%s was not a bpy.types.Object or .Bone" % obj
    )

    typ = None
    if hasattr(obj, "bpxProperties"):
        typ = obj.bpxProperties.bpxType

    # TEMP: Backwards compatibility
    if not typ:
        try:
            typ = obj["bpxType"]
            obj.bpxProperties.bpxType = typ
        except KeyError:
            pass

    return typ


def _create_uuid():
    """Make a unique identifier

    Store as string, as 128-bit integers cannot be stored as-is
    in a Blender property, max is 32 or 16-bit

    It is also originally an integer, such that it
    can be converted back to an integer for hashing.

    """

    return str(uuid.uuid4().int)


def _make_bpxid(obj, overwrite=False):
    assert overwrite or obj.bpxProperties.bpxId == "", (
        "%s already has a bpxId: %s" % (obj, obj.bpxProperties.bpxId)
    )

    uid = _create_uuid()

    try:
        obj.bpxProperties.bpxId = uid
    except AttributeError as e:

        # Writing to a Blender property is sometimes forbidden,
        # e.g. when `bpy.types.Operator.poll()` is called during rendering
        if str(e).startswith("Writing to ID classes"):
            _DEFERRED_BPXIDS[obj] = uid

            def func(obj, uid):
                obj.bpxProperties.bpxId = uid
                _DEFERRED_BPXIDS.pop(obj)

            # Write when Blender is idling
            bpy.app.timers.register(
                functools.partial(func, obj, uid)
            )

    return uid


@with_cumulative_timing
def is_object_valid(obj):
    assert isinstance(obj, bpy.types.Object), obj

    if not obj:
        return False

    # Better to ask forgiveness than permission
    try:
        obj.name
    except ReferenceError:
        return False

    return True


def _clear_all_caches():
    """Internal, to erase everything we think we know"""
    ObjectCache.clear()
    BoneCache.clear()

    _ORDERED_SELECTION[:] = []
    _LAST_SELECTION[:] = []

    SingletonType._key_to_instance.clear()
    SingletonType._instance_to_key.clear()

    _ALIASES.clear()
    _DEFERRED_BPXIDS.clear()


class ObjectCache:
    """Optimise `find_object_by_uuid` by storing prior references"""

    _uuid_to_object = dict()
    _cached_objects = set()

    @classmethod
    def get(cls, uid):
        obj = cls._uuid_to_object.get(uid)

        # It may be cached, but is it still valid?
        if obj is not None and not is_object_valid(obj):
            obj = None

        return obj

    @classmethod
    def store(cls, uid, obj):
        cls._uuid_to_object[uid] = obj
        cls._cached_objects.add(obj)

    @classmethod
    def clear(cls):
        cls._uuid_to_object.clear()
        cls._cached_objects.clear()

    @classmethod
    def is_cached(cls, obj):
        return id(obj) in cls._cached_objects


class BoneCache:
    """Optimise `find_bone_by_uuid` by storing prior references"""

    _uuid_to_bone = dict()
    _cached_bones = set()

    @classmethod
    def get(cls, uid):
        return cls._uuid_to_bone.get(uid)

    @classmethod
    def store(cls, uid, bone):
        cls._uuid_to_bone[uid] = bone
        cls._cached_bones.add(bone)

    @classmethod
    def clear(cls):
        cls._uuid_to_bone.clear()
        cls._cached_bones.clear()

    @classmethod
    def is_cached(cls, bone):
        return bone in cls._cached_bones


@with_cumulative_timing
def find_object_by_uuid(bpxid):
    assert isinstance(bpxid, (str, int)), "%s was not a bpxid" % bpxid

    result = ObjectCache.get(bpxid)

    if result is None:
        for obj in bpy.context.scene.objects:

            # We know this isn't the one, because we've already checked it
            if ObjectCache.is_cached(obj):
                continue

            uid = _get_uuid(obj)
            ObjectCache.store(uid, obj)

            if uid == bpxid:
                result = obj
                break

        # Objects can exist in a linked library, which to the user
        # appears like any other object. Except they are not in the
        # current scene as above, but rather nested in a collection
        else:
            if len(bpy.data.libraries):
                for col in bpy.data.collections:
                    if not col.library:
                        # Not a linked collection
                        continue

                    for obj in col.objects:
                        if ObjectCache.is_cached(obj):
                            continue

                        uid = _get_uuid(obj)
                        ObjectCache.store(uid, obj)

                        if uid == bpxid:
                            result = obj
                            break

    return result


@with_cumulative_timing
def find_bone_by_uuid(armature, boneid):
    assert isinstance(armature, bpy.types.Object), (
        "%s was not a bpy.types.Armature" % armature
    )
    assert isinstance(armature.data, bpy.types.Armature), (
        "%s was not a bpy.types.Armature" % armature
    )
    assert isinstance(boneid, (int, str)), "%s was not a boneid" % boneid

    result = None
    armature_id = _get_uuid(armature)

    if is_object_valid(armature):
        result = BoneCache.get((armature_id, boneid))

    if result is None:
        for bone in armature.data.bones:
            if BoneCache.is_cached(bone):
                continue

            if _USE_SESSION_UUID:
                aid, bid = _get_uuid(bone)
                BoneCache.store((aid, bid), bone)

                if armature_id == aid and boneid == bid:
                    result = bone
                    break
            else:
                uid = _bpxid(bone)
                BoneCache.store(uid, bone)

                if uid == boneid:
                    result = bone
                    break

    return result


@with_cumulative_timing
def find_bone_by_index(armature, boneidx, boneid=None, name=None):
    """Quickest way to find a bone, by its index in the `bones` list

    This can also return false positives, if e.g. there are 5 bones
    and index 1 is removed, index 1 will still exist but will be
    a different bone.

    The `name` argument can be used to verify that the name of the
    discovered bone indeed refers to the correct bone. However, this
    can *also* give falst positives if a bone was both removed and
    renamed prior to being re-evaluated.

    Thus, the `boneid` argument can be used to doubly-verify that
    this indeed is the bone.

    Arguments:
        armature (bpy.types.Armature): Armature containing the bone
        boneidx (int): Index of bone
        name (str, optional): Verify bone name at this index

    """

    assert isinstance(armature, bpy.types.Object), (
        "%s was not an bpy.types.Armature" % armature
    )
    assert isinstance(armature.data, bpy.types.Armature), (
        "%s was not an bpy.types.Armature" % armature
    )

    if boneidx is None or boneidx == -1:
        # May be uninitialised
        return None

    bone = armature.data.bones[boneidx]

    if name and bone.name != name:
        return None

    if boneid and boneid:
        aid, bid = _get_uuid(bone)
        if bid != boneid:
            return None

    return bone


def _set_bpxtype(obj, type):
    """Internal"""
    obj.bpxProperties.bpxType = type


def add_attr(obj, name, default=None):
    """Add a new dynamic attribute"""
    obj.handle()[name] = default


def get_attr(obj, name, default=None):
    """Get value of existing dynamic attribute"""
    try:
        return obj.handle()[name]
    except KeyError:
        return default


def set_attr(obj, name, value):
    """Get value of existing dynamic attribute"""
    obj.handle()[name] = value


def set_prop(prop, value):
    prop.write(value)


def get_prop(obj, name):
    handle = obj.handle()
    return getattr(handle, name)


def undo():
    if _BACKGROUND:
        SingletonType.invalidate()
        bpy.ops.ed.undo_push()
    else:
        bpy.ops.ed.undo()


def with_undo_chunk(func):
    """A decorator for adding undo step after executing `func`"""
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            bpy.ops.ed.undo_push(message=func.__qualname__)

    return wrapped


def call_once(func):
    """This function has no effect on subsequent calls"""
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        if getattr(wrapped, "been_called", False):
            return

        setattr(wrapped, "been_called", True)
        return func(*args, **kwargs)

    return wrapped


def been_called(func):
    return getattr(func, "been_called", False)


def unset_called(func):
    return setattr(func, "been_called", False)


def find(object: str | bpy.types.Object, bone: str = None) -> typing.Any:
    try:
        if isinstance(object, BpxType):
            object = object.handle()

        if isinstance(object, str):
            object = bpy.context.scene.objects[object]

        if bone is not None:
            assert isinstance(object.data, bpy.types.Armature), (
                "%s was not an armature" % object
            )

            bone = object.pose.bones[bone]
            return BpxBone(bone)
        else:
            return BpxObject(object)

    except KeyError:
        pass

    # Only an exist error is expected here
    except Exception:
        raise

    try:
        if isinstance(object, str):
            return bpy.context.scene.collection.children[object]

    except KeyError:
        pass


def find_collection(name):
    try:
        return bpy.context.scene.collection.children[name]
    except KeyError:
        return None


def with_maintained_selection(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with maintained_selection(bpy.context):
            return func(*args, **kwargs)

    return wrapper


@_requires_install
@with_maintained_selection
def create_object(type: int,
                  name: str = "",
                  parent=None,
                  archetype=None) -> BpxType:
    """Create a new Blender object

    Arguments:
        type (int): Type of object to create
        name (str, optional): Name of new object
        parent (BpxObject, optional): Parent to new object
        archetype (str, optional): Name of property group for this object

    Example:
        >>> a = create_object(e_empty_cube, name="myCube")
        >>> b = create_object(e_empty_cube, parent=a)
        >>> isinstance(a, BpxType)
        True
        >>> isinstance(b, BpxType)
        True

    """

    assert isinstance(type, int), "%s was not an object type" % type
    assert parent is None or isinstance(parent, BpxType)

    # Mesh
    if type == e_mesh_plane:
        bpy.ops.mesh.primitive_plane_add()
    elif type == e_mesh_cube:
        bpy.ops.mesh.primitive_cube_add()
    elif type == e_mesh_circle:
        bpy.ops.mesh.primitive_circle_add()
    elif type == e_mesh_uv_sphere:
        bpy.ops.mesh.primitive_uv_sphere_add()
    elif type == e_mesh_ico_sphere:
        bpy.ops.mesh.primitive_ico_sphere_add()
    elif type == e_mesh_cylinder:
        bpy.ops.mesh.primitive_cylinder_add()
    elif type == e_mesh_cone:
        bpy.ops.mesh.primitive_cone_add()
    elif type == e_mesh_torus:
        bpy.ops.mesh.primitive_torus_add()
    elif type == e_mesh_grid:
        bpy.ops.mesh.primitive_grid_add()
    elif type == e_mesh_suzanne:
        bpy.ops.mesh.primitive_monkey_add()

    # Empty
    elif e_empty <= type <= e_empty_image:
        _create_empty_object(type)

    # Armature
    elif type == e_armature_empty:
        adata = bpy.data.armatures.new(name="Armature")
        armature = bpy.data.objects.new(name=adata.name, object_data=adata)
        set_active(armature, link_collection=True)

    else:
        raise TypeError("Unknown type enum: %s" % type)

    xobj = BpxType(bpy.context.active_object, exists=False)

    if parent is not None:
        reparent(xobj, parent)

    if name is not None:
        rename(xobj, name)

    if archetype is not None:
        _set_bpxtype(xobj.handle(), archetype)

    return xobj


def create_constraint(xobj, type):
    if isinstance(xobj, BpxBone):
        handle = xobj.pose_bone()
    elif isinstance(xobj, BpxObject):
        handle = xobj.handle()
    elif isinstance(xobj, bpy.types.Object):
        handle = xobj
    elif isinstance(xobj, bpy.types.PoseBone):
        handle = xobj
    else:
        raise TypeError("%s was not a Bone nor Object" % xobj)

    return handle.constraints.new(type=type)


def create_collection(name, parent=None):
    parent = parent or bpy.context.scene.collection
    collection = bpy.data.collections.new(name)
    parent.children.link(collection)
    return collection


def poly_cube(name, extents=None, offset=None):
    extents = extents or Vector((1, 1, 1))
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1)
    bmesh.ops.scale(bm, vec=extents, verts=bm.verts)

    if offset is not None:
        bmesh.ops.transform(bm, matrix=offset, verts=bm.verts)

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    mesh.update()
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    return BpxObject(obj, exists=False)


def poly_sphere(name, radius=1.0, offset=None):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=radius)

    if offset is not None:
        bmesh.ops.transform(bm, matrix=offset, verts=bm.verts)

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    mesh.update()
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    return BpxObject(obj, exists=False)


def poly_capsule(name, height=1.0, radius=1.0, offset=None):
    half_z = height / 2

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=11, radius=radius)
    bm.verts.ensure_lookup_table()

    max_z_below = 0
    min_z_above = 0
    for vert in bm.verts:
        if vert.co[2] < 0:
            if max_z_below < vert.co[2] or max_z_below == 0:
                max_z_below = vert.co[2]
        elif vert.co[2] > 0:
            if min_z_above > vert.co[2] or min_z_above == 0:
                min_z_above = vert.co[2]

    for vert in bm.verts:
        if vert.co[2] < 0:
            vert.co[2] -= half_z + max_z_below
        elif vert.co[2] > 0:
            vert.co[2] += half_z - min_z_above

    y_axis = Vector((0, 1, 0))
    re_orient = Quaternion(y_axis, radians(-90)).to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=re_orient, verts=bm.verts)

    if offset is not None:
        bmesh.ops.transform(bm, matrix=offset, verts=bm.verts)

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    mesh.update()
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    return BpxObject(obj, exists=False)


def delete(*xtypes):
    xobjects = []
    xcollections = []

    for x in xtypes:
        if isinstance(x, BpxObject):
            xobjects.append(x)

        if isinstance(x, bpy.types.Collection):
            xcollections.append(x)

    if xobjects:
        select(*xobjects)
        bpy.ops.object.delete(
            # Also remove from bpy.data.objects
            use_global=True,

            confirm=False)

        # Deleting via Python does not let our operator handler
        # spot the operator, since it didn't come from the window manager
        # So instead we call it manually here.
        _on_operator_object_delete(bpy.context.scene)

        # NOTE: This won't account for users manually
        # calling bpy.ops.object.delete() outside of bpx

    if xcollections:
        # Unlink the collection from all scenes
        for xcol in xcollections:
            for scene in bpy.data.scenes:
                if xcol.name in scene.collection.children:
                    scene.collection.children.unlink(xcol)

        # Once unlinked from all scenes, delete the collection
        bpy.data.collections.remove(xcol)


def hide(obj):
    if isinstance(obj, BpxObject):
        obj = obj.handle()

    obj.hide_set(True)


def show(xobj):
    if isinstance(xobj, BpxObject):
        xobj.handle().hide_set(False)
    else:
        raise TypeError("%s could not be hidden" % xobj)


def _create_empty_object(type):
    typ = {
        e_empty: "PLAIN_AXES",
        e_empty_plain_axes: "PLAIN_AXES",
        e_empty_arrows: "ARROWS",
        e_empty_single_arrow: "SINGLE_ARROW",
        e_empty_circle: "CIRCLE",
        e_empty_cube: "CUBE",
        e_empty_sphere: "SPHERE",
        e_empty_cone: "CONE",
        e_empty_image: "IMAGE",
    }[type]

    empty = bpy.data.objects.new(name="Empty", object_data=None)
    empty.hide_render = True

    if type == e_empty:
        empty.empty_display_size = 0
    else:
        empty.empty_display_type = typ

    set_active(empty, link_collection=True)


def set_active(object_, link_collection=False):
    if isinstance(object_, BpxType):
        object_ = object_.handle()
    if link_collection:
        bpy.context.collection.objects.link(object_)
    bpy.context.view_layer.objects.active = object_


def set_mode(mode):
    if bpx.mode() != mode:
        bpy.ops.object.mode_set(mode=mode)


def mode():
    """Return the currently active mode"""
    active_object = bpy.context.active_object

    if active_object:
        return active_object.mode
    else:
        return ObjectMode


@contextlib.contextmanager
def pose_mode(xobj):
    if not isinstance(xobj, BpxArmature):
        xobj = BpxType(xobj)

    assert isinstance(xobj, BpxArmature), "%s was not an armature" % xobj
    set_active(xobj)
    previous_mode = bpy.context.object.mode

    try:
        set_mode(PoseMode)
        yield
    finally:
        set_mode(previous_mode)


@contextlib.contextmanager
def object_mode():
    previous_obj = bpy.context.object
    previous_mode = ObjectMode

    # No mode without an object
    if previous_obj:

        # Do not change anything if we don't need to
        if previous_obj.mode != ObjectMode:
            previous_mode = previous_obj.mode
            bpy.ops.object.mode_set(mode=ObjectMode)

    yield

    # Cannot restore to POSE unless we've got an armature selected
    if previous_mode == PoseMode:
        bpy.context.view_layer.objects.active = previous_obj

    if previous_obj:
        if previous_mode != ObjectMode:
            bpy.ops.object.mode_set(mode=previous_mode)


@contextlib.contextmanager
def edit_mode(xobj):
    bpy.context.view_layer.objects.active = xobj.handle()
    previous_mode = bpy.context.object.mode
    bpy.ops.object.mode_set(mode=EditMode)
    yield
    bpy.ops.object.mode_set(mode=previous_mode)


@_requires_install
@with_suspension
def select(*items: str | BpxType | list[str | BpxType], append=False):
    """Select `items`

    `items` can be a single item, multiple items, or nested items

    This call is suspended from callbacks, because we manually
    manage selection ordering.

    """

    if not append:
        deselect_all()

    if isinstance(items, tuple):
        items = list(items)

    flattened = []
    for item in items:
        if isinstance(item, (tuple, list)):
            flattened.extend(item)
        else:
            flattened.append(item)

    if not flattened:
        return

    for index, item in enumerate(flattened[:]):
        if isinstance(item, BpxType):
            flattened[index] = item.name()

    active_object = bpy.context.object

    if not active_object:
        if bpy.context.mode == ObjectMode:
            # Possibly previous active object was deleted.
            # Pick last item as new active.
            active_object = bpy.context.scene.objects[flattened[-1]]
        else:
            debug("No active object")
            return

    current_mode = active_object.mode

    if current_mode == ObjectMode:
        items = []
        last_item = None
        for item in flattened:
            item = bpy.context.scene.objects[item]
            item.hide_set(False)  # Cannot select a hidden object

            try:
                item.select_set(True)
            except RuntimeError:
                # Cannot select an object that is excluded from the view layer
                continue

            items.append(item)
            last_item = item

        # Make the last selected active, this makes
        # it appear in the Properties Panel
        if last_item is not None:
            bpy.context.view_layer.objects.active = last_item

        _ORDERED_SELECTION[:] = list(map(BpxType, items))

    elif current_mode == PoseMode:
        if active_object.type != "ARMATURE":
            warning("bpx misunderstood something, this is a bug")
        else:
            items = []
            bone = None
            for name in flattened:
                bone = active_object.data.bones[name]
                bone.select = True
                items.append(bone)

            if bone:
                # Make last given the active one
                active_object.data.bones.active = bone

        _ORDERED_SELECTION[:] = list(map(BpxBone, items))


def deselect_all():
    _mode = mode()

    if _mode == ObjectMode:
        bpy.ops.object.select_all(action="DESELECT")

    elif _mode == EditMode:
        obj = bpy.context.view_layer.objects.active

        if obj.type == "ARMATURE":
            bpy.ops.armature.select_all(action="DESELECT")

    elif _mode == PoseMode:
        obj = bpy.context.view_layer.objects.active

        if obj.type == "ARMATURE":
            bpy.ops.pose.select_all(action="DESELECT")

    else:
        raise ValueError("Unsupported mode: %s" % _mode)


def rename(xobj, name):
    """Rename `xobj` to `name`

    Examples:
        >>> new()
        >>> obj = create_object(e_empty_cube, name="Test")
        >>> obj.name()
        'Test'
        >>> rename(obj, "NewName")
        >>> obj.name()
        'NewName'

    """

    xobj.handle().name = name


def reparent(child, parent):
    if isinstance(child, BpxObject):
        if isinstance(parent, bpy.types.Collection):
            parent.objects.link(child)
        elif isinstance(parent, BpxObject):
            child.handle().parent = parent.handle()
        else:
            raise TypeError("%s was not an object or collection" % parent)
    else:
        raise TypeError("%s was not a BpxObject" % child)


def link(xobj, collection, move=True):
    if isinstance(xobj, BpxObject):
        if move:
            for existing_collection in xobj.collections():
                existing_collection.objects.unlink(xobj.handle())

        collection.objects.link(xobj.handle())

    else:
        raise TypeError("%s was unsupported" % xobj)


def new(use_factory_startup=False, use_empty=False, **kwargs):
    bpy.ops.wm.read_homefile(
        use_factory_startup=use_factory_startup,
        use_empty=use_empty,
        **kwargs
    )


def deferred(func):
    """Call func from the main thread when Blender is at idle"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bpy.app.timers.register(
            functools.partial(func, *args, **kwargs)
        )
    return wrapper


class Chain:
    def __init__(self, parent=None):
        if parent:
            armature = bpy.context.active_object
            assert parent in armature.data.edit_bones

        self._joints = []
        self._parent = parent

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, tb):
        armature = bpy.context.active_object
        assert isinstance(armature.data, bpy.types.Armature)

        # Some basic validation
        names = set()
        for index, joint in enumerate(self._joints[:-1]):
            parent = self._joints[index - 1]
            assert joint["position"] != parent["position"], (
                "%s == %s" % (parent["name"], joint["name"])
            )
            assert joint["name"] not in names, (
                "%s duplicate name" % joint["name"]
            )
            names.add(joint["name"])

        for index, tip in enumerate(self._joints[1:]):
            joint = self._joints[index]

            bone = armature.data.edit_bones.new(joint["name"])
            bone.head = joint["position"]
            bone.tail = tip["position"]

            if index > 0:
                parent_joint = self._joints[index - 1]
                parent_bone = armature.data.edit_bones[parent_joint["name"]]
                bone.parent = parent_bone
                bone.head = parent_bone.tail
                bone.use_connect = True

            elif self._parent:
                parent_bone = armature.data.edit_bones[self._parent]
                bone.parent = parent_bone

        with pose_mode(armature):
            for joint in self._joints[:-1]:
                pose_bone = armature.pose.bones[joint["name"]]
                for key, value in joint["properties"].items():
                    setattr(pose_bone, key, value)

    def add(self, name, position, **kwargs):
        self._joints.append({
            "name": name,
            "position": Vector(position),

            # Optional properties
            "properties": dict({

                # Defaults
                "rotation_mode": "XYZ",

            }, **kwargs)
        })
        return self._joints[-1]


def make_human(name=""):
    armature = create_object(e_armature_empty, name=name or "Human")
    armature.handle().location[2] = 5.5

    with edit_mode(armature):
        with Chain() as spine:
            spine.add("hip", (0, 0, 1))
            spine.add("torso", (0, 0, 2))
            spine.add("chest", (0, 0, 2.5))
            spine.add("neck", (0, 0, 3))
            spine.add("head", (0, 0, 4))
            spine.add("head_tip", (0, 0, 5))

        with Chain(parent="hip") as leg:
            leg.add("L_upperLeg", (0, 1, 0))
            leg.add("L_lowerLeg", (0, 1, -2))
            leg.add("L_foot", (0, 1, -4))
            leg.add("L_foot_tip", (1, 1, -4))

        with Chain(parent="hip") as leg:
            leg.add("R_upperLeg", (0, -1, 0))
            leg.add("R_lowerLeg", (0, -1, -2))
            leg.add("R_foot", (0, -1, -4))
            leg.add("R_foot_tip", (1, -1, -4))

        with Chain(parent="chest") as leg:
            leg.add("R_upperArm", (0, -1, 2))
            leg.add("R_lowerArm", (0, -3, 2))
            leg.add("R_hand", (0, -5, 2))
            leg.add("R_hand_tip", (0, -5.5, 2))

        with Chain(parent="chest") as leg:
            leg.add("L_upperArm", (0, 1, 2))
            leg.add("L_lowerArm", (0, 3, 2))
            leg.add("L_hand", (0, 5, 2))
            leg.add("L_hand_tip", (0, 5.5, 2))

    return armature


def print_console(text):
    """Write to currently open Python Console (if any)"""

    def find_console():
        for area in bpy.context.screen.areas:
            if area.type != "CONSOLE":
                continue

            for space in area.spaces:
                if space.type != "CONSOLE":
                    continue

                for region in area.regions:
                    if region.type != "WINDOW":
                        continue

                    return area, space, region
        return None, None, None

    area, space, region = find_console()
    if space is None:
        return

    context_override = bpy.context.copy()
    context_override.update({
        "space": space,
        "area": area,
        "region": region,
    })

    if not isinstance(text, str):
        text = str(text)

    with bpy.context.temp_override(**context_override):
        for line in text.split("\n"):
            bpy.ops.console.scrollback_append(text=line, type="OUTPUT")


def _is_collection_in_scene(collection, scene):
    # Direct check if the collection is linked to the scene
    if collection.name in scene.collection.children.keys():
        return True

    # Recursive check for parent collections
    for col in scene.collection.children:
        if col is collection:
            continue
        if collection.name in col.objects.keys():
            if _is_collection_in_scene(col, scene):
                return True

    return False


@with_tripwire
@with_cumulative_timing
def ls(type=None, internal=False):
    """Return all objects as BpxObject instances"""
    return list(ls_iter(type, internal))


def ls_iter(type=None, internal=False, linked=True):
    """Generator alternative to ls()

    The benefit of a generator is that not all objects must be
    computed prior to finishing. If all you need is the first
    object, or a handful of objects in a scene with thousands,
    then this will avoid the cost of computing all objects first.

    Arguments:
        type (str, optional): Only include objects of this bpxType
        internal (bool, optional): Only list known objects
        linked (bool, optional): Include objects within libraries
            that have not been overridden. This comes at a
            performance penalty.

    """

    if internal:
        objects = [x._handle for x in SingletonType._instance_to_key]
    else:
        objects = bpy.context.scene.objects

    # Consider linked scenes
    if linked and len(bpy.data.libraries) > 0:
        linked_objects = []
        for col in bpy.data.collections:
            if col.library is None:
                # A regular, non-linked collection
                continue

            # Is it part of the current scene?
            if not _is_collection_in_scene(col, bpy.context.scene):
                continue

            # It's a linked collection!
            linked_objects.append(col.objects)

        for gen in linked_objects:
            objects = itertools.chain(objects, gen)

    for obj in objects:
        if type and not is_type(obj, type):
            continue

        yield BpxType(obj)


def active_selection(type=None, mode=None):
    mode = mode or bpy.context.mode
    xobj = None

    if mode == PoseMode:
        bone = bpy.context.active_pose_bone
        if bone:
            xobj = BpxBone(bone)

    else:
        obj = bpy.context.active_object

        if obj:
            xobj = BpxObject(obj)

    if not xobj:
        return None

    if type and not is_type(xobj, type):
        return None

    return xobj


@with_tripwire
def selection(type=None,
              active=False,
              mode=None,
              order=SelectionOrder) -> list[BpxType]:
    """Returns a list of selected BpxType items

    Arguments:
        type (str, None): Only return items of this type
        active (bool): Return active object or bone, if any
        mode (str, optional): Return items from this mode
        order (enum, optional): Return items in the order of
            SelectionOrder or HierarchyOrder

    """

    return list(selection_iter(type, active, mode, order))


def selection_iter(type=None,
                   active=False,
                   mode=None,
                   order=SelectionOrder):
    """Yields selected BpxType items

    Arguments:
        type (str, optional): Only return items of this type
        active (bool, optional): Return active object or bone, if any
        mode (str, optional): Return items from this mode
        order (enum, optional): Return items in the order of
            SelectionOrder or HierarchyOrder

    """

    mode = mode or bpy.context.mode
    selected = []

    # Use active object instead of the order selection
    if active:
        if mode == PoseMode:
            bone = bpy.context.active_pose_bone
            if bone:
                selected = [BpxBone(bone)]

        else:
            obj = bpy.context.active_object

            if obj:
                selected = [BpxObject(obj)]

    elif order and USE_ORDERED_SELECTION:
        selected = _ORDERED_SELECTION

    else:
        if mode == ObjectMode:
            selected = map(BpxObject, bpy.context.selected_objects)

        elif mode == PoseMode:
            selected = map(BpxBone, bpy.context.selected_pose_bones)

        else:
            raise TypeError("Unsupported mode: %s" % mode)

    for sel in selected:
        if sel._removed:
            continue

        if mode == PoseMode and not isinstance(sel, BpxBone):
            continue

        if mode == ObjectMode and not isinstance(sel, BpxObject):
            continue

        if type:
            if not is_type(sel, type):
                continue

        yield sel


# Alias
sl = selection


@with_cumulative_timing
def is_type(sel, type: tuple | list | str | typing.Type):
    """Check `sel` against `type`

    Examples:
        >>> new()
        >>> xobj = create_object(e_empty_cube)
        >>> obj = xobj.handle()
        >>> is_type(xobj, BpxType)
        True
        >>> is_type(xobj, BpxObject)
        True
        >>> is_type(xobj.handle(), bpy.types.Object)
        True
        >>> is_type(xobj, "myCustomType")
        False
        >>> obj.bpxProperties.bpxType = "myCustomType"
        >>> is_type(xobj, "myCustomType")
        True

        # Can also compare native Blender types
        >>> is_type(obj, "myCustomType")
        True

    """

    if not isinstance(type, (list, tuple)):
        type = (type,)

    for typ in type:
        # Support for querying type via bpx type, e.g. "rdSolver"
        if isinstance(typ, str):
            if isinstance(sel, (bpy.types.Object, bpy.types.Bone)):
                if sel.bpxProperties.bpxType == typ:
                    return True

            elif isinstance(sel, BpxType):
                if sel._bpxtype == typ:
                    return True

        # Support for query via actual Python type
        elif isinstance(sel, typ):
            return True

    return False


def create_alias(a, b):
    """Create a new alias for `b`

    A BpxType instance may be accessed in reverse through via this alias
    as opposed to iterating over all items looking for a property or
    metadata value.

    """

    _ALIASES[hash(a)] = b


def alias(name, *args, **kwargs) -> typing.Any:
    """Return BpxType instance that matches `name`

    Aliases are created via create_alias(name, xobj)

    """

    hsh = hash(name)

    # Facilitate default argument
    if not args and not kwargs:
        return _ALIASES[hsh]
    else:
        try:
            default = args[0]
        except IndexError:
            try:
                default = kwargs["default"]
            except KeyError:
                raise TypeError(
                    "Bad args '%s' and kwargs '%s'" % (args, kwargs)
                )

        return _ALIASES.get(hsh, default)


@with_cumulative_timing
def rearrange_all():
    """The bone indices can no longer be trusted, e.g. a bone was reparented"""
    for obj in SingletonType._instance_to_key:
        if isinstance(obj, BpxBone):
            obj.rearrange()


@with_cumulative_timing
def dirty_all():
    """Dirty all references to bpy.types.Object instances"""

    for obj in SingletonType._instance_to_key:
        obj.dirty()

    ObjectCache.clear()
    BoneCache.clear()


@with_cumulative_timing
def restore_all():
    """Restore all references to bpy.types.Object instances"""

    for obj in SingletonType._instance_to_key:
        _restore(obj)


@bpy.app.handlers.persistent
def _post_undo_redo(scene, *_):
    """Blender shuffles handles to objects around on undo

    This function ensures that all handles are up to date. This is
    also a good time to do it, since performance won't matter as much
    when the user is undoing and redoing as it does during playback.

    """

    dirty_all()


@with_cumulative_timing
def _on_selection_updated(scene, new_selection):
    deselected = not new_selection

    _LAST_SELECTION[:] = _ORDERED_SELECTION

    if deselected:
        selection_changed = len(_ORDERED_SELECTION) > 0
        _ORDERED_SELECTION[:] = []

    else:
        selection_changed = False

        # Remove from selection, preserving order
        for sel in _ORDERED_SELECTION[:]:
            if isinstance(sel, BpxBone):
                handle = sel.pose_bone()
            else:
                handle = sel.handle()

            if handle not in new_selection:
                try:
                    _ORDERED_SELECTION.remove(sel)
                except Exception:
                    # Unclear when this happens
                    warning(
                        "%s was not in _ORDERED_SELECTION, this is a bug"
                        % sel
                    )
                    traceback.print_exc()

                selection_changed = True

        # Append to selection, preserving order
        for sel in new_selection:
            sel = BpxType(sel)

            if sel not in _ORDERED_SELECTION:
                _ORDERED_SELECTION.append(sel)
                selection_changed = True

    if selection_changed:
        for handler in handlers["selection_changed"]:
            try:
                handler(_ORDERED_SELECTION)
            except Exception:
                traceback.print_exc()


def _on_mode_changed(previous, current):
    # Leaving Edit Mode may cause bones to invalidate, regardless
    # of whether or not they were edited.
    if previous == EditArmatureMode:
        dirty_all()
        rearrange_all()

    for handler in handlers["mode_changed"]:
        handler(previous, current)


@bpy.app.handlers.persistent
@with_cumulative_timing
def _post_depsgraph_changed(scene, depsgraph):
    """Manage ordered selection"""

    last_mode = getattr(_post_depsgraph_changed, "last_mode", None)
    current_mode = bpy.context.mode

    if current_mode == ObjectMode:
        _depsgraph_object_mode_handler(scene, depsgraph)

    if current_mode == PoseMode:
        _depsgraph_pose_mode_handler(scene, depsgraph)

    if current_mode != last_mode:
        _on_mode_changed(last_mode, current_mode)

    if depsgraph.objects:
        for handler in handlers["depsgraph_changed"]:
            try:
                handler()
            except Exception:
                traceback.print_exc()

    if hasattr(bpy.context, "window_manager"):
        _depsgraph_operator_handler(scene)

    setattr(_post_depsgraph_changed, "last_mode", current_mode)


def _depsgraph_operator_handler(scene):
    """Update bpxId when duplication happens

    This function assumes that the only way an object can be duplicated
    is via the duplicate operator(s).

    Not true? Please submit a pull-request

    """

    try:
        last_op = bpy.context.window_manager.operators[-1]
    except IndexError:
        pass
    else:
        curr_size = len(bpy.context.window_manager.operators)
        prev_size = getattr(_depsgraph_operator_handler, "previous_size", 0)

        # Only bother with newly executed operators
        if curr_size == prev_size:
            return

        # https://github.com/blender/blender
        # /blob/9c0bffcc89f174f160805de042b00ae7c201c40b
        # /source/blender/editors/object/object_add.cc#L2481
        if last_op.bl_idname in ("OBJECT_OT_delete",
                                 "OUTLINER_OT_delete"):
            _on_operator_object_delete(scene)

        if last_op.bl_idname == "ARMATURE_OT_delete":
            _on_operator_bone_delete(scene)

        # The session_uuid is unique for duplicated objects, the bpxId is not
        if not _USE_SESSION_UUID:
            if last_op.bl_idname in ("OBJECT_OT_duplicate",
                                     "OBJECT_OT_duplicate_move"):
                _on_operator_duplicate(scene)

        setattr(_depsgraph_operator_handler, "previous_size", curr_size)


def _on_operator_object_delete(scene):
    """The delete operator was called

    We know that objects can only be deleted if they are first selected.
    Therefore, it is safe to assume that whatever was selected prior to
    the scene graph being updated was the objects that was deleted.

    """

    for sel in _LAST_SELECTION:
        _remove(sel)


def _on_operator_bone_delete(scene):
    for sel in _LAST_SELECTION:
        _remove(sel)


def _on_operator_duplicate(scene):
    # Current selection post-operator are the duplicated objects
    selected = bpy.context.selected_objects

    for obj in selected:
        _make_bpxid(obj, overwrite=True)

    # Update selection *after* making a new ID, since they relate
    _on_selection_updated(scene, selected)

    for handler in handlers["object_duplicated"]:
        try:
            handler()
        except Exception:
            traceback.print_exc()


def _depsgraph_object_mode_handler(scene, depsgraph):
    selection_invalidated = False

    for update in depsgraph.updates:
        is_relevant = not any((
            update.is_updated_geometry,
            update.is_updated_transform,
            update.is_updated_shading
        ))

        if is_relevant:
            selection_invalidated = True
            break

    if selection_invalidated:
        # Blender doesn't provide ordered selection,
        # so we have to handle this by ourselves
        selected = bpy.context.selected_objects
        _on_selection_updated(scene, selected)


def _depsgraph_pose_mode_handler(scene, depsgraph):
    selection_invalidated = False

    for update in depsgraph.updates:
        is_relevant = not any((
            update.is_updated_geometry,
            update.is_updated_transform,
            update.is_updated_shading
        ))

        if is_relevant:
            selection_invalidated = True
            break

    if selection_invalidated:
        # Blender doesn't provide ordered selection,
        # It seems that bone selection is ordered by hierarchy, not
        # selected order, so we track the order by ourselves.
        selected = bpy.context.selected_pose_bones or []
        selected += bpy.context.selected_objects or []
        _on_selection_updated(scene, selected)


@bpy.app.handlers.persistent
def _post_file_open(*_args):
    """Destroy xobjects prior to bpy.types.Object being destroyed"""
    SingletonType.destroy_all()

    _clear_all_caches()

    object = bpy.context.active_object
    if object and object.mode == ObjectMode:
        selected = bpy.context.view_layer.objects.selected
        _on_selection_updated(bpy.context.scene, selected or [])

    # Trigger the create_object handler
    for obj in bpy.data.objects:
        BpxObject(obj)

        if isinstance(obj.data, bpy.types.Armature):
            for bone in obj.data.bones:
                BpxBone(bone)


@bpy.app.handlers.persistent
def _pre_file_open(*_args):
    pass


@bpy.app.handlers.persistent
@with_cumulative_timing
def _on_save_pre(*args):
    """Track evaluations happening during save

    The depsgraph evaluates inbetween saving and loading, and we may or
    may not want to perform some action while this is happening.

    """

    bpy.app.handlers.depsgraph_update_post.remove(_post_depsgraph_changed)


@bpy.app.handlers.persistent
@with_cumulative_timing
def _on_save_post(*args):
    bpy.app.handlers.depsgraph_update_post.append(_post_depsgraph_changed)


class BpxProperties(bpy.types.PropertyGroup):
    bpxType: bpy.props.StringProperty(
        name="bpxType",
        default="",
        description="Get properties from the property group of this name",
        options={"HIDDEN"},
    )
    bpxId: bpy.props.StringProperty(
        name="bpxId",
        default="",
        description="A unique ID",
        options={"HIDDEN"},
    )


# Register these regardless of whether we `install`
# Since they are necessary in order to use bpx when uninstalled
#
# In Blender, properties are not added to individual objects,
# but rather to *all* objects. Those objects interested in
# the properties then make a concerted effort to access them
# explicitly, while other objects simply ignore them.
#
# We assign properties to Bone rather than PoseBone, even though PoseBone
# carries the most relevant information including the final worldspace
# Matrix, because properties stored with Bone survives deletion followed
# by undo, wherease PoseBone does not.
#
# https://projects.blender.org/blender/blender/issues
# /64612#issuecomment-447694
bpy.utils.register_class(BpxProperties)
for typ in (bpy.types.Object, bpy.types.Bone):
    typ.bpxProperties = bpy.props.PointerProperty(type=BpxProperties)


def install():
    global _INSTALLED

    if _INSTALLED:
        return

    _INSTALLED = True

    bpy.app.handlers.undo_post.insert(0, _post_undo_redo)
    bpy.app.handlers.redo_post.insert(0, _post_undo_redo)
    bpy.app.handlers.load_post.insert(0, _post_file_open)
    bpy.app.handlers.load_pre.insert(0, _pre_file_open)
    bpy.app.handlers.save_pre.insert(0, _on_save_pre)
    bpy.app.handlers.save_post.insert(0, _on_save_post)
    bpy.app.handlers.depsgraph_update_post.insert(0, _post_depsgraph_changed)

    fmt = logging.Formatter(
        "bpx.%(funcName)s() - %(message)s"
    )

    handler = logging.StreamHandler()
    handler.setFormatter(fmt)

    _LOG.addHandler(handler)
    _LOG.propagate = False
    _LOG.setLevel(logging.INFO)


def uninstall():
    global _INSTALLED

    if not _INSTALLED:
        return

    bpy.app.handlers.undo_post.remove(_post_undo_redo)
    bpy.app.handlers.redo_post.remove(_post_undo_redo)
    bpy.app.handlers.load_post.remove(_post_file_open)
    bpy.app.handlers.load_pre.remove(_pre_file_open)
    bpy.app.handlers.save_pre.remove(_on_save_pre)
    bpy.app.handlers.save_post.remove(_on_save_post)
    bpy.app.handlers.depsgraph_update_post.remove(_post_depsgraph_changed)

    # No longer relevant
    for _, collection in handlers.items():
        collection.clear()

    _INSTALLED = False


"""

Test Suite

"""


def test_handler_on_removed(_):
    pass


def test_handler_on_created(_):
    counter = {"#": 0}

    def on_created(xobj):
        counter["#"] += 1

    new()

    bpx.handlers["object_created"].append(on_created)

    try:
        create_object(e_empty_cube)
        assert_equal(counter["#"], 1)
        create_object(e_empty_cube)
        assert_equal(counter["#"], 2)
    finally:
        bpx.handlers["object_created"].remove(on_created)


def test_rename_object(_):
    bpx.new()
    box = bpx.create_object(e_empty_cube, "Name1")
    assert_equal(box.name(), "Name1")
    assert_true(box.handle() is not None)

    bpx.rename(box, "Name2")
    assert_equal(box.name(), "Name2")
    assert_true(box.handle() is not None)


def test_handler_on_destroyed(_):
    pass


def test_undo(_):
    pass


def test_new_file_destroyed(_):
    pass


def test_is_alive(_):
    new()

    xobj = bpx.create_object(e_empty_cube, name="Cube")

    assert_true(xobj.is_valid())
    assert_true(xobj.is_alive())

    bpx.delete(xobj)

    assert_true(not xobj.is_alive())


def is_background():
    import sys
    return "--background" in sys.argv


if __name__ == "__main__":
    import sys
    import unittest
    import doctest

    # For familiarity
    bpx = sys.modules[__name__]

    _BACKGROUND = True

    install()

    # unittest really wants tests to be methods,
    # but we don't.
    tests = {
        name: func
        for name, func in globals().items()
        if callable(func) and name.startswith("test_")
    }

    Tests = type("Tests", (unittest.TestCase,), tests)
    t = Tests()

    def assert_true(value):
        t.assertTrue(value)

    def assert_false(value):
        t.assertFalse(value)

    def assert_equal(first, second):
        t.assertEqual(first, second)

    # unittest can't just run the tests as-is,
    # they need a stupid "suite". So be it.
    suite = unittest.TestSuite()
    for test in tests:
        suite.addTest(Tests(test))

    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)

    # Test examples in each docstring too
    doctest.testmod()

    if not bpy.app.background:
        bpy.ops.wm.quit_blender()
