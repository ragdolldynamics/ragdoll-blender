import ragdollc

from ragdollc import registry

import os
import json

import bpy

from . import events, log, upgrade, util, viewport, commands
from .vendor import bpx

_dynamic_property_groups = {}

# Let each individual object type handle its own initialisation
post_constructors = {}


def create(typ, name) -> bpx.BpxType:
    """Create a new object to represent an entity

    Every entity in Ragdoll is represented by a bpy.types.Object
    created here.

    The entity is stored in the transient member `.data[]` and is
    thus not stored alongside the Blender file. Entities are
    always generated anew with each file-open and given a new unique ID.

    """

    xobj = bpx.create_object(bpx.e_empty, name, archetype=typ)

    obj = xobj.handle()

    if xobj.type() in ("rdMarker", "rdEnvironment"):
        # Moving these have no effect
        obj.lock_location = (True, True, True)
        obj.lock_rotation = (True, True, True)
        obj.lock_scale = (True, True, True)

    elif xobj.type() == "rdSolver":
        # Transforming these have no effect
        obj.lock_rotation = (True, True, True)

    # Nothing takes scale into consideration
    obj.lock_scale = (True, True, True)

    on_created(xobj)

    return xobj


@bpx.call_once
def deferred_install():
    # Deferred install of run-time callbacks and
    # other performance sensitive things
    events.install()

    rendererState = registry.ctx("RenderStateComponent")
    rendererState.api = rendererState.kOpenGL
    rendererState.depthOffset = 0.0001

    unit = registry.ctx("LinearUnit")
    unit.label = "m"
    unit.centimetersPerUnit = 100

    sceneAxis = registry.ctx("UpAxisIndex")
    sceneAxis.x = 0
    sceneAxis.y = 2
    sceneAxis.z = 1  # Blender is Z up

    # Not yet implemented
    features = registry.ctx("FeatureFlags")
    features.livePreferences = False
    features.interactiveMode = False


def on_created(xobj):
    """A new BpxObject has been created

    The lifecycle of BpxObjects are consistent with Blender objects,
    meaning they are created once and destroyed once an object has
    been permanently removed from the Blender scene.

    """

    typ = xobj.type()

    # Is this one of ours?
    if not typ:
        return

    deferred_install()

    try:
        post_constructors[typ](xobj)
    except KeyError:
        # Don't forget to make a `def post_constructor(xobj)`
        raise KeyError("No `post_constructor` for %s" % typ)


def on_destroyed(xobj):
    """A BpxObject has been destroyed

    This happens *after* the bpy.types.Object has been destroyed,
    meaning we cannot access properties or attributes from here.

    We can however access `.data` since that is stored alongside the
    Python object, which continues to exist until after this callback.

    """

    entity = xobj.data.get("entity", None)

    if entity is not None:
        ragdollc.registry.destroy(entity)


def on_execute_command(command):
    if command == "resetConstraintFrames":
        for marker in bpx.sl(type="rdMarker"):
            util.reset_constraint_frames(marker)

    elif command == "cacheAll":
        pass

    elif command == "uncache":
        pass

    elif command == "returnToStartFrame":
        commands.return_to_start()

    elif command == "transferLive":
        bpy.ops.ragdoll.snap_to_simulation()

    elif command == "keyframeLive":
        bpy.ops.ragdoll.snap_to_simulation()

    elif command == "liveUndo":
        pass

    # User events
    elif command == "ragdollExpiredEvent":
        pass

    elif command == "ragdollRecordingLimitEvent":
        pass

    elif command == "ragdollNonCommercialExportEvent":
        pass

    elif command == "ragdollLicenceDeactivatedEvent":
        bpy.ops.wm.read_homefile(use_empty=True)

    else:
        raise ValueError(
            "Unrecognised command: %s, this is a bug" % command
        )


@bpx.with_cumulative_timing
def on_mode_changed(previous, current):
    if previous in (bpx.EditMeshMode, bpx.SculptMode):
        if current in (bpx.ObjectMode, bpx.PoseMode):
            edited_mesh = bpx.selection(active=True)[0]
            on_mesh_edited(edited_mesh)


