import bpy
import ragdollc

from ragdollc import registry

from . import viewport, scene, preferences, constants
from .vendor import bpx
from .archetypes import (
    solver,
    marker,
    group,
    pin_constraint,
    distance_constraint,
    environment,
)

state = {
    "installed": False,
    "handlers": dict(),
}

previous_library_count = 0


@bpx.call_once
def minimal_install():
    """Monitor the addition of a new library"""
    bpy.app.handlers.depsgraph_update_post.append(monitor_library_changed)
    bpy.app.handlers.load_post.append(post_file_open)


@bpx.call_once
def install():
    minimal_install()

    bpy.app.handlers.undo_post.append(post_undo_redo)
    bpy.app.handlers.redo_post.append(post_undo_redo)
    bpy.app.handlers.frame_change_pre.append(pre_frame_changed)

    handler = bpy.types.SpaceView3D.draw_handler_add(
        post_viewport_draw, (), "WINDOW", "POST_VIEW"
    )

    state["handlers"][post_viewport_draw] = handler

    handler = bpy.types.WindowManager.draw_cursor_add(
        on_cursor_draw, (), "VIEW_3D", "WINDOW"
    )

    state["handlers"][on_cursor_draw] = handler

    # Subscribe to native application properties
    scene_properties = [
        "use_preview_range",
        "frame_preview_start",
        "frame_preview_end",
        "frame_start",
        "frame_end",
    ]

    render_properties = ["fps", "fps_base"]

    for prop in scene_properties:
        BusSubscriber.subscribe(
            owner_name="scene-timeline",
            key=(bpy.types.Scene, prop),
            notify=post_timeline_changed,
            options={"PERSISTENT"},
        )

    for prop in render_properties:
        BusSubscriber.subscribe(
            owner_name="scene-fps",
            key=(bpy.types.RenderSettings, prop),
            notify=post_timeline_changed,
            options={"PERSISTENT"},
        )

    BusSubscriber.subscribe(
        owner_name="ui-scale",
        key=(bpy.types.PreferencesView, "ui_scale"),
        notify=post_dpi_changed,
        options={"PERSISTENT"},
    )

    ragdollc.handlers.saveState.append(viewport.save_state)
    ragdollc.handlers.restoreState.append(viewport.restore_state)
    ragdollc.handlers.optionSet.append(on_option_set)
    ragdollc.handlers.evaluateStartState.append(evaluate_start_state)
    ragdollc.handlers.evaluateCurrentState.append(evaluate_current_state)
    ragdollc.handlers.evaluateMembers.append(evaluate_members)
    ragdollc.handlers.selectionChanged.append(on_ragdoll_selection_changed)
    ragdollc.handlers.parseInputGeometry.append(marker.parse_input_geometry)
    ragdollc.handlers.executeCommand.append(on_execute_command)

    # Automatically removed upon uninstalling bpx
    bpx.handlers["selection_changed"].append(on_blender_selection_changed)
    bpx.handlers["depsgraph_changed"].append(on_depsgraph_changed)

    bpx.unset_called(uninstall)


def _remove_if_exists(handler, handlers):
    if handler in handlers:
        handlers.remove(handler)


def on_depsgraph_changed(*args):
    viewport.add_evaluation_reason("depsgraph_changed")


@bpx.call_once
def uninstall():
    # events.py is lazily installed on first solver
    _remove_if_exists(post_file_open, bpy.app.handlers.load_post)
    _remove_if_exists(monitor_library_changed,
                      bpy.app.handlers.depsgraph_update_post)

    _remove_if_exists(post_undo_redo, bpy.app.handlers.undo_post)
    _remove_if_exists(post_undo_redo, bpy.app.handlers.redo_post)
    _remove_if_exists(pre_frame_changed, bpy.app.handlers.frame_change_pre)

    try:
        handler = state["handlers"].pop(post_viewport_draw)
        bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
    except KeyError:
        pass

    try:
        handler = state["handlers"].pop(on_cursor_draw)
        bpy.types.WindowManager.draw_cursor_remove(handler)
    except KeyError:
        pass

    BusSubscriber.terminate_all()

    bpx.unset_called(install)
    bpx.unset_called(minimal_install)


@bpx.deferred
def on_option_set(name, value):
    """Ragdoll Core edited a preference"""

    preferences.write(name, value)


"""
Requests to evaluate

Ragdoll will make requests to evaluate various entities as it processes
the scene information. For example, when drawing a solver, if that solver
is visible, it will try and compute all of its members. If any of those
members are enabled and visible, they will in turn be requested to evaluate.

"""


