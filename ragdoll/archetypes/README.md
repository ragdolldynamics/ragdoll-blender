This directory defines each Ragdoll type as a Blender-equivalent Property Group, which we then use alongside bpx to read and write data from and to Blender.

```py
import bpx
marker = bpx.create_object(bpx.e_empty, "myMarker", archetype="rdMarker")
marker["shapeRadius"] = 1.2
```
