import bpy
from .vendor import bpx


def upgrade_all():
    # TEMP: Introduced new boneId property
    for marker in bpx.ls(type="rdMarker"):
        pg = marker.property_group()
        source = pg.sourceTransform
        object = source.object

        if not object:
            continue

        if not isinstance(object.data, bpy.types.Armature):
            continue

        if source.object and source.boneid == "" and source.get("bone"):
            bone_name = source["bone"]
            bone = source.object.pose.bones[bone_name]
            bone = bpx.BpxBone(bone)
            source.boneid = bone.boneid()
            bpx.debug("Patched up boneid for %s" % bone)

    for xobj in bpx.ls():
        # TEMP: Backwards compatibility
        typ = bpx.get_attr(xobj, "bpxType")
        if typ:
            bpx.debug("Patched up bpxType for %s" % xobj)
            bpx._set_bpxtype(xobj.handle(), typ)
