import sys
import bpy
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

    # UI, the order of installation affects panels default rendering order
    icons.install()
    menus.install()

    solver_ui.install()
    group_ui.install()
    marker_ui.install()
    pin_constraint_ui.install()
    distance_constraint_ui.install()
    environment_ui.install()

    # Let uninstall be called once again
    bpx.unset_called(uninstall)

    log.info("Successfully loaded Ragdoll")


@bpx.call_once
def uninstall():
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
    bpx.uninstall()

    # Erase all trace
    for module in sys.modules.copy():
        if module.startswith("ragdoll."):
            sys.modules.pop(module)

    # Let install be called once again
    bpx.unset_called(install)

    # Message operator has been unregistereed
    print("Successfully unloaded Ragdoll")
