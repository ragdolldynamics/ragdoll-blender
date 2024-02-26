import os
import re
import logging
import webbrowser
from datetime import datetime, timedelta, date as date_

import bpy
import ragdollc
from ragdollc import registry

from ..ui import icons, draw


# Common code
STATUS_OK = 0  # All OK
STATUS_FAIL = 1  # General error
STATUS_INET = 4  # Connection to the server failed
STATUS_EXPIRED = 13  # Activation expired
STATUS_FEATURES_CHANGED = 22  # Licence fields have changed
STATUS_TRIAL_EXPIRED = 30  # Trial expired

_opt = dict(options={"SKIP_SAVE", "HIDDEN"})

# Some product names have different name externally
# Prefer the externally marketable name.
product_to_brand = {
    "enterprise": "unlimited",
    "headless": "batch",
}


class Licence(bpy.types.Operator):
    bl_idname = "ragdoll.licence"
    bl_label = "Licence"
    bl_options = {"INTERNAL"}
    bl_description = "Ragdoll Licencing Dialog"

    changed = True

    is_activated: bpy.props.BoolProperty(**_opt)
    is_trial: bpy.props.BoolProperty(**_opt)
    trial_days: bpy.props.IntProperty(name="Trial Days Remain", **_opt)
    expires: bpy.props.BoolProperty(**_opt)
    expiry: bpy.props.StringProperty(**_opt)
    expiry_date: bpy.props.StringProperty(name="Expiry Date", **_opt)
    serial: bpy.props.StringProperty(name="Product Key", **_opt)
    floating: bpy.props.StringProperty(**_opt)
    product: bpy.props.StringProperty(name="Licence Type", **_opt)
    is_expired: bpy.props.BoolProperty(**_opt)

    def execute(self, context):

        ragdollc.install()

        Licence.changed = True
        dpi_scale = context.preferences.system.ui_scale
        width = int(360 * dpi_scale)
        return context.window_manager.invoke_popup(self, width=width)

    def update_licence(self):
        licence = registry.ctx("LicenceComponent")

        self.is_activated = licence.isActivated
        self.is_trial = licence.isTrial
        self.trial_days = licence.trialDays
        self.expires = licence.expires
        self.expiry = licence.expiry
        self.serial = licence.serial
        self.product = licence.product
        self.floating = os.environ.get("RAGDOLL_FLOATING", "")

        self.product = "Ragdoll %s" % product_to_brand.get(
            self.product,
            self.product
        ).capitalize()

        if self.is_trial:
            self.is_expired = self.trial_days == 0
            self.expiry_date = (
                datetime.now() + timedelta(days=self.trial_days)
            ).strftime("%Y.%m.%d")

        else:
            if self.expires:
                # The exact way how internal licencing module computed
                dt = _format_expiry(self.expiry, "expiry")
                expiry_date = date_.fromordinal(dt.toordinal())
                self.is_expired = expiry_date < date_.today()
                self.expiry_date = dt.strftime("%Y.%m.%d")
            else:
                self.is_expired = False
                self.expiry_date = "Perpetual"

        Licence.changed = False

    def draw(self, context):
        layout = self.layout

        if Licence.changed:
            self.update_licence()

        layout.label(text="Ragdoll Licencing",
                     icon_value=icons.fname_to_icon_id["logo2.png"])

        row = layout.row()
        row.enabled = not Licence.changed
        row.use_property_split = True

        body = row.column()

        status_box = body.box()

        status_row = status_box.column()
        status_row.enabled = False

        status_icon = status_row.column()
        status_icon.label(
            text="Expired" if self.is_expired else "Status",
            icon=("SEQUENCE_COLOR_01" if self.is_expired else
                  "SEQUENCE_COLOR_04"),
        )

        product_col = status_row.column()
        product_col.prop(self, "product")

        if self.is_trial:
            trail_col = status_row.column()
            trail_col.prop(self, "trial_days")

        expiry_col = status_row.column()
        expiry_col.prop(self, "expiry_date")

        body.separator()

        if self.floating:
            floating_box = body.box()
            floating_row = floating_box.column()

            server_col = floating_row.column()
            server_col.enabled = not self.is_activated
            server_col.prop(self, "floating", text="Server")

        else:
            activation_box = body.box()
            activation_row = activation_box.column()

            serial_col = activation_row.column()
            serial_col.enabled = not self.is_activated
            serial_col.prop(self, "serial")

            active_col = activation_row.column()

            active_row = active_col.row()
            active_row.separator()
            active_row.label(text="")

            button_row = active_row.row()
            button_row.scale_x = 0.6

            if self.is_activated:
                button_row.operator_context = "INVOKE_DEFAULT"
                op = button_row.operator(
                    "ragdoll.licence_node_locked",
                    text="Deactivate",
                )
                op.is_activated = self.is_activated

            else:
                button_row.operator_context = "EXEC_DEFAULT"
                op = button_row.operator(
                    "ragdoll.licence_node_locked",
                    text="Activate",
                )
                op.serial = self.serial
                op.is_activated = self.is_activated

            active_row.separator(factor=2)

        body.separator()