def on_mesh_edited(edited_mesh):
    """A mesh has been edited, update any associated Markers"""
    edited_entity = None

    # Since we cannot traverse backwards from mesh -> Marker,
    # we'll need to iterate over all Markers to find the mesh
    for entity in bpx.ls(type=("rdMarker", "rdEnvironment")):
        input_mesh = entity["inputGeometry"].read()

        if input_mesh is edited_mesh:
            edited_entity = entity
            break

    if not edited_entity:
        return

    edited_entity["inputGeometry"].touch()


@bpx.with_cumulative_timing
def post_object_removed_unremoved(xobj):
    """An object was removed from Blender

    This can be either a Marker, an assigned object
    or a completely unrelated Blender object.

    """

    xobj.dirty()
    entity = xobj.data.get("entity", None)

    # Is it one of ours? (can be None or 0)
    if not entity:
        return

    # Source and destination transforms also have a `entity`
    # and if that's the case we should also dirty the original
    # marker object.
    arch = registry.archetype(entity)
    if arch == "rdMarker":

        # Careful to avoid throwing an exception during this callback
        xmarker = bpx.alias(entity, None)

        if xmarker is not None:
            xmarker.dirty()

    touch_members()


def post_undo_redo():
    # An object may have been undeleted
    touch_members()


def touch_members():
    from .archetypes import solver

    for xsolver in bpx.ls(type="rdSolver"):
        entity = xsolver.data["entity"]
        ragdollc.scene.propertyChanged(entity, "members")

    # Keep viewport up to date
    viewport.add_evaluation_reason("members_changed")


def find_group(marker) -> bpx.BpxObject | None:
    """Find the group for `marker`

    """

    handle = marker.handle()

    if not handle:
        return

    # Groups take markers as input, and know which markers are
    # associated with it. But the relationship is unidirectional,
    # the Marker does not know what group they connect to.
    for group in bpx.ls(type="rdGroup"):
        for member in group["members"]:
            if member.object == handle:
                return group


def find_or_create_current_solver() -> bpx.BpxObject | None:
    # Prefer active selection
    solvers = bpx.selection("rdSolver", active=True)

    if solvers:
        return solvers[0]  # Can only have 1 active selection

    try:
        return next(bpx.ls_iter(type="rdSolver"))
    except StopIteration:
        return None


def post_file_open():
    # Ensure members are added prior to evaluating the solver
    # for the first time to avoid the initial flicker.
    from .archetypes import solver  # Avoid cyclic import

    # When installed, object creation is monitored and this happens
    # implicitly. But when not installed, we need to explicitly
    # instantiate these such that their callbacks are fired
    if not bpx.been_called(install):
        for obj in bpy.context.scene.objects:
            bpx.BpxType(obj)

    for xobj in bpx.ls(type="rdSolver"):
        entity = xobj.data.get("entity")
        solver.evaluate_members(entity)

    upgrade.upgrade_all()


def object_to_entity(xobj: bpy.types.Object) -> int:
    """Entities are stored in the transient metadata of its BpxType"""

    if not isinstance(xobj, bpx.BpxType):
        xobj = bpx.BpxObject(xobj)

    return xobj.data.get("entity", 0)


def object_to_marker(xobj: bpx.BpxType) -> bpx.BpxObject:
    """Return the marker associated with `xobj`"""

    entity = xobj.data.get("entity")
    if not entity:
        return

    xobj = bpx.alias(entity)
    if not xobj.is_alive():
        return

    return xobj


