import bpy
import logging
from ..vendor import bpx

_log = bpx._LOG


class LogOff(bpy.types.Operator):
    bl_idname = "ragdoll.logging_off"
    bl_label = "Logging Off"
    bl_options = {"INTERNAL"}
    bl_description = "Stay quiet."
    icon = "MUTE_IPO_OFF"

    def execute(self, _):
        _log.setLevel(logging.CRITICAL)
        return {"FINISHED"}


class LogDefault(bpy.types.Operator):
    bl_idname = "ragdoll.logging_default"
    bl_label = "Default Logging"
    bl_options = {"INTERNAL"}
    bl_description = ("Print only messages that may be interesting, but "
                      "probably aren't.")
    icon = "PLAY_SOUND"

    def execute(self, _):
        _log.setLevel(logging.INFO)
        _log.info("Info level set")
        return {"FINISHED"}


class LogLess(bpy.types.Operator):
    bl_idname = "ragdoll.logging_less"
    bl_label = "Less Logging"
    bl_options = {"INTERNAL"}
    bl_description = ("Don't print anything unless it's something I need to "
                      "pay attention to.")
    icon = "REMOVE"

    def execute(self, _):
        _log.setLevel(logging.WARNING)
        _log.warning("Warning level set")
        return {"FINISHED"}


class LogMore(bpy.types.Operator):
    bl_idname = "ragdoll.logging_more"
    bl_label = "More Logging"
    bl_options = {"INTERNAL"}
    bl_description = "Print all messages you can think of."
    icon = "ADD"

    def execute(self, _):
        _log.setLevel(logging.DEBUG)
        _log.debug("Debug level set")
        return {"FINISHED"}


def install():
    bpy.utils.register_class(LogOff)
    bpy.utils.register_class(LogDefault)
    bpy.utils.register_class(LogLess)
    bpy.utils.register_class(LogMore)


def uninstall():
    bpy.utils.unregister_class(LogOff)
    bpy.utils.unregister_class(LogDefault)
    bpy.utils.unregister_class(LogLess)
    bpy.utils.unregister_class(LogMore)
