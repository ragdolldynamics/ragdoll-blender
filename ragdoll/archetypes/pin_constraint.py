import ragdollc
from ragdollc import registry

from .. import scene, types
from ..vendor import bpx


@scene.with_properties("rdPinConstraint.json")
class RdPinConstraintPropertyGroup(scene.PropertyGroup):
    type = "rdPinConstraint"

    @classmethod
    def on_property_changed(cls, entity, name):
        if name in ("parentMarker", "childMarker"):
            xobj = bpx.alias(entity)
            Joint = registry.get("JointComponent", entity)

            if name == "parentMarker":
                Joint.parent = registry.null
            else:
                Joint.child = registry.null

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

    entity = ragdollc.scene.createPinConstraint(xobj.name())

    # Create a two-way mapping between these
    bpx.create_alias(entity, xobj)

    xobj.data["entity"] = entity

    touch_all_properties(entity)


def touch_all_properties(entity):
    RdPinConstraintPropertyGroup.touch_all_properties(entity)


def evaluate_start_state(entity):
    xobj = bpx.alias(entity)

    removed = registry.get("RemovedComponent", entity)
    removed.value = not xobj.is_alive()

    if removed.value:
        return

    parent_frame = xobj["parentFrame"].read()
    child_frame = xobj["childFrame"].read()
    parent_frame = types.descale_matrix(parent_frame)
    child_frame = types.descale_matrix(child_frame)

    Joint = registry.get("JointComponent", entity)
    Joint.parentFrame = types.to_rdtype(parent_frame)
    Joint.childFrame = types.to_rdtype(child_frame)

    # When the transform itself is scaled, which can happen
    # when there is a parent to the transform that is scaled.
    if registry.valid(Joint.parent):
        scale = registry.get("ScaleComponent", Joint.parent)
        Joint.childFrame = Joint.childFrame * scale.matrix

    evaluate_current_state(entity)


def evaluate_current_state(entity):
    xobj = bpx.alias(entity)

    mat = xobj.matrix()
    mat = types.descale_matrix(mat)

    # Assemble the final stiffness/damping values in the solver
    # alongside the global values.
    PinUI = registry.get("PinJointUIComponent", entity)
    PinUI.linearStiffness = xobj["linearStiffness"].read()
    PinUI.linearDampingRatio = xobj["linearDampingRatio"].read()
    PinUI.angularStiffness = xobj["angularStiffness"].read()
    PinUI.angularDampingRatio = xobj["angularDampingRatio"].read()
    PinUI.angularStiffnessSwing = xobj["angularStiffnessSwing"].read()
    PinUI.angularStiffnessTwist = xobj["angularStiffnessTwist"].read()
    PinUI.linearStiffnessXYZ = types.to_rdvector(
        xobj["linearStiffnessXYZ"].read())

    Drive = registry.get("DriveComponent", entity)
    Drive.target = types.to_rdtype(mat)
    Drive.acceleration = xobj["springType"].read()

    JointAnim = registry.get("JointAnimation", entity)
    JointAnim.influence = xobj["influence"].read()
    JointAnim.influence = min(1.0, JointAnim.influence)
    JointAnim.influence = max(0.0, JointAnim.influence)


def install():
    scene.post_constructors["rdPinConstraint"] = post_constructor
    scene.register_property_group(RdPinConstraintPropertyGroup)


def uninstall():
    scene.unregister_property_group(RdPinConstraintPropertyGroup)
