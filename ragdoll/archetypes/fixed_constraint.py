import bpy

from ragdollc import registry

from .. import scene
from ..vendor import bpx


@scene.with_properties("rdFixedConstraint.json")
class RdFixedConstraintPropertyGroup(scene.PropertyGroup):
    type = "rdFixedConstraint"


def evaluate_start_state(entity):
    pass


def evaluate_current_state(entity):
    pass


def install():
    scene.register_property_group(RdFixedConstraintPropertyGroup)


def uninstall():
    scene.unregister_property_group(RdFixedConstraintPropertyGroup)
