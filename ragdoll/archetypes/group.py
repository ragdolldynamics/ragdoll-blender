import ragdollc
from ragdollc import registry

from .. import scene
from ..vendor import bpx


@scene.with_properties("rdGroup.json")
class RdGroupPropertyGroup(scene.PropertyGroup):
    type = "rdGroup"

    @classmethod
    def on_property_changed(cls, entity, name):
        if name.startswith("members"):
            xobj = bpx.alias(entity)

            for member in xobj["members"].read():
                if not member.object:  # Could be disconnected
                    continue

                xmember = bpx.BpxType(member.object)

                member_entity = xmember.data["entity"]
                group = registry.get("GroupComponent", member_entity)
                group.entity = entity

        super().on_property_changed(entity, name)


def post_constructor(xobj):
    entity = xobj.data.get("entity")

    if entity is not None:
        ragdollc.registry.destroy(entity)

    entity = ragdollc.scene.createGroup(xobj.name())

    # Create a two-way mapping between these
    bpx.create_alias(entity, xobj)

    xobj.data["entity"] = entity

    touch_all_properties(entity)


def touch_all_properties(entity):
    RdGroupPropertyGroup.touch_all_properties(entity)


def evaluate_start_state(entity):
    xobj = bpx.alias(entity)

    group_ui = registry.get("GroupUIComponent", entity)
    group_ui.selfCollide = xobj["selfCollide"].read()


def evaluate_current_state(entity):
    xobj = bpx.alias(entity)

    group_ui = registry.get("GroupUIComponent", entity)
    group_ui.inputType = xobj["inputType"].read()
    group_ui.linearMotion = xobj["linearMotion"].read()
    group_ui.linearStiffness = xobj["linearStiffness"].read()
    group_ui.linearDampingRatio = xobj["linearDampingRatio"].read()
    group_ui.angularStiffness = xobj["angularStiffness"].read()
    group_ui.angularDampingRatio = xobj["angularDampingRatio"].read()


def on_removed(entity):
    pass


def install():
    scene.post_constructors["rdGroup"] = post_constructor
    scene.register_property_group(RdGroupPropertyGroup)


def uninstall():
    scene.unregister_property_group(RdGroupPropertyGroup)