def source_to_object(source) -> bpx.BpxObject:
    """Convert a VectorPointerGroup to an object

    References from entity to Blender object comes in
    pairs of {"object", "bone"}

    """

    if isinstance(source, bpx.BpxType):
        return source

    if isinstance(source, bpx.BpxProperty):
        source = source.read()

    assert isinstance(source, bpy.types.PropertyGroup), (
        "Not a property group"
    )
    assert hasattr(source, "object") and hasattr(source, "boneid"), (
        dir(source)
    )

    obj = source.object

    if obj is None:
        raise bpx.ExistError("%s.object was empty" % source)

    if isinstance(obj.data, bpy.types.Armature):
        # Try the fast route first
        obj = bpx.find_bone_by_index(source.object, source.boneidx)

        # The slow route
        if not obj:
            obj = bpx.find_bone_by_uuid(source.object, source.boneid)

    if not obj:
        raise bpx.ExistError("Could not find the object for %s" % source)

    return bpx.BpxType(obj)


def make_update_callback(name, cls):
    def property_changed(property_group, _context):

        # The entity is stored in a transient variable
        # of the persistent object's `.data[]` dictionary
        xobj = bpx.BpxObject(property_group.id_data)
        entity = xobj.data.get("entity")

        # Make note for the developer
        if entity is None or entity < 0:
            # This would mean we monitor a property on
            # an object that is supposed to have a data[]
            # member for an entity. Not having that means
            # it hasn't yet been initialised, which means
            # we've missed a circumstance where objects
            # get created.
            #
            # Developer:
            #   Ensure ragdollc.create_* has been called
            #
            return log.debug(
                "There exists an object without "
                "a corresponding entity, this is a bug"
            )

        # Blender has more verbosity than we need
        # E.g. members.object and inputGeometry.object
        c_name = name.split(".")[0]

        # Dirty property for the next read()
        xobj[c_name].dirty()

        cls.on_property_changed(entity, c_name)

    return property_changed


def _PointerProperty(cls, namespace, subtype=None):
    """Property group for referencing an object or pose bone

    Arguments:
        cls: Property group class that owns this property. MUST have
            classmethod `on_property_changed(entity, name)` implemented
            for property update callback.
        namespace (str): Property name.
        subtype (list or str or None): The subtype of `bpy.types.Object`,
            e.g. "MESH", or ["MESH", "ARMATURE"]. Optional, default None.

    """

    type_name = "RdPointerPropertyGroup_%s" % cls.__name__
    if type_name not in _dynamic_property_groups:

        class RdPointerPropertyGroup(bpy.types.PropertyGroup):
            pass

        annotations = RdPointerPropertyGroup.__annotations__

        _poll = {}
        if subtype and isinstance(subtype, str):
            _poll["poll"] = lambda self, object: object.type == subtype
        if subtype and isinstance(subtype, list):
            _subtype = set(subtype)
            _poll["poll"] = lambda self, object: object.type in _subtype

        annotations["object"] = bpy.props.PointerProperty(
            name="Object Reference",
            type=bpy.types.Object,
            update=make_update_callback("%s.object" % namespace, cls),
            **_poll
        )
        annotations["boneid"] = bpy.props.StringProperty(
            name="Bpx Bone ID",
            update=make_update_callback("%s.boneid" % namespace, cls),
        )
        annotations["boneidx"] = bpy.props.IntProperty(
            name="Bone Index",
            update=make_update_callback("%s.boneidx" % namespace, cls),
            default=-1,
        )

        _dynamic_property_groups[type_name] = RdPointerPropertyGroup
        bpy.utils.register_class(RdPointerPropertyGroup)

    return _dynamic_property_groups[type_name]


def _EntityPropertyForCollection(cls, namespace):
    """Property group for referencing entity object in collection

    In Blender, the CollectionProperty represents an array.
    Blender does not have an `update` callback for CollectionProperty,
    only for members of a PropertyGroup. Furthermore, Blender cannot use
    a PropertyGroup unless first registered. Hence, complicating this
    particular property somewhat.

    Arguments:
        cls: Property group class that owns this property. MUST have
            classmethod `on_property_changed(entity, name)` implemented
            for property update callback.
        namespace (str): Property name.

    """

    type_name = "RdEntityPropertyGroup_%s" % cls.__name__
    if type_name not in _dynamic_property_groups:

        class RdEntityPropertyGroup(bpy.types.PropertyGroup):
            pass

        annotations = RdEntityPropertyGroup.__annotations__
        annotations["object"] = bpy.props.PointerProperty(
            name="Object",
            type=bpy.types.Object,
            update=make_update_callback("%s.object" % namespace, cls),
        )

        _dynamic_property_groups[type_name] = RdEntityPropertyGroup
        bpy.utils.register_class(RdEntityPropertyGroup)

    return _dynamic_property_groups[type_name]


