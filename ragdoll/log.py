import bpy
import logging

from .vendor import bpx


def debug(message):
    """Show message only in Blender Info panel

    Important: This is GUI based logging, do not use this in e.g. an eval loop
        as it may make GUI a bit unresponsive in such scenario.

    """
    _message(message, logging.DEBUG)
    return True


def info(message):
    """Show message in Info panel and status bar, as info

    Important: This is GUI based logging, do not use this in e.g. an eval loop
        as it may make GUI a bit unresponsive in such scenario.

    """
    _message(message, logging.INFO)
    return True


def warning(message):
    """Show message in Info panel and status bar, as warning

    Important: This is GUI based logging, do not use this in e.g. an eval loop
        as it may make GUI a bit unresponsive in such scenario.

    """
    _message(message, logging.WARNING)
    return False


def error(message):
    """Show message everywhere and a pop-up bubble

    Important: This is GUI based logging, do not use this in e.g. an eval loop
        as it may make GUI a bit unresponsive in such scenario.

    """
    _message(message, logging.ERROR)
    return False


class UserMessage(bpy.types.Operator):
    """An operator for displaying pop-up notification"""
    bl_idname = "ragdoll.user_message"
    bl_label = ""
    bl_options = {"INTERNAL"}

    level: bpy.props.IntProperty()  # for message icon
    message: bpy.props.StringProperty()

    def modal(self, _context, _event):
        level = {
            10: "OPERATOR",  # Only in Info panel
            20: "INFO",      # Displayed in Info panel and status bar
            30: "WARNING",   # Displayed in Info panel and status bar
            40: "ERROR",     # Everywhere and a pop-up bubble
        }.get(self.level, "ERROR")

        self.report({level}, f"Ragdoll: {self.message}")
        return {"FINISHED"}

    def execute(self, context):
        if bpx._LOG.level > self.level:
            return {"FINISHED"}

        # We need to start a modal session so the GUI can redraw to ensure
        # the message is displayed and pass to Info panel. Or we only see
        # it in console.
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


def _message(message, level):
    def _on_idle():
        wm = bpy.context.window_manager
        if wm.is_interface_locked:
            return 0.1

        bpy.ops.ragdoll.user_message(
            level=level,
            message="%s" % message,
        )

    bpy.app.timers.register(_on_idle)


@bpx.call_once
def install():
    bpy.utils.register_class(UserMessage)
    bpx.unset_called(uninstall)


@bpx.call_once
def uninstall():
    bpy.utils.unregister_class(UserMessage)
    bpx.unset_called(install)
