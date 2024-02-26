import ragdollc
from ragdollc import registry

from .. import scene, types
from ..vendor import bpx


@scene.with_properties("rdDistanceConstraint.json")
class RdDistanceConstraintPropertyGroup(scene.PropertyGroup):
    type = "rdDistanceConstraint"

    @classmethod
    def on_property_changed(cls, entity, name):
        if name in ("parentMarker", "childMarker"):
            Joint = registry.get("JointComponent", entity)

            if name == "parentMarker":
                Joint.parent = registry.null
            else:
                Joint.child = registry.null

            xobj = bpx.alias(entity)
            if xobj:
                other = xobj[name].read()
                if other:
                    other = bpx.BpxType(other)
                    other_entity = other.data["entity"]

                    if name == "parentMarker":
                        Joint.parent = other_entity
                    else:
                        Joint.child = other_entity

        super().on_property_changed(entity, name)


def post_constructor(xobj):
    entity = xobj.data.get("entity")

    if entity is not None:
        ragdollc.registry.destroy(entity)

    entity = ragdollc.scene.createDistanceConstraint(xobj.name())

    # Create a two-way mapping between these
    bpx.create_alias(entity, xobj)

    xobj.data["entity"] = entity

    touch_all_properties(entity)


def touch_all_properties(entity):
    RdDistanceConstraintPropertyGroup.touch_all_properties(entity)


def evaluate_start_state(entity):
    xobj = bpx.alias(entity)

    removed = registry.get("RemovedComponent", entity)
    removed.value = not xobj.is_alive()

    if removed.value:
        return

    parent_offset = xobj["parentOffset"].read()
    child_offset = xobj["childOffset"].read()
    parent_frame = bpx.Matrix.Translation(parent_offset)
    child_frame = bpx.Matrix.Translation(child_offset)

    Joint = registry.get("JointComponent", entity)
    Joint.parentFrame = types.to_rdtype(parent_frame)
    Joint.childFrame = types.to_rdtype(child_frame)
    Joint.ignoreMass = xobj["ignoreMass"].read()

    DistUi = registry.get("DistanceJointUIComponent", entity)
    DistUi.useScaleForDistance = xobj["useScaleForDistance"].read()
    DistUi.useScale = xobj["useScale"].read()

    # When the transform itself is scaled, which can happen
    # when there is a parent to the transform that is scaled.
    if registry.valid(Joint.parent):
        scale = registry.get("ScaleComponent", Joint.parent)
        Joint.childFrame = Joint.childFrame * scale.matrix

    evaluate_current_state(entity)


def evaluate_current_state(entity):
    xobj = bpx.alias(entity)

    Dist = registry.get("DistanceJointComponent", entity)
    Dist.method = xobj["method"].read()
    Dist.scale = xobj["scale"].read()

    if Dist.method != Dist.FromStart:
        Dist.minimum = xobj["minimum"].read()
        Dist.maximum = xobj["maximum"].read()

        if Dist.method == Dist.Custom:
            Dist.minimum = min(Dist.minimum, Dist.maximum)
            Dist.maximum = max(Dist.minimum, Dist.maximum)

        Dist.minimum *= Dist.scale
        Dist.maximum *= Dist.scale

    if Dist.stiffness < 0:
        Dist.tolerance = 0.0
    else:
        Dist.tolerance = xobj["tolerance"].read()

    # Sanity checks
    Dist.minimum = max(0, Dist.minimum)
    Dist.maximum = max(0, Dist.maximum)

    DistUi = registry.get("DistanceJointUIComponent", entity)
    DistUi.stiffness = xobj["stiffness"].read()
    DistUi.dampingRatio = xobj["dampingRatio"].read()

    if DistUi.useScaleForDistance:
        Joint = registry.get("JointComponent", entity)

        if registry.valid(Joint.child):
            Scale = registry.get("ScaleComponent", Joint.child)
            Dist.minimum *= Scale.value.x()
            Dist.maximum *= Scale.value.x()


def install():
    scene.post_constructors["rdDistanceConstraint"] = post_constructor
    scene.register_property_group(RdDistanceConstraintPropertyGroup)


def uninstall():
    scene.unregister_property_group(RdDistanceConstraintPropertyGroup)