def evaluate_start_state(entity):
    """Ragdoll is requesting the start state of `entity` be evaluated

    When asked to evaluate, Ragdoll will take various state of
    `entity` into account in order to evaluate whether or not to
    evaluate it. For example, if the `entity` is a Marker that is
    disabled, then it will not be evaluated.

    """

    # Support evaluating entities without a Blender representative
    # E.g. for testing
    if not bpx.alias(entity, None):
        return

    arch = registry.archetype(entity)

    if arch == "rdSolver":
        return solver.evaluate_start_state(entity)

    elif arch == "rdMarker":
        return marker.evaluate_start_state(entity)

    elif arch == "rdGroup":
        return group.evaluate_start_state(entity)

    elif arch == "rdPinConstraint":
        return pin_constraint.evaluate_start_state(entity)

    elif arch == "rdDistanceConstraint":
        return distance_constraint.evaluate_start_state(entity)

    elif arch == "rdEnvironment":
        return environment.evaluate_start_state(entity)

    else:
        raise TypeError("Unrecognised arch: %s" % arch)


def evaluate_current_state(entity):
    """Ragdoll is requesting the *current* state of `entity` be evaluated

    Ragdoll separates between "start" and "current", where "start" is the
    initialisation and setup stage where changes to things such as shape
    and hierarchy can happen. The "current" state on the other hand is only
    able to manipulate run-time properties such as position and stiffness.

    """

    if not bpx.alias(entity, None):
        return

    arch = registry.archetype(entity)

    if arch == "rdSolver":
        return solver.evaluate_current_state(entity)

    if arch == "rdMarker":
        return marker.evaluate_current_state(entity)

    if arch == "rdGroup":
        return group.evaluate_current_state(entity)

    if arch == "rdPinConstraint":
        return pin_constraint.evaluate_current_state(entity)

    elif arch == "rdDistanceConstraint":
        return distance_constraint.evaluate_current_state(entity)

    if arch == "rdEnvironment":
        return environment.evaluate_current_state(entity)


def evaluate_members(entity):
    """Ragdoll is requesting that the SceneComponent is updated

    At this point, Ragdoll will have cleared the SceneComponent
    due to a change in the membership of `entity`, such as a Solver.
    When this happens, we must update the SceneComponent such
    that it accurately reflects members of the `entity`.

    """

    if not bpx.alias(entity, None):
        pass

    arch = registry.archetype(entity)

    if arch == "rdSolver":
        return solver.evaluate_members(entity)


@bpx.deferred
def on_ragdoll_selection_changed():
    """Selection was changed from within Ragdoll, e.g. via the Manipulator

    Reflect this change in Blender as well, such that properties
    can be edited both natively and via the Manipulator UI.

    """

    selection = []

    for entity in ragdollc.scene.selection():
        xobj = bpx.alias(entity)
        if xobj is not None:
            selection.append(xobj)

    if selection:
        bpx.select(selection)
    else:
        bpx.deselect_all()

    bpy.ops.ed.undo_push(message="Ragdoll select")


@bpx.with_cumulative_timing
def on_blender_selection_changed(selection):
    """Selection was changed in Blender

    Reflect this change in Ragdoll, such that we get
    highlighting and outlining.

    NOTE: Selection changing from within Ragdoll will trigger
          this callback as well, resulting in double-selection.
          This is harmless and will not propagate any further.

    """

    ragdollc.scene.deselect()

    for sel in selection:
        entity = sel.data.get("entity", None)

        if isinstance(entity, int):
            ragdollc.scene.select(entity, append=True)

    # Hide anything with a DrawableComponent that is hidden in Blender
    for xobj in bpx.ls():
        entity = xobj.data.get("entity")

        if not entity:
            continue

        Drawable = registry.get("DrawableComponent", entity)
        if not Drawable:
            continue

        Drawable.visible = xobj.visible()

    bpx.report_cumulative_timings()


@bpx.deferred
def on_execute_command(command):
    scene.on_execute_command(command)


def post_viewport_draw():
    viewport.draw()


def on_cursor_draw(_mouse_pos):
    pass


def on_library_added_or_removed():
    # Objects can exist in a linked library, which to the user
    # appears like any other object. Except they are not in the
    # current scene as above, but rather nested in a collection
    if not len(bpy.data.libraries):
        return

    # Refresh all bpx objects
    for col in bpy.data.collections:
        if not col.library:
            continue

        for obj in col.objects:
            bpx.BpxType(obj)

    bpx.dirty_all()


