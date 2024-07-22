import re
import os
import json
import copy
import ragdollc

import bpy

from . import log, constants, scene, util
from .vendor import bpx


def load(fname, **opts):
    loader = Loader(opts)
    loader.read(fname)
    return loader.load()


def reinterpret(fname, **opts):
    loader = Loader(opts)
    loader.read(fname)
    return loader.reinterpret()


def export(fname=None, data=None, opts=None):
    """Export everything Ragdoll-related into `fname`

    Arguments:
        fname (str, optional): Write to this file,
            or console if no file is provided
        data (dict, optional): Export this dictionary instead

    Returns:
        data (dict): Exported data as a dictionary

    """

    opts = dict({
        "animation": False,
        "simulation": False,
    }, **(opts or {}))

    initial_frame = bpy.context.scene.frame_current

    # Ensure the solver is initialised
    for solver in bpx.ls(type="rdSolver"):
        entity = solver.data["entity"]
        Time = ragdollc.registry.get("TimeComponent", entity)
        bpy.context.scene.frame_set(Time.startFrame)
        ragdollc.scene.evaluate(entity)

    data = json.loads(ragdollc.registry.dump())
    data = make_backwards_compatible(data)
    data = patch_source_destination_paths(data)

    if fname and not fname.endswith(".rag"):
        fname += ".rag"

    if fname is not None:
        with open(fname, "w") as f:
            json.dump(data, f, indent=4, sort_keys=True)

    bpy.context.scene.frame_set(initial_frame)

    return data


class Entity(int):
    pass