def _inject_UIListIndexProperty(cls, property_name):
    """Add an extra index property for rendering collection in GUI

    To render a collection property in GUI panel with `bpy.types.UIList`
    class and `UILayout.template_list()`, we must also provide an extra
    property for memorizing active item's index in list UI.

    Arguments:
        cls: Property group class that owns this property
        property_name (str): Property name

    """

    ui_index = "%s_ui_index" % property_name
    cls.__annotations__[ui_index] = bpy.props.IntProperty()


class PropertyGroup(bpy.types.PropertyGroup):
    type = None

    @classmethod
    def touch_all_properties(cls, entity):
        """Initialise all properties in this group"""
        for name in cls.__annotations__:
            cls.on_property_changed(entity, name)

    @classmethod
    def on_property_changed(cls, entity, name):
        xobj = bpx.alias(entity, None)

        if xobj and name == "export":
            export = registry.get("ExportComponent", entity)
            export.value = xobj["export"].read()

        if xobj and name == "enabled":
            xobj = bpx.alias(entity)
            enabled = xobj["enabled"].read()

            if registry.archetype(entity) == "rdSolver":
                ui = registry.get("SolverUIComponent", entity)
                ui.enabled = enabled

            elif registry.archetype(entity) == "rdMarker":
                ui = registry.get("MarkerUIComponent", entity)
                ui.enabled = enabled

            elif registry.archetype(entity) == "rdGroup":
                ui = registry.get("GroupUIComponent", entity)
                ui.enabled = enabled

            elif registry.archetype(entity) == "rdEnvironment":
                ui = registry.get("EnvironmentUIComponent", entity)
                ui.enabled = enabled

            elif registry.archetype(entity) == "rdPinConstraint":
                ui = registry.get("PinJointUIComponent", entity)
                ui.enabled = enabled

            elif registry.archetype(entity) == "rdDistanceConstraint":
                ui = registry.get("DistanceJointUIComponent", entity)
                ui.enabled = enabled

            elif registry.archetype(entity) == "rdFixedConstraint":
                ui = registry.get("FixedJointUIComponent", entity)
                ui.enabled = enabled

            else:
                log.warning(
                    "%s is an unsupported archetype, this is a bug"
                    % registry.archetype(entity)
                )

            touch_members()

        if xobj is not None:
            xobj[name].dirty()

        ragdollc.scene.propertyChanged(entity, name)