@bpy.app.handlers.persistent
@bpx.with_cumulative_timing
def monitor_library_changed(scene, depsgraph):
    """Monitor for when a new library is added

    Blender does not provide any means of know whether the user
    links a new scene into the currently open scene. Even though
    it happens via an operator, not even the operators from:
    bpy.context.window_manager.operators[-1] is able to indicate
    whether the operator used was the scene linking one.

    Thus, we resort to the heavy-handed approach of listening
    to every single event in Blender to see whether one of them
    created a new library.

    """

    global previous_library_count
    library_count = len(bpy.data.libraries)

    if library_count != previous_library_count:
        on_library_added_or_removed()
        previous_library_count = library_count


@bpy.app.handlers.persistent
def post_file_open(*_args):
    scene.post_file_open()
    viewport.add_evaluation_reason("file_open")

    # Message bus subscriptions (Must re-register on scene load)
    BusSubscriber.resubscribe_all()


def post_timeline_changed():
    blscene = bpy.context.scene

    fps = blscene.render.fps
    timestep = 1.0 / fps

    start_frame = blscene.frame_start
    end_frame = blscene.frame_end

    if blscene.use_preview_range:
        start_frame = blscene.frame_preview_start
        end_frame = blscene.frame_preview_end

    for rdsolver in bpx.ls(type="rdSolver"):
        entity = rdsolver.data["entity"]
        Time = registry.get("TimeComponent", entity)

        start_mode = rdsolver["startTime"].read()

        if start_mode == constants.PlaybackStart:
            Time.startFrame = blscene.frame_start

        elif start_mode == constants.PreviewStart:
            Time.startFrame = blscene.frame_preview_start

        else:
            Time.startFrame = rdsolver["startTimeCustom"].read()

        Time.endFrame = end_frame
        Time.fixedTimestep = timestep

    ragdollc.scene.setFrameRange(start_frame, end_frame, timestep)


@bpy.app.handlers.persistent
def pre_frame_changed(*_args):
    manip = registry.ctx("Manipulator")

    if manip.active and manip.mode == manip.LiveMode:
        return

    frame = bpy.context.scene.frame_current

    # Only pass on the change if there was an actual difference
    # Zero difference can happen when dragging on the time slider
    # without dragging far enough to account for 1 whole frame.
    if frame != getattr(pre_frame_changed, "last_frame", None):
        ragdollc.scene.setCurrentFrame(frame)
        viewport.add_evaluation_reason("time_changed")

    pre_frame_changed.last_frame = frame


@bpx.with_cumulative_timing
@bpy.app.handlers.persistent
def post_undo_redo(blscene, *_):
    scene.post_undo_redo()
    viewport.add_evaluation_reason("undo_redo")


def post_dpi_changed():
    pref = bpy.context.preferences
    value = pref.view.ui_scale * pref.system.ui_scale
    preferences.write("ragdollDpiScale", value)


class BusSubscriber:
    """bpy.msgbus subscription management interface"""
    all_subscribers = {}

    def __init__(self, name: str):
        self.name = name
        self.subscriptions = {}

    @classmethod
    def subscribe(cls, owner_name, key, notify, args=None, options=None):
        """Add one subscription"""
        if owner_name not in cls.all_subscribers:
            cls.all_subscribers[owner_name] = cls(owner_name)
        owner = cls.all_subscribers[owner_name]

        if key in owner.subscriptions:
            return

        subscription = {
            "key": key,
            "args": args or (),
            "notify": notify,
            "options": options or set(),
        }
        owner.subscriptions[key] = subscription
        bpy.msgbus.subscribe_rna(owner=owner, **subscription)  # noqa

    @classmethod
    def terminate(cls, owner_name):
        """Cancel one subscriber's all subscriptions."""
        if owner_name not in cls.all_subscribers:
            return

        owner = cls.all_subscribers.pop(owner_name)
        # NOTE: This may lead to tbbmalloc memory access violation crash
        #   if not being handled well. So be careful when modifying this
        #   code.
        bpy.msgbus.clear_by_owner(owner)  # noqa

    @classmethod
    def terminate_all(cls):
        """Unsubscribe all subscriptions"""
        for name in list(cls.all_subscribers.keys()):
            cls.terminate(name)

    @classmethod
    def resubscribe_all(cls):
        """Resubscribe all subscriptions"""
        for name, owner in cls.all_subscribers.items():
            for subscription in owner.subscriptions.values():
                bpy.msgbus.subscribe_rna(owner=owner, **subscription)  # noqa
