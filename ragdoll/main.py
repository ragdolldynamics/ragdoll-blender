import os
import sys
import bpy
import inspect
import ragdollc

from . import log, events, scene, preferences

from .operators import (
    assign_markers,
    assign_environment,
    create_solver,
    create_pin_constraint,
    create_attach_constraint,
    create_distance_constraint,
    create_ground,
    manipulator,
    record_simulation,
    snap_to_simulation,
    retarget_ui,
    io,
    delete_physics,
    edit_solver,
    edit_marker,
    logging_level,
    licence,
)
from .archetypes import (
    group,
    solver,
    pin_constraint,
    distance_constraint,
    marker,
    environment,
)
from .ui import (
    icons,
    menus,
    solver as solver_ui,
    group as group_ui,
    marker as marker_ui,
    pin_constraint as pin_constraint_ui,
    distance_constraint as distance_constraint_ui,
    environment as environment_ui,
)

from .vendor import bpx


@bpx.call_once
def install():
    # For ordered selection
    bpx.install()

    ragdollc.install()

    # Do not consume any CPU or risk any exception being
    # thrown until the user actively uses Ragdoll
    events.minimal_install()

    preferences.install()
    log.install()
    scene.install()

    # Archetypes
    pin_constraint.install()
    distance_constraint.install()
    group.install()
    solver.install()
    marker.install()
    environment.install()

    # Operators
    assign_markers.install()
    assign_environment.install()
    create_solver.install()
    create_pin_constraint.install()
    create_attach_constraint.install()
    create_distance_constraint.install()
    create_ground.install()
    manipulator.install()
    record_simulation.install()
    snap_to_simulation.install()
    io.install()
    retarget_ui.install()
    delete_physics.install()
    edit_solver.install()
    edit_marker.install()
    logging_level.install()
    licence.install()

    # UI
    icons.install()
    menus.install()

    # NOTE: The order of installation affects panels default rendering order.
    #   For example, if marker panel installed before group, in a new scene
    #   you should see that marker panel is on top of Properties Panel and
    #   group at the bottom (if selected marker has group).
    solver_ui.install()
    marker_ui.install()
    group_ui.install()
    pin_constraint_ui.install()
    distance_constraint_ui.install()
    environment_ui.install()

    # Let uninstall be called once again
    bpx.unset_called(uninstall)

    log.info("Successfully loaded Ragdoll")


@bpx.call_once
def uninstall():
    if not _is_uninstall_on_blender_exit():
        recovery = _save_session_recovery()
        log.info("Unloading Ragdoll. Saved session recovery to %r" % recovery)
        # Can't have any Ragdoll nodes in the scene if
        # the Ragdoll property groups no longer exists
        bpy.ops.wm.read_homefile(use_empty=True)

    solver_ui.uninstall()
    group_ui.uninstall()
    marker_ui.uninstall()
    pin_constraint_ui.uninstall()
    distance_constraint_ui.uninstall()
    environment_ui.uninstall()

    menus.uninstall()
    icons.uninstall()
    scene.uninstall()

    pin_constraint.uninstall()
    distance_constraint.uninstall()
    group.uninstall()
    solver.uninstall()
    marker.uninstall()
    environment.uninstall()

    assign_markers.uninstall()
    assign_environment.uninstall()
    create_solver.uninstall()
    create_pin_constraint.uninstall()
    create_attach_constraint.uninstall()
    create_distance_constraint.uninstall()
    create_ground.uninstall()
    manipulator.uninstall()
    record_simulation.uninstall()
    snap_to_simulation.uninstall()
    io.uninstall()
    retarget_ui.uninstall()
    delete_physics.uninstall()
    edit_solver.uninstall()
    edit_marker.uninstall()
    logging_level.uninstall()
    licence.uninstall()

    events.uninstall()
    log.uninstall()
    preferences.uninstall()

    # NOTE: We don't call `ragdollc.uninstall()` because we cannot unload
    #   .pyd module in Blender.

    bpx.uninstall()

    # Erase all trace
    for module in sys.modules.copy():
        if module.startswith("ragdoll."):
            sys.modules.pop(module)

    # Let install be called once again
    bpx.unset_called(install)

    # Message operator has been unregistereed
    print("Successfully unloaded Ragdoll")


def _is_uninstall_on_blender_exit():
    """Return True if addon is being unloaded by closing Blender
    """

    for frame_info in inspect.stack():
        if frame_info.function != "disable_all":
            continue

        module = inspect.getmodule(frame_info.frame)
        if module and module.__name__ == "addon_utils":
            return True

    return False


def _save_session_recovery():
    # Referenced from `WM_exit_ex` in
    # `source/blender/windowmanager/intern/wm_init_exit.cc`
    last_session = os.path.join(
        os.path.dirname(os.path.normpath(bpy.app.tempdir)),
        "quit.blend"
    )
    bpy.ops.wm.save_as_mainfile(filepath=last_session, copy=True)

    return last_session