def _format_expiry(date_string, key):

    try:
        return datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S")

    except TypeError:
        # This should not happen.
        _error("Please try restarting Blender: "
               "Unexpected datetime type from %r: %r" % (key, date_string))

    except ValueError:
        # Sometimes we get invalid date string for reasons, e.g.
        # licence changed without plugin reload, or floating
        # server is not available. Here we just return present
        # time as expired to indicate something went wrong.
        _error("Please try restarting Blender: "
               "Bad datetime string from %r: %r" % (key, date_string))

    return datetime.now()


class LicenceNodeLocked(bpy.types.Operator):
    bl_idname = "ragdoll.licence_node_locked"
    bl_label = ""
    bl_options = {"INTERNAL"}
    bl_description = "Activate/Deactivate Ragdoll node-locked licence"

    serial: bpy.props.StringProperty(**_opt)
    is_activated: bpy.props.BoolProperty(**_opt)
    width: bpy.props.IntProperty(default=400)

    def invoke(self, context, _event):
        if not self.is_activated:
            return {"FINISHED"}
        return context.window_manager.invoke_props_dialog(self,
                                                          width=self.width)

    def draw(self, _context):
        deactivation_warning = (
            "Do you want me to deactivate Ragdoll on this machine? "
            "I'll try and revert to a trial licence."
            "\n"
            "WARNING: This will close your currently opened file"
        )

        layout = self.layout
        layout.label(text="Deactivate Ragdoll", icon="ERROR")

        text_box = layout.box()
        draw.multi_lines(text_box, deactivation_warning, self.width)

    def execute(self, context):
        if self.is_activated:
            result = ragdollc.licence.deactivate()
        else:
            if not self.is_serial_valid():
                self.report({"ERROR"}, "Invalid product key.")
                return {"CANCELLED"}

            result = ragdollc.licence.activate(self.serial)

        Licence.changed = True

        if result != STATUS_OK:
            self.report({"ERROR"}, f"Ragdoll Licencing Error: {result}")

        return {"FINISHED"}

    def is_serial_valid(self):
        validator = "^" + "-".join(["[0-9A-Z]{4}"] * 7) + "$"
        return bool(re.match(validator, self.serial))


class LicenceOffline(bpy.types.Operator):
    bl_idname = "ragdoll.licence_offline"
    bl_label = ""
    bl_options = {"INTERNAL"}

    serial: bpy.props.StringProperty(**_opt)
    is_activated: bpy.props.BoolProperty(**_opt)

    def execute(self, context):
        return {"FINISHED"}


class LicenceFloating(bpy.types.Operator):
    bl_idname = "ragdoll.licence_floating"
    bl_label = ""
    bl_options = {"INTERNAL"}

    floating: bpy.props.StringProperty(**_opt)
    is_activated: bpy.props.BoolProperty(**_opt)

    def execute(self, context):
        return {"FINISHED"}


class LicenceShowPricing(bpy.types.Operator):
    bl_idname = "ragdoll.licence_show_pricing"
    bl_label = "Pricing"
    bl_options = {"INTERNAL"}

    def execute(self, _context):
        url = "https://ragdolldynamics.com/pricing"
        if bpy.app.background:
            self.report({"WARNING"}, url)
        else:
            webbrowser.open(url)
        return {"FINISHED"}


class NotifyWithPricing(bpy.types.Operator):
    bl_idname = "ragdoll.notify_with_pricing"
    bl_label = "Ragdoll"
    bl_options = {"INTERNAL"}

    icon: bpy.props.StringProperty()
    title: bpy.props.StringProperty()
    message: bpy.props.StringProperty()
    width: bpy.props.IntProperty(default=400)

    def execute(self, _context):
        return {"FINISHED"}

    def invoke(self, context, _event):
        rt = context.window_manager.invoke_props_dialog(self, width=self.width)
        bpy.ops.ragdoll.user_message(
            level=logging.WARNING,
            message=self.message
        )
        return rt

    def draw(self, _context):
        layout = self.layout
        layout.label(text=self.title, icon=self.icon)

        text_box = layout.box()
        draw.multi_lines(text_box, self.message, self.width)

        layout.operator("ragdoll.licence_show_pricing")


def _error(message):
    import traceback

    trace = traceback.format_exc()
    if trace:
        print(trace)
        message += "\n" + trace

    def _on_idle():
        wm = bpy.context.window_manager
        if wm.is_interface_locked:
            return 0.1

        bpy.ops.ragdoll.user_message(
            level=40,  # logging.ERROR
            message=message,
        )

    bpy.app.timers.register(_on_idle)


_classes = (
    Licence,
    LicenceFloating,
    LicenceNodeLocked,
    LicenceOffline,
    LicenceShowPricing,
    NotifyWithPricing,
)


def install():
    for cls in _classes:
        bpy.utils.register_class(cls)


def uninstall():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
