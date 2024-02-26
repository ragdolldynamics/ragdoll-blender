import ragdollc
from ragdollc import (
    registry,
    components as c
)

from .. import scene, types, events
from ..vendor import bpx


@scene.with_properties("rdSolver.json")
class RdSolverPropertyGroup(scene.PropertyGroup):
    type = "rdSolver"

    @classmethod
    def on_property_changed(cls, entity, name):
        if name.startswith("members"):
            # Add members immediately, ahead of evaluating solver,
            # and then again, when Solver requests to evaluate.
            # This prevents uninitialised members from being evaluated
            evaluate_members(entity)

        super().on_property_changed(entity, name)


def post_constructor(xobj):
    entity = xobj.data.get("entity")

    if entity is not None:
        ragdollc.registry.destroy(entity)

    entity = ragdollc.scene.createSolver(xobj.name())

    bpx.create_alias(entity, xobj)

    xobj.data["entity"] = entity

    # Ensure newly created solver is up to date with the latest
    events.post_timeline_changed()
    events.pre_frame_changed()

    touch_all_properties(entity)

    return entity


def touch_all_properties(entity):
    RdSolverPropertyGroup.touch_all_properties(entity)


@bpx.with_cumulative_timing
def evaluate_start_state(entity):
    xobj = bpx.alias(entity)

    tm = registry.get("RestComponent", entity)
    tm.value = types.to_rdmatrix(xobj.matrix())

    solver = registry.get("SolverComponent", entity)
    solver.unhinged = False
    solver.skipped = False
    solver.cacheMethod = xobj["cache"].read()
    solver.substeps = xobj["substeps"].read()
    solver.airDensity = xobj["airDensity"].read()
    solver.spaceMultiplier = xobj["spaceMultiplier"].read()
    solver.timeMultiplier = xobj["timeMultiplier"].read()
    solver.positionIterations = xobj["positionIterations"].read()
    solver.velocityIterations = xobj["velocityIterations"].read()
    solver.blend = xobj["blend"].read()
    solver.type = xobj["solverType"].read()
    solver.collisionDetectionType = xobj["collisionDetectionType"].read()
    solver.bounceThresholdVelocity = xobj["bounceThresholdVelocity"].read()
    solver.frameskipMethod = c.SolverComponent.FrameskipIgnore
    solver.timeMethod = xobj["timeMethod"].read()
    solver.simulateEvery = xobj["simulateEvery"].read()
    solver.simulateEvery = solver.simulateEvery
    solver.origin = types.to_rdvector(xobj["origin"].read())
    solver.maxLinearDriveForce = xobj["maxLinearDriveForce"].read()
    solver.maxAngularDriveForce = xobj["maxAngularDriveForce"].read()

    solverUi = registry.get("SolverUIComponent", entity)
    solverUi.sceneScale = xobj["sceneScale"].read()
    solverUi.linearLimitStiffness = xobj["linearLimitStiffness"].read()
    solverUi.linearLimitDamping = xobj["linearLimitDamping"].read()
    solverUi.angularLimitStiffness = xobj["angularLimitStiffness"].read()
    solverUi.angularLimitDamping = xobj["angularLimitDamping"].read()
    solverUi.linearDriveStiffness = xobj["linearDriveStiffness"].read()
    solverUi.linearDriveDamping = xobj["linearDriveDamping"].read()
    solverUi.angularDriveStiffness = xobj["angularDriveStiffness"].read()
    solverUi.angularDriveDamping = xobj["angularDriveDamping"].read()
    solverUi.linearConstraintStiffness = xobj["linearConstraintStiffness"].read()
    solverUi.linearConstraintDamping = xobj["linearConstraintDamping"].read()
    solverUi.angularConstraintStiffness = xobj["angularConstraintStiffness"].read()
    solverUi.angularConstraintDamping = xobj["angularConstraintDamping"].read()

    # Blender's UI doesn't like these really large values, so let's
    # allow for smaller values in the UI whilst keeping large values internally
    solverUi.linearLimitStiffness *= 1000
    solverUi.linearLimitDamping *= 1000
    solverUi.angularLimitStiffness *= 1000
    solverUi.angularLimitDamping *= 1000

    solverDrawable = registry.get("SolverDrawableComponent", entity)
    solverDrawable.shapes = xobj["drawShapes"].read()
    solverDrawable.constraints = xobj["drawConstraints"].read()
    solverDrawable.drives = xobj["drawDrives"].read()
    solverDrawable.contacts = xobj["drawContacts"].read()
    solverDrawable.hierarchy = xobj["drawHierarchy"].read()
    solverDrawable.destinations = xobj["drawDestinations"].read()
    solverDrawable.velocities = xobj["drawVelocities"].read()
    solverDrawable.trajectories = xobj["drawTrajectories"].read()
    solverDrawable.ghosts = xobj["drawGhosts"].read()

    if solverDrawable.ghosts:
        solverDrawable.ghostsFuture = xobj["drawGhostsFuture"].read()
        solverDrawable.ghostsPast = xobj["drawGhostsPast"].read()
        solverDrawable.ghostsIncrement = xobj["drawGhostsIncrement"].read()
        solverDrawable.ghostsPastColor = xobj["drawGhostsPastColor"].read()
        solverDrawable.ghostsFutureColor = xobj["drawGhostsFutureColor"].read()
        solverDrawable.ghostsDisplayType = xobj["drawGhostsDisplayType"].read()

    solverDrawable.coms = xobj["drawComs"].read()
    solverDrawable.groups = xobj["drawGroups"].read()
    solverDrawable.buffer = xobj["drawBuffer"].read()
    solverDrawable.velocityScale = xobj["drawVelocityScale"].read()
    solverDrawable.limitScale = xobj["drawLimitScale"].read()
    solverDrawable.lineWidth = xobj["drawLineWidth"].read()
    solverDrawable.mode = xobj["drawMode"].read()
    solverDrawable.depth = xobj["drawDepth"].read()
    solverDrawable.limits = xobj["drawLimits"].read()
    solverDrawable.inertia = xobj["drawInertia"].read()

    drawable = registry.get("DrawableComponent", entity)
    drawable.displayType = xobj["displayType"].read()

    evaluate_current_state(entity)


