import bpy

import ragdollc
from ragdollc import registry

from .. import scene, types
from ..vendor import bpx


@scene.with_properties("rdMarker.json")
class RdMarkerPropertyGroup(scene.PropertyGroup):

    type = "rdMarker"

    @classmethod
    def on_property_changed(cls, entity, name):
        """Monitor non-keyable properties"""

        xobj = bpx.alias(entity)

        if not xobj:
            return

        if name == "parentMarker":
            parent = registry.get("ParentComponent", entity)
            prop = xobj[name]
            xparent = prop.read()

            if xparent:
                xparent = bpx.BpxType(xparent)
                parent.entity = xparent.data["entity"]
            else:
                parent.entity = registry.null

            registry.replace(entity, parent)

        super().on_property_changed(entity, name)


def touch_all_properties(entity):
    RdMarkerPropertyGroup.touch_all_properties(entity)


def post_constructor(xobj):
    entity = xobj.data.get("entity")

    if entity is not None:
        ragdollc.registry.destroy(entity)

    entity = ragdollc.scene.createMarker(xobj.name())

    # Create a two-way mapping between these
    bpx.create_alias(entity, xobj)

    xobj.data["entity"] = entity

    touch_all_properties(entity)


@bpx.with_cumulative_timing
def evaluate_start_state(entity):
    xobj = bpx.alias(entity)
    xsource = xobj["sourceTransform"].read(False)

    # Keep this up to date
    xsource.data["entity"] = entity

    mat = xsource.matrix()
    Rest = registry.get("RestComponent", entity)
    Rest.value = types.to_rdmatrix(mat)

    Scale = registry.get("ScaleComponent", entity)
    Scale.value = types.to_rdvector(mat.to_scale())

    Origin = registry.get("OriginComponent", entity)
    Origin.value = types.to_rdtype(xobj["originMatrix"].read(False))

    Rigid = registry.get("RigidComponent", entity)
    Rigid.densityCustom = xobj["density"].read(False)
    Rigid.collide = xobj["collide"].read(False)
    Rigid.friction = xobj["friction"].read(False)
    Rigid.restitution = xobj["restitution"].read(False)
    Rigid.thickness = xobj["thickness"].read(False)
    Rigid.ignoreGravity = xobj["ignoreGravity"].read(False)
    Rigid.ignoreFields = xobj["ignoreFields"].read(False)
    Rigid.wakeCounter = xobj["wakeCounter"].read(False)
    Rigid.positionIterations = xobj["positionIterations"].read(False)
    Rigid.velocityIterations = xobj["velocityIterations"].read(False)
    Rigid.maxContactImpulse = xobj["maxContactImpulse"].read(False)
    Rigid.maxDepenetrationVelocity = xobj["maxDepenetrationVelocity"].read(False)

    Desc = registry.get("GeometryDescriptionComponent", entity)
    Desc.type = xobj["shapeType"].read(False)
    Desc.offset = types.to_rdtype(xobj["shapeOffset"].read(False))
    Desc.rotation = types.to_rdtype(xobj["shapeRotation"].read(False))
    Desc.length = xobj["shapeLength"].read(False)
    Desc.extents = types.to_rdtype(xobj["shapeExtents"].read(False))
    Desc.vertexLimit = xobj["shapeVertexLimit"].read(False)
    Desc.radius = xobj["shapeRadius"].read(False)
    Desc.radiusEnd = xobj["shapeRadiusEnd"].read(False)

    MarkerUi = registry.get("MarkerUIComponent", entity)
    MarkerUi.sourceTransform = xsource.name()
    MarkerUi.limitStiffness = xobj["limitStiffness"].read(False)
    MarkerUi.limitDampingRatio = xobj["limitDampingRatio"].read(False)
    MarkerUi.collisionGroup = xobj["collisionGroup"].read(False)
    MarkerUi.drawLimit = xobj["drawLimit"].read(False)
    MarkerUi.drawDrive = xobj["drawDrive"].read(False)
    MarkerUi.centerOfMass = types.to_rdtype(xobj["centerOfMass"].read(False))
    MarkerUi.angularMass = types.to_rdtype(xobj["angularMass"].read(False))
    MarkerUi.drawScale = xobj["drawScale"].read(False)
    MarkerUi.recordTranslation = xobj["recordTranslation"].read(False)
    MarkerUi.recordRotation = xobj["recordRotation"].read(False)
    MarkerUi.inputGeometryMatrix = types.to_rdtype(
        xobj["inputGeometryMatrix"].read(False))

    if Rigid.densityCustom == 0:
        MarkerUi.mass = xobj["mass"].read(False)

    Drawable = registry.get("DrawableComponent", entity)
    Drawable.displayType = xobj["displayType"].read(False)

    Color = registry.get("ColorComponent", entity)
    Color.value = types.to_rdcolor(xobj["color"].read(False))

    Parent = registry.get("ParentComponent", entity)
    Subs = registry.get("SubEntitiesComponent", entity)
    if registry.get("JointChangedComponent", Subs.relative).value:
        registry.get("JointChangedComponent", Subs.relative).value = False

        Joint = registry.get("JointComponent", Subs.relative)
        Joint.ignoreMass = xobj["ignoreMass"].read(False)
        Joint.child = entity

        MarkerUi.parentFrame = types.to_rdmatrix(
            xobj["parentFrame"].read(False))
        MarkerUi.childFrame = types.to_rdmatrix(
            xobj["childFrame"].read(False))

        Limit = registry.get("LimitComponent", Subs.relative)
        Limit.enabled = False

        if registry.valid(Parent.entity):
            Joint.parent = Parent.entity

            rng = xobj["limitRange"].read(False)
            Limit.twist = rng.x
            Limit.swing1 = rng.y
            Limit.swing2 = rng.z
            Limit.enabled = True

    LimitDrawable = registry.get("LimitDrawableComponent", Subs.relative)
    LimitDrawable.visible = MarkerUi.drawLimit

    evaluate_current_state(entity)


