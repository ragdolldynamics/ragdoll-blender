import bpy

BLENDER_3 = bpy.app.version[0] == 3
BLENDER_4 = bpy.app.version[0] == 4

Auto = None
Off = False

InputInherit = 0
InputKinematic = 2
InputDynamic = 3

# Shape types
BoxShape = 0
SphereShape = 1
CapsuleShape = 2
CylinderShape = 2
ConvexHullShape = 4
MeshShape = ConvexHullShape

# Cache
StaticCache = 1
DynamicCache = 2

DisplayWire = 1

NoGroup = 0
AddToExisting = 1
CreateNewGroup = 2
SpecificGroup = -1

# rdSolver.startTime
PlaybackStart = 0
PreviewStart = 1
CustomStart = 2

LodLessThan = 0
GreaterThan = 1
LodEqual = 2
LodNotEqual = 3

Lod0 = 0
Lod1 = 1
Lod2 = 2
LodCustom = 3

MatchByName = 0
MatchByHierarchy = 1

MotionInherit = -1
MotionLocked = 0
MotionLimited = 1
MotionFree = 2