def _value_to_type(value):
    if isinstance(value, (list, tuple)):
        value = [_value_to_type(v) for v in value]

    elif not isinstance(value, dict):
        pass

    elif value["type"] == "Entity":
        value = Entity(value["value"])

    elif value["type"] == "Vector3":
        value = bpx.Vector(value["values"])

    elif value["type"] == "Color4":
        r, g, b, a = value["values"]
        value = bpx.Color((r, g, b))

    elif value["type"] == "Matrix44":
        _ = value["values"]
        value = bpx.Matrix([
            [_[0], _[4], _[8], _[12], ],
            [_[1], _[5], _[9], _[13], ],
            [_[2], _[6], _[10], _[14], ],
            [_[3], _[7], _[11], _[15], ],
        ])

    elif value["type"] == "Path":
        value = value["value"]

    elif value["type"] == "Quaternion":
        x, y, z, w = value["values"]
        value = bpx.Quaternion((w, x, y, z))

    elif value["type"] == "PointArray":
        values = []

        # Values are stored flat; every 3 values represent an Point
        stride = 0
        for _ in range(len(value["values"]) // 3):
            values.append(bpx.Vector((
                value["values"][stride + 0],
                value["values"][stride + 1],
                value["values"][stride + 2],
            )))

            stride += 3
        value = values

    elif value["type"] == "UintArray":
        value = value["values"]

    else:
        raise TypeError("Unsupported type: %s" % value)

    return value


def Component(comp):
    """Simplified access to component members"""

    data = {}

    for key, value in comp["members"].items():
        if isinstance(value, (dict, list, tuple)):
            value = _value_to_type(value)

        data[key] = value

    return data


class Registry(object):
    def __init__(self, dump=None):
        if dump is None:
            dump = {
                "entities": {}
            }

        dump = copy.deepcopy(dump)
        dump["entities"] = {

            # Original JSON stores keys as strings, but the original
            # keys are integers; i.e. entity IDs
            Entity(entity): value
            for entity, value in dump["entities"].items()
        }

        self._dump = dump

    def count(self, *components):
        """Return number of entities with this component(s)"""
        return len(list(self.view(*components)))

    def view(self, *components):
        """Iterate over every entity that has all of `components`"""
        for entity in self._dump["entities"]:
            if all(self.has(entity, comp) for comp in components):
                yield entity

    def has(self, entity, component):
        """Return whether `entity` has `component`"""
        assert isinstance(entity, int), "entity must be int"
        assert isinstance(component, str), (
            "component must be string")
        return component in self._dump["entities"][entity]["components"]

    def ctx(self, component):
        """Return whether `entity` has `component`"""
        assert isinstance(component, str), (
            "component must be string")

        # Added in 2024.01.25
        ctx = self._dump.get("context", {
            "LinearUnit": {
                "type": "LinearUnit",
                "members": {
                    "label": "cm",
                    "centimetersPerUnit": 1.0
                }
            }
        })

        return Component(ctx[component])

    def get(self, entity, component):
        """Return `component` for `entity`

        Returns:
            dict: The component

        Raises:
            KeyError: if `entity` does not have `component`

        """
        components = {}
        try:
            components = self._dump["entities"][entity]["components"]
            return Component(components[component])

        except KeyError as e:
            if self.has(entity, "NameComponent"):
                Name = self.get(entity, "NameComponent")
                name = Name["path"] or Name["value"]
            else:
                name = "Entity: %d" % entity

            raise KeyError(
                "%s did not have '%s' (%s) {%s}" % (
                    name, component, e, ", ".join(components.keys())
                )
            )

    def components(self, entity):
        """Return *all* components for `entity`"""
        return self._dump["entities"][entity]["components"]


def patch_source_destination_paths(json):
    """For backwards compatibility, remove characters unsupported by Maya"""

    def clean(text):
        return re.sub(r'[^a-zA-Z0-9]', '_', text)

    for entity, value in json["entities"].items():
        if "MarkerUIComponent" in value["components"]:
            marker_ui = value["components"]["MarkerUIComponent"]
            members = marker_ui["members"]
            members["sourceTransform"] = clean(members["sourceTransform"])

            for index, name in enumerate(members["destinationTransforms"][:]):
                members["destinationTransforms"][index] = clean(name)

        if "NameComponent" in value["components"]:
            Name = value["components"]["NameComponent"]
            Name["members"]["value"] = clean(Name["members"]["value"])

    return json


def make_backwards_compatible(json):
    """2024.04.09 removed the "absolute" subentity"""

    # We'll add a mock entity, carrying a mock component
    # such that exports can be imported/loaded in Maya
    absolute_entity = 0xffff0000

    # Find an unoccupied ID
    while str(absolute_entity) in json["entities"]:
        absolute_entity += 1

    json["entities"][str(absolute_entity)] = {
        "components": {
            "NameComponent": {
                "members": {
                    "path": "",
                    "shortestPath": "",
                    "value": "Backwards Compatibility"
                },
                "type": "NameComponent"
            },
            "DriveComponent": {
                "members": {},
                "type": "DriveComponent"
            }
        },
        "id": absolute_entity
    }

    for entity, value in json["entities"].items():
        for key, comp in value["components"].items():
            if key == "SubEntitiesComponent":
                comp["members"].update({
                    "absolute": {
                        "type": "Entity",
                        "value": absolute_entity
                    }
                })

    return json


def _name(path, level=1):
    # TODO: Assuming Maya convention for paths here
    # Convert to Ragdoll Standard `/`
    path = path.replace("|", "/")

    names = path.split("/")

    # Keep adding levels of hierarchy until unique
    # If the path is truly unique, this will be enough
    if level < len(names):
        name = "/".join(names[-level:])

    # If the path is not unique, we need to keep appending numbers
    # e.g. /root/joint1/joint1/joint11
    else:
        name = path + str(level - len(names) + 1)

    # TODO: Assuming Maya *namespace*, bad
    name = name.rsplit(":", 1)[-1]

    if len(name) > 63:
        log.warning("Longer than 63 chars: %s")

    return name


def DefaultDump():
    return {
        "schema": Loader.SupportedSchema,
        "entities": {},
        "info": {}
    }


def DefaultState():
    return {

        # Series of solver entities
        "solvers": [],

        # Series of group entities
        "groups": [],

        # Series of collision group entities
        "collisionGroups": [],

        # Series of markers entities
        "markers": [],

        # Transforms that are already assigned
        "occupied": [],

        # Constraints of all sorts
        "constraints": [],

        # Map entity -> active Blender Object
        "entityToTransform": {},

        # Map entity -> active Ragdoll node
        "entityToNode": {},

        # Markers without a transform
        "missing": [],

        # Paths used to search for each marker
        "searchTerms": {},

        # Map entity to a unique name
        "entityToName": {},
    }


def _write(xobj, attr, value):
    """Tolerate being unable to set an attribute, favouring those that work

    It's possible and acceptable to miss attributes, if it means
    the majority of the import works alright.

    """

    try:
        xobj[attr] = value
    except Exception:  # noqa
        bpx.warning("Could not set '%s.%s=%s'" % (xobj, attr, value))


class Loader(object):
    """Reconstruct physics from a Ragdoll dump

    A "dump" is the internal data of the Ragdoll plug-in.

    This loader reconstructs a Blender scene such that the results
    are the same as when the dump was originally created.

    Arguments:
        roots (list): Path(s) that the original path must match
        replace (list): Search/replace pairs of strings to find and replace
            in each original path
        overrideSolver (path): Use this solver instead of the one from the file

    """

    SupportedSchema = "ragdoll-1.0"

    def __init__(self, opts=None):
        opts = dict({
            "roots": [],
            "matchBy": constants.MatchByHierarchy,
            "searchAndReplace": ["", ""],
            "namespace": None,
            "preserveAttributes": True,
            "retarget": True,

            "overrideSolver": "",
            "createMissingTransforms": False,
        }, **(opts or {}))

        self._opts = opts

        # Do we need to re-analyse before use?
        self._dirty = True

        # Is the data valid, e.g. no null-entities?
        self._invalid_reasons = []

        # Transient data, updated on changes to fname and filtering
        self._state = DefaultState()

        self._registry = Registry()

        # Original dump
        self._dump = None

        # Default, in case data is passed in directly rather than a file
        self._current_fname = "character"

    def count(self):
        return len(self._state["entityToTransform"])

    @property
    def registry(self):
        return self._registry

    def dump(self):
        return copy.deepcopy(self._dump)

    def edit(self, options):
        self._opts.update(options)
        self._dirty = True

    def read(self, fname):
        assert fname, "Empty `fname`."
        self._invalid_reasons[:] = []

        dump = DefaultDump()

        if isinstance(fname, dict):
            # Developer-mode, bypass everything and use as-is
            dump = fname

        else:
            try:
                with open(fname) as f:
                    dump = json.load(f)
                self._current_fname = fname

            except Exception as e:
                error = (
                    "An exception was thrown when attempting to read %s\n%s"
                    % (fname, str(e))
                )

                self._invalid_reasons += [error]

        assert "schema" in dump and dump["schema"] == self.SupportedSchema, (
            "Dump not compatible with this version of Ragdoll"
        )

        self._registry = Registry(dump)
        self._dump = dump
        self._dirty = True

        # TEMP
        fname = os.path.basename(self._current_fname)
        fname, _ = os.path.splitext(fname)
        armature_name = fname
        self._opts["armature"] = armature_name

        # Preprocess source transform names
        # They are not guaranteed to be unique
        #
        # E.g.
        #
        # /joint2/joint2
        # /joint1/joint2/joint2
        # /joint3/joint2
        #
        unique_names = set()
        entity_to_name = {}
        for entity in self._registry.view("MarkerUIComponent"):
            MarkerUi = self._registry.get(entity, "MarkerUIComponent")
            path = MarkerUi["sourceTransform"]
            name = _name(path)

            level = 1
            while name in unique_names:
                level += 1
                name = _name(path, level)

            assert name not in unique_names, "%s was not unique!"
            unique_names.add(name)

            entity_to_name[entity] = name

        self._entity_to_name = entity_to_name

    def is_valid(self):
        return len(self._invalid_reasons) == 0

    def invalid_reasons(self):
        """Return reasons for failure, useful for reporting"""
        return self._invalid_reasons[:]

    def create(self, armature):
        assert isinstance(armature, bpx.BpxArmature), (
            "%s was not a BpxArmature" % armature
        )

        seen = {}
        entity_to_bone = {}

        def lock_child(pose_bone, linear_motion):
            if linear_motion == "Inherit":
                Group = self._registry.get(entity, "GroupComponent")
                try:
                    GroupUi = self._registry.get(
                        Group["entity"], "GroupUIComponent"
                    )
                except KeyError:
                    pass
                else:
                    linear_motion = GroupUi.get("linearMotion", "Locked")

            if linear_motion == "Locked":
                pose_bone.lock_location[0] = True
                pose_bone.lock_location[1] = True
                pose_bone.lock_location[2] = True

            # Synchronise locked Maya channels with limits
            Subs = self._registry.get(entity, "SubEntitiesComponent")
            Limit = self._registry.get(Subs["relative"], "LimitComponent")

            if Limit["enabled"] and Limit["twist"] < 0:
                pose_bone.lock_rotation[0] = True

            if Limit["enabled"] and Limit["swing1"] < 0:
                pose_bone.lock_rotation[1] = True

            if Limit["enabled"] and Limit["swing2"] < 0:
                pose_bone.lock_rotation[2] = True

        def lock_root(pose_bone):
            pose_bone.lock_scale[0] = True
            pose_bone.lock_scale[1] = True
            pose_bone.lock_scale[2] = True

        def recursive_create(entity):
            if entity in seen:
                return

            # Avoid cycles
            seen[entity] = True

            Rigid = self._registry.get(entity, "RigidComponent")
            MarkerUi = self._registry.get(entity, "MarkerUIComponent")
            Rest = self._registry.get(entity, "RestComponent")
            Scale = self._registry.get(entity, "ScaleComponent")

            # Added in 2023.10.12
            if self._registry.has(entity, "ParentComponent"):
                parent = self._registry.get(entity, "ParentComponent")
                parent = parent["entity"]
            else:
                parent = Rigid["parentRigid"]

            # Ensure we have an entity_to_bone the parent already
            if parent and parent not in entity_to_bone:
                recursive_create(parent)

            bone_name = self._entity_to_name[entity]

            with bpx.edit_mode(armature):
                data = armature.handle().data
                edit_bone = data.edit_bones.new(bone_name)

                # These names are guaranteed unique, otherwise it is a bug
                if bone_name != edit_bone.name:
                    raise ValueError(
                        "Bone name was changed: %s -> %s, this is a bug"
                        % (bone_name, edit_bone.name)
                    )

                pose_mtx = bpx.Matrix.LocRotScale(
                    Rest["matrix"].to_translation(),
                    Rest["matrix"].to_quaternion(),
                    Scale["value"],
                )

                edit_mtx = pose_mtx

                if parent:
                    ParentRest = self._registry.get(parent, "RestComponent")
                    ParentScale = self._registry.get(parent, "ScaleComponent")
                    parent_mtx = bpx.Matrix.LocRotScale(
                        ParentRest["matrix"].to_translation(),
                        ParentRest["matrix"].to_quaternion(),
                        ParentScale["value"],
                    )
                    parent_scale_mtx = bpx.Matrix.Diagonal(
                        ParentScale["value"]
                    ).to_4x4()

                    # Remove parent scale from edit bone
                    edit_mtx = (
                        parent_mtx @
                        parent_scale_mtx.inverted() @
                        parent_mtx.inverted() @
                        edit_mtx
                    )

                edit_bone.matrix = edit_mtx

                up = bpx.Vector((0, 1, 0))
                orient = edit_mtx.to_quaternion() @ up
                edit_bone.tail = edit_bone.head + orient

                if parent:
                    parent_bone = entity_to_bone[parent]
                    parent_bone = data.edit_bones[parent_bone]
                else:
                    parent_bone = None

                edit_bone.use_connect = False
                edit_bone.parent = parent_bone

            with bpx.pose_mode(armature):
                # Setup pose bone next, can't edit
                # these without switching to Pose mode.
                pose = armature.handle().pose
                pose_bone = pose.bones[bone_name]
                pose_bone.matrix = pose_mtx
                pose_bone.rotation_mode = "XYZ"

                if parent:
                    linear_motion = MarkerUi.get("linearMotion", "Locked")
                    lock_child(pose_bone, linear_motion)
                else:
                    lock_root(pose_bone)

            entity_to_bone[entity] = bone_name

        # Create bones
        with bpx.object_mode():
            for entity in self._registry.view("MarkerUIComponent"):
                recursive_create(entity)

        return entity_to_bone

    @bpx.with_cumulative_timing
    def analyse(self):
        """Fill internal state from dump with something we can use"""

        # No need for needless work
        if not self._dirty:
            return self._state

        # Clear previous results
        self._state = DefaultState()

        self._find_constraints()
        self._find_solvers()
        self._find_groups()
        self._find_markers()
        self._find_collision_groups()

        self.validate()

        self._dirty = False
        return self._state

    def validate(self):
        reasons = []
        self._invalid_reasons[:] = reasons

    def report(self):
        if self._dirty:
            self.analyse()

        def name_(entity_):
            Name = self._registry.get(entity_, "NameComponent")
            return Name["value"]

        solvers = self._state["solvers"]
        groups = self._state["groups"]
        constraints = self._state["constraints"]
        colgroups = self._state["collisionGroups"]
        markers = self._state["entityToTransform"]

        if solvers:
            bpx.info("Solvers:")
            for entity in solvers:
                bpx.info("  %s.." % name_(entity))

        if groups:
            bpx.info("Groups:")
            for entity in groups:
                bpx.info("  %s.." % name_(entity))

        if colgroups:
            bpx.info("Collision Groups:")
            for entity in colgroups:
                bpx.info("  %s.." % name_(entity))

        if markers:
            bpx.info("Markers:")
            for entity, transform in markers.items():
                bpx.info("  %s -> %s.." % (name_(entity), transform))

        if constraints:
            bpx.info("Constraints:")
            for entity in constraints:
                bpx.info("  %s.." % name_(entity))

        if not any([solvers, groups, constraints, markers]):
            bpx.warning("Dump was empty")

    @bpx.with_undo_chunk
    @bpx.with_cumulative_timing
    def load(self):
        # TEMP
        armature_name = self._opts["armature"]

        # One Armature to rule them all
        armature = bpx.create_object(bpx.e_armature_empty, name=armature_name)
        armature.handle().data.display_type = "STICK"

        # Update armature name
        armature_name = armature.name()
        self._opts["armature"] = armature_name

        # Assembly
        assembly = bpx.create_collection(armature_name + ":Rig")
        assembly_geo = bpx.create_collection(armature_name + ":Geometry",
                                             assembly)
        bpx.link(armature, assembly)

        # Create transform hierarchy
        entity_to_bone = self.create(armature)

        # Create meshes
        bone_to_mesh = {}
        for entity, bone_name in entity_to_bone.items():
            MarkerUi = self._registry.get(entity, "MarkerUIComponent")

            path = MarkerUi["inputGeometryPath"]
            if not path:
                continue

            name = _name(path)
            mesh = self._create_mesh(entity, name)

            bone_to_mesh[bone_name] = mesh
            assembly_geo.objects.link(mesh.handle())

            bone = armature.handle().pose.bones[bone_name]
            con = bpx.create_constraint(mesh, "CHILD_OF")
            con.target = armature.handle()
            con.subtarget = bone.name

            # Geometry is already stored in the frame of the Marker
            con.inverse_matrix = bpx.Matrix()

        out = self.reinterpret()

        # Make sure created geometries are visible
        for marker in out["markers"]:
            mesh = marker["inputGeometry"].read()

            if not mesh:
                continue

            if not mesh.collections():
                assembly_geo.objects.link(mesh.handle())

            if mesh in bone_to_mesh.values():
                # Matrix is baked into the exported vertices
                _write(marker, "inputGeometryMatrix", bpx.Matrix())

        # Convert to Blender's Z-up
        if self._dump["info"]["upAxis"] == "y":
            handle = armature.handle()
            handle.rotation_mode = "XYZ"  # As opposed to quaternions
            handle.rotation_euler[0] = bpx.radians(90)

        # Make it active
        bpy.context.view_layer.objects.active = armature.handle()
        armature.handle().select_set(True)

        return self

    @bpx.with_undo_chunk
    @bpx.with_cumulative_timing
    def reinterpret(self, dry_run=False):
        """Interpret dump back into the UI-commands used to create them.

        For example, if two chains were created using the `Active Chain`
        command, then this function will attempt to figure this out and
        call `Active Chain` on the original controls.

        Unlike `load` this method reproduces what the artist did in order
        to author the rigids and constraints. The advantage is closer
        resemblance to newly authored chains and rigids, at the cost of
        less accurately capturing custom constraints and connections.

        Caveat:
            Imports are made using the current version of Ragdoll and its
            tools. Meaning that if a tool - e.g. create_chain - has been
            updated since the export was made, then the newly imported
            physics will be up-to-date but not necessarily the same as
            when it got exported.

        """

        # In case the user forgot or didn't know
        if self._dirty:
            self.analyse()

        if dry_run:
            return self.report()

        if not self.is_valid():
            return bpx.error("Dump not valid")

        if self._opts["createMissingTransforms"]:
            self._create_missing_transforms()

        rdsolvers = self._create_solvers()
        rdgroups = self._create_groups(rdsolvers)
        rdmarkers = self._create_markers(rdgroups, rdsolvers)
        rdcolgroups = self._create_collision_groups(rdmarkers)
        rdconstraints = self._create_constraints(rdmarkers)

        self._dirty = True
        bpx.info("Done")

        return {
            "solvers": rdsolvers.values(),
            "groups": rdgroups.values(),
            "markers": rdmarkers.values(),
            "constraints": rdconstraints.values(),
            "collisionGroups": rdcolgroups.values(),
        }

    @bpx.with_undo_chunk
    @bpx.with_cumulative_timing
    def update(self):
        pass

    @bpx.with_cumulative_timing
    def _create_mesh(self, entity, name):
        Desc = self._registry.get(entity, "GeometryDescriptionComponent")
        offset = bpx.Matrix.LocRotScale(
            Desc["offset"],
            Desc["rotation"],
            bpx.Vector((1, 1, 1)),
        )

        if Desc["type"] == "Box":
            mesh = bpx.poly_cube(name,
                                 Desc["extents"],
                                 offset=offset)

        elif Desc["type"] == "Sphere":
            mesh = bpx.poly_sphere(name,
                                   Desc["radius"],
                                   offset=offset)

        elif Desc["type"] == "Capsule":
            mesh = bpx.poly_capsule(name,
                                    Desc["length"],
                                    Desc["radius"],
                                    offset=offset)

        elif Desc["type"] == "ConvexHull":
            # Added in 2022.07.20
            if self._registry.has(entity, "ConvexMeshComponents"):
                Meshes = self._registry.get(entity, "ConvexMeshComponents")
                Scale = self._registry.get(entity, "ScaleComponent")
                mesh = meshes_to_obj(name, Meshes, Scale["value"])

            else:
                mesh = bpx.poly_capsule(name,
                                        Desc["length"],
                                        Desc["radius"],
                                        offset=offset)

        else:
            raise ValueError("Unsupported shape type: %s" % Desc["type"])

        return mesh

    @bpx.with_cumulative_timing
    def _create_missing_transforms(self):
        missing = self._state["missing"]

        if not missing:
            return

        bpx.info("Creating missing transforms..")

        # ...

    @bpx.with_cumulative_timing
    def _create_solvers(self):
        bpx.info("Creating solver(s)..")

        rdsolvers = {}

        unoccupied_markers = list(self._state["markers"])
        for marker in self._state["occupied"]:
            unoccupied_markers.remove(marker)

        for marker in unoccupied_markers:
            if marker not in self._state["entityToTransform"]:
                unoccupied_markers.remove(marker)

        for entity in self._state["solvers"]:
            if self._opts["overrideSolver"]:
                solver_name = self._opts["overrideSolver"]
                rdsolver = bpx.find(solver_name)

                if not rdsolver or rdsolver.type() != "rdSolver":
                    # If the user requested to override it, they likely
                    # intended to stop if it could not be found.
                    raise bpx.ExistError(
                        "Overridden solver %s could not be found"
                        % solver_name
                    )
                else:
                    rdsolvers[entity] = rdsolver
                    continue

            # Ensure there is at least 1 marker in it
            is_empty = True
            for marker in unoccupied_markers:
                Scene = self._registry.get(marker, "SceneComponent")
                if Scene["entity"] == entity:
                    is_empty = False
                    break

            if is_empty:
                bpx.warning(
                    "Solver '%s' was skipped due to being empty" % entity
                )
                continue

            Name = self._registry.get(entity, "NameComponent")
            name = Name["value"]
            rdsolver = scene.create("rdSolver", name)
            rdsolvers[entity] = rdsolver

            bpx.link(rdsolver, util.find_assembly())

        # Don't apply attributes from solver if the solver
        # already existed in the scene.
        override = self._opts["overrideSolver"]

        if self._opts["preserveAttributes"] and not override:
            for entity, rdsolver in rdsolvers.items():
                try:
                    self._apply_solver(entity, rdsolver)
                except KeyError as e:
                    # Don't let poorly formatted JSON get in the way
                    bpx.warning("Could not restore attribute: %s.%s"
                                % (rdsolver, e))

        return rdsolvers

    @bpx.with_cumulative_timing
    def _create_groups(self, rdsolvers):
        bpx.info("Creating group(s)..")

        unoccupied_markers = list(self._state["markers"])
        for marker in self._state["occupied"]:
            unoccupied_markers.remove(marker)

        for marker in unoccupied_markers:
            if marker not in self._state["entityToTransform"]:
                unoccupied_markers.remove(marker)

        rdgroups = {}

        for entity in self._state["groups"]:
            Scene = self._registry.get(entity, "SceneComponent")
            rdsolver = rdsolvers.get(Scene["entity"])

            if not rdsolver:
                # Exported group wasn't part of an exported solver
                # This would be exceedingly rare.
                continue

            # Ensure there is at least 1 marker in it
            is_empty = True
            for marker in unoccupied_markers:
                Group = self._registry.get(marker, "GroupComponent")
                if Group["entity"] == entity:
                    is_empty = False
                    break

            if is_empty:
                continue

            Name = self._registry.get(entity, "NameComponent")

            # E.g. |someCtl_rGroup
            name = Name["value"]

            rdgroup = scene.create("rdGroup", name)
            rdgroups[entity] = rdgroup

            rdsolver["members"].append({"object": rdgroup.handle()})
            bpx.link(rdgroup, util.find_assembly())

        if self._opts["preserveAttributes"]:
            for entity, rdgroup in rdgroups.items():
                try:
                    self._apply_group(entity, rdgroup)
                except KeyError as e:
                    # Don't let poorly formatted JSON get in the way
                    bpx.warning("Could not restore attribute: %s.%s"
                                % (rdgroup, e))

        return rdgroups

    @bpx.with_cumulative_timing
    def _create_markers(self, rdgroups, rdsolvers):
        bpx.info("Creating marker(s)..")
        rdmarkers = {}

        ordered_markers = []
        unoccupied_markers = list(self._state["markers"])

        for marker in self._state["occupied"]:
            unoccupied_markers.remove(marker)

        armature_name = self._opts["armature"]
        armature = bpx.find(armature_name)
        assert armature, "%s armature not found, this is a bug" % armature_name

        with bpx.pose_mode(armature):
            for entity in unoccupied_markers:
                bone = self._state["entityToTransform"].get(entity)

                if not bone:
                    bpx.warning("Skipped %s due to missing bone" % entity)
                    continue

                Scene = self._registry.get(entity, "SceneComponent")
                rdsolver = rdsolvers.get(Scene["entity"])

                if not rdsolver:
                    # Exported marker wasn't part of an exported solver
                    continue

                Name = self._registry.get(entity, "NameComponent")
                name = Name["value"]

                rdmarker = scene.create("rdMarker", name)
                bpx.link(rdmarker, util.find_assembly())

                transform = {
                    "object": bone.handle(),
                    "boneid": bone.boneid(),
                    "boneidx": bone.boneidx(),
                }

                rdmarker["sourceTransform"] = transform
                rdmarker["destinationTransforms"].append(transform)
                rdsolver["members"].append({"object": rdmarker.handle()})

                rdmarkers[entity] = rdmarker
                ordered_markers.append((entity, rdmarker))

        if not rdmarkers:
            return rdmarkers

        if self._opts["preserveAttributes"]:
            for entity, rdmarker in rdmarkers.items():
                try:
                    self._apply_marker(entity, rdmarker)
                except KeyError as e:
                    # Don't let poorly formatted JSON get in the way
                    bpx.warning("Could not restore attribute: %s" % e)

        bpx.info("Adding to group(s)..")

        for entity, rdmarker in ordered_markers:
            Group = self._registry.get(entity, "GroupComponent")
            rdgroup = rdgroups.get(Group["entity"])

            if rdgroup is None:
                continue

            rdgroup["members"].append({"object": rdmarker.handle()})

        bpx.info("Reconstructing hierarchy..")

        for entity, rdmarker in ordered_markers:
            Subs = self._registry.get(entity, "SubEntitiesComponent")
            Joint = self._registry.get(Subs["relative"], "JointComponent")
            parent_entity = Joint["parent"]

            if parent_entity:
                # A parent was exported, but hasn't yet been created
                if parent_entity not in rdmarkers:
                    bpx.debug(
                        "Missing parent, likely due to partial import"
                    )
                    continue

                parent_rdmarker = rdmarkers[parent_entity]
                rdmarker["parentMarker"] = parent_rdmarker.handle()

        return rdmarkers

    @bpx.with_cumulative_timing
    def _create_collision_groups(self, rdmarkers):
        bpx.info("Creating collision group(s)..")
        rdcolgroups = {}

        # ...

        return rdcolgroups

    @bpx.with_cumulative_timing
    def _create_constraints(self, rdmarkers):
        bpx.info("Creating constraint(s)..")
        rdconstraints = {}

        # ...

        return rdconstraints

    @bpx.with_cumulative_timing
    def _find_constraints(self):
        constraints = self._state["constraints"]
        constraints[:] = []

        for entity in self._registry.view("DistanceJointUIComponent"):
            constraints.append(entity)

        for entity in self._registry.view("PinJointUIComponent"):
            constraints.append(entity)

        for entity in self._registry.view("FixedJointComponent"):
            constraints.append(entity)

    @bpx.with_cumulative_timing
    def _find_solvers(self):
        solvers = self._state["solvers"]
        solvers[:] = []

        for entity in self._registry.view("SolverUIComponent"):
            solvers.append(entity)

    @bpx.with_cumulative_timing
    def _find_groups(self):
        groups = self._state["groups"]

        groups[:] = []

        for entity in self._registry.view("GroupUIComponent"):
            groups.append(entity)

        # Re-establish creation order
        def sort(entity_):
            order = self._registry.get(entity_, "OrderComponent")
            return order["value"]

        groups[:] = sorted(groups, key=sort)

    @bpx.with_cumulative_timing
    def _find_collision_groups(self):
        colgroups = self._state["collisionGroups"]
        colgroups[:] = []

        for entity in self._registry.view("CollisionGroupComponent"):
            colgroups.append(entity)

    @bpx.with_cumulative_timing
    def _find_markers(self):
        """Find and associate each entity with a Blender transform"""
        markers = self._state["markers"]
        occupied = self._state["occupied"]
        missing = self._state["missing"]
        entity_to_transform = self._state["entityToTransform"]

        armature_name = self._opts["armature"]
        armature = bpx.find(armature_name)

        for entity in self._registry.view("MarkerUIComponent"):
            # Collected regardless
            markers.append(entity)

            # Find original path, minus the rigid
            # E.g. |rMarker_upperArm_ctl -> |root_grp|upperArm_ctrl
            bone_name = self._entity_to_name[entity]
            bone = bpx.BpxBone(armature.handle().pose.bones[bone_name])

            if bone is None:
                # Transform wasn't found in this scene, that's OK.
                # It just means it can't actually be loaded onto anything.
                missing.append(entity)
                continue

            # Avoid assigning to already assigned transforms
            elif bone in entity_to_transform.values():
                occupied.append(entity)

            elif scene.object_to_marker(bone):
                occupied.append(entity)

            entity_to_transform[entity] = bone

        # Re-establish creation order
        def sort(entity_):
            order = self._registry.get(entity_, "OrderComponent")
            return order["value"]

        markers[:] = sorted(markers, key=sort)

    @bpx.with_cumulative_timing
    def _apply_solver(self, entity, solver):
        LinearUnit = self._registry.ctx("LinearUnit")
        Solver = self._registry.get(entity, "SolverComponent")
        SolverUi = self._registry.get(entity, "SolverUIComponent")
        unit_scale_factor = 100 / LinearUnit["centimetersPerUnit"]

        frameskip_method = {
            "Pause": 0,
            "Ignore": 1,
        }.get(Solver["frameskipMethod"], 0)

        solver_type = {
            "PGS": 0,
            "TGS": 1,
        }.get(Solver["type"], 1)

        collision_type = {
            "SAT": 0,
            "PCM": 1,
        }.get(Solver["collisionDetectionType"], 1)

        gravity = Solver["gravity"]

        if self._dump["info"]["upAxis"] == "y":
            old_y = gravity.y
            gravity.y = gravity.z
            gravity.z = old_y

        gravity /= unit_scale_factor

        _write(solver, "solverType", solver_type)
        _write(solver, "frameskipMethod", frameskip_method)
        _write(solver, "collisionDetectionType", collision_type)
        _write(solver, "enabled", Solver["enabled"])
        _write(solver, "airDensity", Solver["airDensity"])
        _write(solver, "gravity", gravity)
        _write(solver, "substeps", Solver["substeps"])
        _write(solver, "timeMultiplier", Solver["timeMultiplier"])
        _write(solver, "lod", Solver["lod"])
        _write(solver, "positionIterations", Solver["positionIterations"])
        _write(solver, "velocityIterations", Solver["velocityIterations"])
        _write(solver, "linearLimitStiffness", SolverUi["linearLimitStiffness"])
        _write(solver, "linearLimitDamping", SolverUi["linearLimitDamping"])
        _write(solver, "angularLimitStiffness", SolverUi["angularLimitStiffness"])
        _write(solver, "angularLimitDamping", SolverUi["angularLimitDamping"])
        _write(solver, "linearConstraintStiffness", SolverUi["linearConstraintStiffness"])
        _write(solver, "linearConstraintDamping", SolverUi["linearConstraintDamping"])
        _write(solver, "angularConstraintStiffness", SolverUi["angularConstraintStiffness"])
        _write(solver, "angularConstraintDamping", SolverUi["angularConstraintDamping"])
        _write(solver, "linearDriveStiffness", SolverUi["linearDriveStiffness"])
        _write(solver, "linearDriveDamping", SolverUi["linearDriveDamping"])
        _write(solver, "angularDriveStiffness", SolverUi["angularDriveStiffness"])
        _write(solver, "angularDriveDamping", SolverUi["angularDriveDamping"])

        # Added 2023.06.01
        if "sceneScale" in Solver:
            scene_scale = Solver["sceneScale"]
            scene_scale = 1 / scene_scale
        else:
            scene_scale = Solver["spaceMultiplier"]

        # E.g. 0.1 -> 10
        scene_scale *= unit_scale_factor

        _write(solver, "sceneScale", scene_scale)

    @bpx.with_cumulative_timing
    def _apply_group(self, entity, group):
        GroupUi = self._registry.get(entity, "GroupUIComponent")

        input_type = {
            "Inherit": 0,
            "Off": 1,
            "Kinematic": 2,
            "Drive": 3
        }.get(GroupUi["inputType"], 3)

        linear_motion = {
            "Locked": constants.MotionLocked,
            "Limited": constants.MotionLimited,
            "Free": constants.MotionFree,
        }.get(GroupUi.get("linearMotion"), 0)

        _write(group, "inputType", input_type)
        _write(group, "enabled", GroupUi["enabled"])
        _write(group, "selfCollide", GroupUi["selfCollide"])

        # Added 2022.02.25
        try:
            _write(group, "linearMotion", linear_motion)
        except KeyError:
            pass

        # Added 2022.11.25
        try:
            _write(group, "linearStiffness", GroupUi["linearStiffness"])
            _write(group, "angularStiffness", GroupUi["angularStiffness"])
            _write(group, "linearDampingRatio",
                   GroupUi["linearDampingRatio"])
            _write(group, "angularDampingRatio",
                   GroupUi["angularDampingRatio"])

        except KeyError:
            pass

    @bpx.with_cumulative_timing
    def _apply_collision_group(self, mod, entity, col):
        pass

    @bpx.with_cumulative_timing
    def _apply_constraint(self, mod, entity, con):
        pass

    @bpx.with_cumulative_timing
    def _apply_marker(self, entity, marker):
        Name = self._registry.get(entity, "NameComponent")
        Desc = self._registry.get(entity, "GeometryDescriptionComponent")
        Color = self._registry.get(entity, "ColorComponent")
        Rigid = self._registry.get(entity, "RigidComponent")
        Lod = self._registry.get(entity, "LodComponent")
        MarkerUi = self._registry.get(entity, "MarkerUIComponent")
        Drawable = self._registry.get(entity, "DrawableComponent")
        Subs = self._registry.get(entity, "SubEntitiesComponent")
        Joint = self._registry.get(Subs["relative"], "JointComponent")
        Limit = self._registry.get(Subs["relative"], "LimitComponent")
        Drive = self._registry.get(Subs["absolute"], "DriveComponent")

        bpx.rename(marker, Name["value"])

        input_type = {
            "Inherit": 0,
            "Off": 1,
            "Kinematic": 2,
            "Drive": 3
        }.get(MarkerUi["inputType"], 0)

        linear_motion = {
            "Inherit": constants.MotionInherit,
            "Locked": constants.MotionLocked,
            "Limited": constants.MotionLimited,
            "Free": constants.MotionFree,
        }.get(MarkerUi.get("linearMotion"), 0)

        lod_preset = {
            "Level0": constants.Lod0,
            "Level1": constants.Lod1,
            "Level2": constants.Lod2,
            "Custom": constants.LodCustom,
        }.get(Lod["preset"], 0)

        lod_op = {
            "LessThan": constants.LodLessThan,
            "GreaterThan": constants.GreaterThan,
            "Equal": constants.LodEqual,
            "NotEqual": constants.LodNotEqual,
        }.get(Lod["op"], 0)

        display_type = {
            "Off": -1,
            "Default": 0,
            "Wire": 1,
            "Constant": 2,
            "Shaded": 3,
            "Mass": 4,
            "Friction": 5,
            "Restitution": 6,
            "Velocity": 7,
            "Contacts": 8,
        }.get(Drawable["displayType"], 0)

        _write(marker, "mass", MarkerUi["mass"])
        _write(marker, "density", Rigid["densityCustom"])
        _write(marker, "inputType", input_type)
        _write(marker, "limitStiffness", MarkerUi["limitStiffness"])
        _write(marker, "limitDampingRatio", MarkerUi["limitDampingRatio"])
        _write(marker, "collisionGroup", MarkerUi["collisionGroup"])
        _write(marker, "friction", Rigid["friction"])
        _write(marker, "restitution", Rigid["restitution"])
        _write(marker, "collide", Rigid["collide"])
        _write(marker, "linearDamping", Rigid["linearDamping"])
        _write(marker, "angularDamping", Rigid["angularDamping"])
        _write(marker, "positionIterations", Rigid["positionIterations"])
        _write(marker, "velocityIterations", Rigid["velocityIterations"])
        _write(marker, "maxContactImpulse", Rigid["maxContactImpulse"])
        _write(marker, "maxDepenetrationVelocity", Rigid["maxDepenetrationVelocity"])
        _write(marker, "angularMass", Rigid["angularMass"])
        _write(marker, "centerOfMass", Rigid["centerOfMass"])
        _write(marker, "lodPreset", lod_preset)
        _write(marker, "lodOperator", lod_op)
        _write(marker, "lod", Lod["level"])
        _write(marker, "displayType", display_type)

        # Limits
        min1 = bpx.radians(-1)

        _write(marker, "collideWithParent", not Joint["disableCollision"])
        _write(marker, "parentFrame", Joint["parentFrame"])
        _write(marker, "childFrame", Joint["childFrame"])
        _write(marker, "limitRange", (
            max(min1, Limit["twist"]),
            max(min1, Limit["swing1"]),
            max(min1, Limit["swing2"]),
        ))

        if "ignoreMass" in Joint:
            # Added in 2023.03.23
            _write(marker, "ignoreMass", Joint["ignoreMass"])

        shape_type = {
            "Box": constants.BoxShape,
            "Sphere": constants.SphereShape,
            "Capsule": constants.CapsuleShape,
            "ConvexHull": constants.MeshShape,
        }.get(Desc["type"], constants.CapsuleShape)

        _write(marker, "shapeExtents", Desc["extents"])
        _write(marker, "shapeLength", Desc["length"])
        _write(marker, "shapeRadius", Desc["radius"])
        _write(marker, "shapeOffset", Desc["offset"])
        _write(marker, "color", Color["value"])

        # These are exported as Quaternion
        rotation = Desc["rotation"].to_euler("XYZ")
        _write(marker, "shapeRotation", rotation)

        # Added in 2022.03.14
        try:
            Origin = self._registry.get(entity, "OriginComponent")
            _write(marker, "originMatrix", Origin["matrix"])
        except KeyError:
            pass

        # Added 2022.02.25
        try:
            _write(marker, "linearMotion", linear_motion)
        except KeyError:
            pass

        # Added 2022.11.25
        try:
            _write(marker, "linearStiffness", MarkerUi["linearStiffness"])
            _write(marker, "linearDampingRatio",
                   MarkerUi["linearDampingRatio"])
            _write(marker, "angularStiffness", MarkerUi["angularStiffness"])
            _write(marker, "angularDampingRatio",
                   MarkerUi["angularDampingRatio"])

        except KeyError:
            pass

        mesh_replaced = False

        if MarkerUi["inputGeometryPath"]:
            path = MarkerUi["inputGeometryPath"]
            name = _name(path)

            try:
                mesh = bpx.find(name)
            except KeyError:
                # Backwards compatibility, before meshes were exported
                if not self._registry.has(entity, "ConvexMeshComponents"):
                    if shape_type == constants.MeshShape:
                        # No mesh? Resort to a plain capsule
                        shape_type = constants.CapsuleShape
                        bpx.warning(
                            "%s.%s=%s could not be found, reverting "
                            "to a capsule shape" % (
                                marker, "inputGeometry", path
                            )
                        )

            else:
                marker["inputGeometry"] = {"object": mesh}
                mesh_replaced = True

            _write(marker, "inputGeometryMatrix",
                   MarkerUi["inputGeometryMatrix"])

        if not mesh_replaced:
            path = MarkerUi["inputGeometryPath"] or MarkerUi["sourceTransform"]
            name = _name(path)

            if self._registry.has(entity, "ConvexMeshComponents"):
                Meshes = self._registry.get(entity, "ConvexMeshComponents")

                # May be empty
                if Meshes["vertices"]:
                    Meshes = self._registry.get(entity, "ConvexMeshComponents")
                    Scale = self._registry.get(entity, "ScaleComponent")
                    mesh = meshes_to_obj(name, Meshes, Scale["value"])

                    marker["inputGeometry"] = {"object": mesh}

                    source = marker["sourceTransform"].read()
                    armature = source.handle()

                    # bone = armature.handle().pose.bones[bone_name]
                    con = bpx.create_constraint(mesh, "CHILD_OF")
                    con.target = armature
                    con.subtarget = source.pose_bone().name

                    # Geometry is already stored in the frame of the Marker
                    con.inverse_matrix = bpx.Matrix()

                    # Matrix is baked into the exported vertices
                    _write(marker, "inputGeometryMatrix", bpx.Matrix())

        # Set this after replacing the mesh, as the replaced
        # mesh may not actually be in use.
        _write(marker, "shapeType", shape_type)


def meshes_to_obj(name, Meshes, scale=None):
    vertices = []
    edges = []
    faces = []

    # Failsafe
    if any(abs(axis) < 0.0001 for axis in scale):
        scale.x = max(0.0001, scale.x)
        scale.y = max(0.0001, scale.y)
        scale.z = max(0.0001, scale.z)
        bpx.debug("Bad scale during meshes_to_obj, this is a bug")

    for vertex in Meshes["vertices"][:]:
        vertex.x /= scale.x
        vertex.y /= scale.y
        vertex.z /= scale.z

        vertices.append(vertex)

    # It's all triangles, 3 points each
    indices = Meshes["indices"]
    end = len(indices) + 1
    prev = 0
    for i in range(3, end, 3):
        faces.append(indices[prev:i])
        prev = i

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, edges, faces)

    obj = bpy.data.objects.new(name, mesh)
    return bpx.BpxObject(obj, exists=False)