def evaluate_current_state(entity):
    xobj = bpx.alias(entity)

    solverUi = registry.get("SolverUIComponent", entity)
    solverUi.gravity = types.to_rdvector(xobj["gravity"].read(True))


def clear_members(entity):
    for arch_entity in registry.view("ArchetypeComponent"):
        Scene = registry.get("SceneComponent", arch_entity)

        # Some archetypes may not have Scene, e.g. CollisionGroup.
        if Scene:
            if Scene.entity != registry.null and Scene.entity != entity:
                # Ignore entity that belongs to *another* solver.
                continue

            Scene.entity = registry.null

            Group = registry.get("GroupComponent", arch_entity)

            if Group:
                Group.entity = registry.null


def evaluate_enabled(xobj):
    assert isinstance(xobj, bpx.BpxType), "%s was not a BpxType" % xobj

    entity = xobj.data["entity"]
    Removed = registry.get("RemovedComponent", entity)
    Removed.value = not xobj.is_alive()

    # Markers also need their source transform
    if not Removed.value and xobj.type() in "rdMarker":
        xsource = xobj["sourceTransform"].read(animated=False)
        Removed.value = not xsource or not xsource.is_alive()

    # The environment cannot exist without its input geometry
    if not Removed.value and xobj.type() in "rdEnvironment":
        xsource = xobj["inputGeometry"].read(animated=False)
        Removed.value = not xsource or not xsource.is_alive()

    return not Removed.value


@bpx.with_cumulative_timing
def evaluate_members(entity):
    xobj = bpx.alias(entity)

    # Remove all Group and Scene members, such that only
    # those that are alive are added below
    clear_members(entity)

    # Add those that are alive and well
    for member in xobj["members"].read(False):
        if not member.object:  # Could be disconnected
            continue

        xmember = bpx.BpxType(member.object)

        if not evaluate_enabled(xmember):
            continue

        member_entity = xmember.data["entity"]
        Scene = registry.get("SceneComponent", member_entity)
        Scene.entity = entity

        # A scene can contain exactly one level of groups
        if xmember.type() == "rdGroup":
            evaluate_group_members(xmember)


def evaluate_group_members(xgroup):
    assert isinstance(xgroup, bpx.BpxType), "%s was not a BpxType" % xgroup
    entity = xgroup.data["entity"]

    for member in xgroup["members"].read():
        if not member.object:
            continue

        xmember = bpx.BpxType(member.object)
        member_entity = xmember.data["entity"]

        if not evaluate_enabled(xmember):
            continue

        Group = registry.get("GroupComponent", member_entity)
        Group.entity = entity


def install():
    scene.post_constructors["rdSolver"] = post_constructor
    scene.register_property_group(RdSolverPropertyGroup)


def uninstall():
    scene.unregister_property_group(RdSolverPropertyGroup)
