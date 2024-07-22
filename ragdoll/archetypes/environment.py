import bpy

import ragdollc
from ragdollc import registry

from .. import scene, types
from ..vendor import bpx


@scene.with_properties("rdEnvironment.json")
class RdEnvironmentPropertyGroup(scene.PropertyGroup):
    type = "rdEnvironment"

    @classmethod
    def on_property_changed(cls, entity, name):
        """Monitor non-keyable properties"""

        if name in "inputGeometry":
            parse_input_geometry(entity)

        super().on_property_changed(entity, name)


def touch_all_properties(entity):
    RdEnvironmentPropertyGroup.touch_all_properties(entity)


def post_constructor(xobj):
    entity = xobj.data.get("entity")

    if entity is not None:
        ragdollc.registry.destroy(entity)

    entity = ragdollc.scene.createEnvironment(xobj.name())

    # Create a two-way mapping between these
    bpx.create_alias(entity, xobj)

    xobj.data["entity"] = entity

    touch_all_properties(entity)


@bpx.with_cumulative_timing
def evaluate_start_state(entity):
    xobj = bpx.alias(entity)
    xsource = xobj["inputGeometry"].read(False)

    if not xsource:
        return

    # Keep this up to date
    xsource.data["entity"] = entity

    mat = xsource.matrix()
    Rest = registry.get("RestComponent", entity)
    Rest.value = types.to_rdmatrix(mat)

    Scale = registry.get("ScaleComponent", entity)
    Scale.value = types.to_rdvector(mat.to_scale())

    Rigid = registry.get("RigidComponent", entity)
    Rigid.friction = xobj["friction"].read()
    Rigid.restitution = xobj["restitution"].read()
    Rigid.thickness = xobj["thickness"].read()


@bpx.with_cumulative_timing
def evaluate_current_state(entity):
    pass


def parse_input_geometry(entity):
    # We need the scale component
    evaluate_start_state(entity)

    xobj = bpx.alias(entity)

    Mesh = registry.get("MeshComponent", entity)
    Mesh.vertices.clear()
    Mesh.indices.clear()

    geo = xobj["inputGeometry"].read()

    # There may not be any geometry connected
    if not geo:
        return

    mesh = geo.handle().data
    for v in mesh.vertices:
        point = types.to_rdpoint(v.co)
        Mesh.vertices.append(point)

    if len(Mesh.vertices) == 0:
        return False

    for loops in mesh.loop_triangles:
        for index in loops.vertices:
            Mesh.indices.append(index)


def install():
    scene.post_constructors["rdEnvironment"] = post_constructor
    scene.register_property_group(RdEnvironmentPropertyGroup)


def uninstall():
    scene.unregister_property_group(RdEnvironmentPropertyGroup)