def with_properties(fname):
    """Generate property annotations for Ragdoll property group

    Args:
        fname: JSON filename with properties

    """

    def wrapper(cls):
        dirname = os.path.dirname(__file__)  # ragdoll
        dirname = os.path.join(dirname, "resources", "archetypes")

        filepath = os.path.join(dirname, fname)

        with open(filepath, "r") as f:
            data = json.load(f)

        for name, spec in data["property"].items():
            options = spec["options"]

            # Ignore these, they are for internal C++ use only
            if options.get("internal", False):
                continue

            kwargs = spec["value"].copy()
            kwargs["name"] = spec["label"]
            kwargs["description"] = spec["help"]
            kwargs["update"] = make_update_callback(name, cls)

            # type def
            typ = kwargs.pop("type")
            if typ == "bool":
                Property = bpy.props.BoolProperty

            elif typ in ("int", "u_int", "u_short"):
                Property = bpy.props.IntProperty

            elif typ in ("float", "double"):
                Property = bpy.props.FloatProperty
                kwargs["step"] = 1
                kwargs["precision"] = 3

            elif typ in ("float[3]",
                         "double[3]",
                         "angle[3]",
                         "euler",
                         "color"):
                Property = bpy.props.FloatVectorProperty
                kwargs["size"] = 3
                kwargs["step"] = 1
                kwargs["precision"] = 3

            elif typ == "matrix":
                Property = bpy.props.FloatVectorProperty
                kwargs["size"] = (4, 4)
                kwargs["subtype"] = "MATRIX"
                kwargs["default"] = ((1, 0, 0, 0),
                                     (0, 1, 0, 0),
                                     (0, 0, 1, 0),
                                     (0, 0, 0, 1))

            # A pair of {"object": "bone"} for assigning a
            # Blender transform to a Marker
            elif typ == "pointer":
                # Use the name of the property as a namespace
                Property = bpy.props.PointerProperty
                subtype = kwargs.pop("subtype", None)
                kwargs.pop("update", None)  # Not relevant here
                kwargs["type"] = _PointerProperty(cls, name, subtype)

            # An array of pairs of [{"object": "bone"}]
            elif typ == "pointer[]":
                Property = bpy.props.CollectionProperty
                subtype = kwargs.pop("subtype", None)
                kwargs.pop("update", None)  # Not relevant here
                kwargs["type"] = _PointerProperty(cls, name, subtype)

            # Entities are represented as objects in Blender
            elif typ == "entity":
                # Use the name of the property as a namespace
                Property = bpy.props.PointerProperty
                kwargs["type"] = bpy.types.Object

            elif typ == "entity[]":
                Property = bpy.props.CollectionProperty
                kwargs.pop("update", None)  # Not relevant here
                kwargs["type"] = _EntityPropertyForCollection(cls, name)

            elif typ == "string":
                Property = bpy.props.StringProperty

            elif typ == "enum":
                Property = bpy.props.EnumProperty
                kwargs["items"] = [
                    (item, item, "", i) for i, item in kwargs.pop("items")
                ]
            else:
                raise TypeError(
                    f"Property {name!r} uses an unsupported type: "
                    f"{typ!r}"
                )

            if typ.endswith("[]"):
                _inject_UIListIndexProperty(cls, name)

            # Options
            kwargs["options"] = set()
            if options.get("hidden"):
                kwargs["options"].add("HIDDEN")  # Hide from Data API

            if options.get("animatable"):
                kwargs["options"].add("ANIMATABLE")

            # Everything overridable per default
            if typ == "pointer[]":
                kwargs["override"] = {"LIBRARY_OVERRIDABLE", "USE_INSERTION"}
            else:
                kwargs["override"] = {"LIBRARY_OVERRIDABLE"}

            # Install property
            cls.__annotations__[name] = Property(**kwargs)

        return cls

    return wrapper


def register_property_group(cls):
    bpy.utils.register_class(cls)

    # In Blender, properties are not added to individual objects,
    # but rather to *all* objects. Those objects interested in
    # the properties then make a concerted effort to access them
    # explicitly, while other objects simply ignore them.
    prop = bpy.props.PointerProperty(type=cls)
    setattr(bpy.types.Object, cls.type, prop)


def unregister_property_group(cls):
    bpy.utils.unregister_class(cls)
    delattr(bpy.types.Object, cls.type)


@bpx.call_once
def install():
    bpx.handlers["object_created"].append(on_created)
    bpx.handlers["object_destroyed"].append(on_destroyed)
    bpx.handlers["object_removed"].append(post_object_removed_unremoved)
    bpx.handlers["object_unremoved"].append(post_object_removed_unremoved)
    bpx.handlers["mode_changed"].append(on_mode_changed)

    # Allow uninstall to be called again
    bpx.unset_called(uninstall)


@bpx.call_once
def uninstall():
    # bpx handlers uninstalled via bpx.uninstall()

    # NOTE: Do not uninstall the "_dynamic_property_groups"
    # WHY: Don't know :blush: Things just explode. Feel free to investigate!

    bpx.unset_called(install)
    bpx.unset_called(deferred_install)
