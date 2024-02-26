### Ragdoll for Blender

Welcome to Ragdoll! This addon is a "bridge" between Blender and "Ragdoll Core", which is the run-time engine and API of Ragdoll.

Under the hood, Ragdoll is similar to Blender and Maya, in that it also has a notion of objects, a scene graph, selection, undo and redo, a serialisation format for saving scene files to disk. The basic building blocks of a graphical editor.

<br>

### Operators

Any change made interactively is made via a so-called "Operator".

Operators are Blender's way of encapsulating an action with undo/redo, along with modal edits such as activating a picker and picking a mesh to replace a collider with.

All of Ragdoll's operators live in the [`operators/`](/operators) directory and registerd to the namespace `bpy.ops.ragdoll`.

```py
# Select some objects, and run the following:
bpy.ops.ragroll.assign_markers()
```

<br>

### bpx

The glue between Ragdoll and Blender is called "bpx" and is a subset of `bpy` with persistent references to objects and bones.

```py
from ragdoll.vendor import bpx
obj = bpx.create_object(bpx.e_mesh)
```

References will survive undo and provides caching and change detection of properties.

- See [bpx.py](https://github.com/ragdolldynamics/bpx.py) for details

<br>

### bpxId

As part of `ragdoll.vendor.bpx` every Object and PoseBone in Blender that Ragdoll operates on will have a `bpxId` property. This is a persistent identifier that survives undo and redo, which Blender would normally consider destructive to any Python object reference.

<br>

### ragdollId

Each object representing a Ragdoll "entity" is imbued with a `ragdollId` property. This property helps Ragdoll identify which objects should have an entity instantiated for it on scene-open.
