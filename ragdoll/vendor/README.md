# bpx.py

A wrapper around Blender's `bpy` with persistent object refernces.

**Features**

- Persistent references to objects
- Persistent references to pose bones
- Ordered selection
- Transient metadata
- Alias
- Operator callbacks
- Object Created callback
- Object Removed callback
- Object Unremoved callback
- Object Destroyed callback
- Object Duplicated callback
- Selection Changed callback

The difference between an object being destroyed versus removed is that
destroyed objects can never returned. They are permanently gone and cannot
be restored from e.g. undo. Typical example is file open or undo followed by
performing a new action which invalidates redo.

Object removal is currently tracked during selection change, as there is
no native mechanism for monitoring when an object is removed.

The file is encoded utf-8 due to object names in Blender being unicode.
