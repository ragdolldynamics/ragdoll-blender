import os
import bpy

from .. import constants, parser
from ..vendor import bpx

from . import (
    OperatorWithOptions,
    PlaceholderOption,
)


class ExportPhysics(OperatorWithOptions):
    """Save Ragdoll physics to disk

    Export the internals of the Ragdoll solver into a new file, this file
    could then be imported back into Blender for re-application onto an
    identical character or imported elsewhere such as Unreal or Unity.

    """
    bl_idname = "ragdoll.export_physics"
    bl_label = "Export Physics"
    bl_options = {"INTERNAL"}
    bl_description = "Save Ragdoll physics to disk"

    icon = "EXPORT"

    # File dialog writes selected path to `filepath` property.
    filepath: PlaceholderOption("exportPath")
    filter_glob: bpy.props.StringProperty(
        default="*.rag",
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        if not bpx.ls(type="rdSolver"):
            cls.poll_message_set("No Ragdoll solvers in the current scene")
            return False

        return True

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):

        if not self.filepath:
            self.report({"ERROR"}, "Export file path not decided.\n"
                        "Please try re-run the command with dialog for "
                        "options.")
            return {"CANCELLED"}

        if os.path.isdir(self.filepath):
            self.report({"ERROR"}, "Expecting a file path, not directory.")
            return {"CANCELLED"}

        if not self.filepath.lower().endswith(".rag"):
            self.filepath += ".rag"

        parser.export(self.filepath)

        self.report({"INFO"}, "Physics exported: %s" % self.filepath)
        return {"FINISHED"}


class ImportPhysics(OperatorWithOptions):
    """Import Ragdoll physics from disk

    Import a previously exported Ragdoll scene from disk.

    """
    bl_idname = "ragdoll.import_physics"
    bl_label = "Import Physics"
    bl_options = {"INTERNAL"}
    bl_description = "Import Ragdoll physics from disk"

    icon = "CON_ARMATURE"

    # File dialog writes selected path to `filepath` property.
    filepath: PlaceholderOption("exportPath")
    filter_glob: bpy.props.StringProperty(
        default="*.rag",
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.filepath:
            self.report({"ERROR"}, "Import file path not decided.\n"
                        "Please try re-run the command with dialog for "
                        "options.")
            return {"CANCELLED"}

        if os.path.isdir(self.filepath):
            self.report({"ERROR"}, "Expecting a file path, not directory.")
            return {"CANCELLED"}

        parser.reinterpret(self.filepath)

        self.report({"INFO"}, "Physics imported: %s" % self.filepath)
        return {"FINISHED"}


class LoadPhysics(OperatorWithOptions):
    """Generate Blender scene from .rag file

    Be rid of all native Blender objects and work with pure physics at optimal
    performance. Export and apply the baked keyframes onto your original,
    heavy character rig once finished tinkering.

    """
    bl_idname = "ragdoll.load_physics"
    bl_label = "Load Physics"
    bl_options = {"INTERNAL"}
    bl_description = "Generate Blender scene from .rag file"

    icon = "IMPORT"

    # File dialog writes selected path to `filepath` property.
    filepath: PlaceholderOption("exportPath")
    filter_glob: bpy.props.StringProperty(
        default="*.rag",
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.filepath:
            self.report({"ERROR"}, "File path not decided.\n"
                        "Please try re-run the command with dialog for "
                        "options.")
            return {"CANCELLED"}

        if os.path.isdir(self.filepath):
            self.report({"ERROR"}, "Expecting a file path, not directory.")
            return {"CANCELLED"}

        with bpx.timing("load_physics", True) as t:
            self.load(self.filepath)

        self.report({"INFO"}, "Physics loaded in %.2f ms: %s" % (
            t.duration, self.filepath
        ))

        return {"FINISHED"}

    def load(self, fname):
        """Create a Blender scene from an exported Ragdoll file

        New transforms are generated and then assigned Markers.

        """

        # Prefer merging with the first found existing solver
        solver = next(bpx.ls_iter(type="rdSolver"), None)

        opts = {

            # No hierarchy here, it's cleeeean
            "matchBy": constants.MatchByName,

            # No need to retarget, we're targeting the inputs
            "retarget": False,

            # Don't hold any Blender's python object reference
            "overrideSolver": solver.name() if solver else "",
        }

        parser.load(fname, **opts)


def install():
    bpy.utils.register_class(ExportPhysics)
    bpy.utils.register_class(ImportPhysics)
    bpy.utils.register_class(LoadPhysics)


def uninstall():
    bpy.utils.unregister_class(ExportPhysics)
    bpy.utils.unregister_class(ImportPhysics)
    bpy.utils.unregister_class(LoadPhysics)