@bpx.with_cumulative_timing
def evaluate_current_state(entity):
    # Cannot unremove an object past the start frame
    if registry.get("RemovedComponent", entity).value:
        return

    xobj = bpx.alias(entity)

    # Object can be removed on frames other than the start frame
    # But we do not care for it, as there is nothing we can do.
    if not xobj.is_alive():
        return

    xsource = xobj["sourceTransform"].read(False)
    mat = types.to_rdmatrix(xsource.matrix())

    Kinematic = registry.get("KinematicComponent", entity)
    Kinematic.value = mat

    MarkerUi = registry.get("MarkerUIComponent", entity)
    MarkerUi.inputType = xobj["inputType"].read(True)
    MarkerUi.linearMotion = xobj["linearMotion"].read(True)
    MarkerUi.airDensity = xobj["airDensity"].read(True)
    MarkerUi.linearStiffness = xobj["linearStiffness"].read(True)
    MarkerUi.linearDampingRatio = xobj["linearDampingRatio"].read(True)
    MarkerUi.angularStiffness = xobj["angularStiffness"].read(True)
    MarkerUi.angularDampingRatio = xobj["angularDampingRatio"].read(True)
    MarkerUi.linearDamping = xobj["linearDamping"].read(True)
    MarkerUi.angularDamping = xobj["angularDamping"].read(True)

    Subs = registry.get("SubEntitiesComponent", entity)
    JointAnim = registry.get("JointAnimation", Subs.relative)
    JointAnim.influence = xobj["influence"].read(True)

    Drive = registry.get("DriveComponent", Subs.relative)
    Drive.target = mat
    Drive.slerp = xobj["driveInterpolation"].read(True)
    Drive.acceleration = xobj["driveSpringType"].read(True)
    Drive.angularAmountTwist = xobj["driveAngularAmountTwist"].read(True)
    Drive.angularAmountSwing = xobj["driveAngularAmountSwing"].read(True)
    Drive.linearAmount = types.to_rdvector(
        xobj["driveLinearAmount"].read(True))


def parse_input_geometry(entity):
    xobj = bpx.alias(entity)

    InputMesh = registry.get("InputMeshComponent", entity)
    InputMesh.vertices.clear()
    InputMesh.triangleIndices.clear()

    geo = xobj["inputGeometry"].read()

    # There may not be any geometry connected
    if not geo:
        return

    mesh = geo.handle().data
    for v in mesh.vertices:
        point = types.to_rdpoint(v.co)
        InputMesh.vertices.append(point)

    if len(InputMesh.vertices) == 0:
        return False

    for loops in mesh.loop_triangles:
        for index in loops.vertices:
            InputMesh.triangleIndices.append(index)


def install():
    scene.post_constructors["rdMarker"] = post_constructor
    scene.register_property_group(RdMarkerPropertyGroup)


def uninstall():
    scene.unregister_property_group(RdMarkerPropertyGroup)
