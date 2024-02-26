import bpy
import blf
import gpu
import logging
import traceback

from gpu_extras import batch as gpu_batch
from bpy_extras import view3d_utils as v3d

from . import tag_redraw


class EyedropperMixin:
    """Customizable eyedropper operator mixin-class

    You MUST subclass this base class to make things work.

    """

    _cursor = (-1, -1)
    _handler = None
    _hit = None
    _point_size = 0

    def hit_types(self) -> set[str]:
        """Returns a set of Object type name for filtering

        This function returns an empty set by default, therefore no filtering
        and all types of object can be picked.

        Reimplement this function to make your own filter. Should return
        e.g. `{"MESH"}` for only picking mesh type object.

        Please visit Blender API doc for `bpy.types.Object.type` and find out
        valid "Object Type Items".

        """
        return set()

    def on_clicked(self,
                   hit_object: bpy.types.Object,
                   context: bpy.types.Context) -> set[str]:
        """Function for processing picked object

        This function simply returns `{"FINISHED"}` and does nothing on
        eyedropper picked object.

        Reimplement this function to make it useful.

        Return value MUST be `{"FINISHED"}` or `{"CANCELLED"}`, just like
        operator `execute()`.

        Arguments:
            hit_object: Eyedropper picked object
            context: Blender context instance

        """
        return {"FINISHED"}

    @staticmethod
    def _draw_callback(cls, hit_types):
        context = bpy.context
        region = context.region
        region_3d = context.space_data.region_3d

        cursor = cls._cursor
        current_area = context.area
        cursor = (
            cursor[0] - current_area.x,
            cursor[1] - current_area.y
        )

        # Hit test

        origin = v3d.region_2d_to_origin_3d(region, region_3d, cursor)
        direction = v3d.region_2d_to_vector_3d(region, region_3d, cursor)

        dg = context.evaluated_depsgraph_get()
        r = context.scene.ray_cast(dg, origin, direction)
        hit = r[4]

        if hit and (not hit_types or hit.type in hit_types):
            cls._hit = hit
        else:
            cls._hit = None
            return

        # Hit.
        # Draw object name.

        object_name = hit.name
        pad = cls._point_size // 2  # padding
        offset = pad
        font_id = 0  # default font
        blf.size(font_id, cls._point_size)

        w, h = blf.dimensions(font_id, object_name)
        left = cursor[0] + offset
        right = left + w
        top = cursor[1] - offset
        bottom = top - h

        # Backdrop
        #  _______________
        # |_______________|
        #
        vertices = (
            (left - pad, top + pad),
            (right + pad, top + pad),
            (left - pad, bottom - pad),
            (right + pad, bottom - pad)
        )
        indices = ((0, 1, 2), (2, 1, 3))
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = gpu_batch.batch_for_shader(
            shader,
            "TRIS",
            {"pos": vertices},
            indices=indices,
        )
        shader.uniform_float("color", (0.02, 0.02, 0.02, 1.0))
        batch.draw(shader)

        # Text
        #  _______________
        # |__Object_Name__|
        #
        blf.position(font_id, left, bottom, 0)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.draw(font_id, object_name)

    def _teardown(self, context):
        cls = self.__class__
        cls._hit = None
        cls._cursor = (-1, -1)

        if cls._handler:
            bpy.types.SpaceView3D.draw_handler_remove(cls._handler, "WINDOW")
            cls._handler = None
            tag_redraw(context.screen)

        if context.window:
            context.window.cursor_modal_restore()

    def invoke(self, context, event):
        cls = self.__class__
        cls._cursor = (event.mouse_region_x, event.mouse_region_y)
        cls._handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback,
            (cls, self.hit_types()),
            "WINDOW",
            "POST_PIXEL",
        )
        pref = context.preferences
        cls._point_size = pref.ui_styles[0].widget_label.points
        cls._point_size *= pref.system.ui_scale

        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set("EYEDROPPER")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        cls = self.__class__  # makes linter happy

        if event.type == "RIGHTMOUSE" or event.type == "ESC":
            return {"CANCELLED"}

        elif event.type == "MOUSEMOVE":
            cls._cursor = (event.mouse_x, event.mouse_y)
            tag_redraw(context.screen)  # Drives our draw handler

        elif event.type == "LEFTMOUSE" and event.value == "RELEASE":
            return self._on_clicked(context)

        elif event.type == "LEFTMOUSE":
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    def __del__(self):
        self._teardown(bpy.context)

    def cancel(self, context):
        self._teardown(context)

    def _on_clicked(self, context):
        cls = self.__class__  # makes linter happy
        hit_object = cls._hit

        try:
            status = self.on_clicked(hit_object, context)

        except Exception as e:
            # Handling all unhandled error to ensure modal ends
            traceback.print_exc()
            bpy.ops.ragdoll.user_message(
                level=logging.WARNING,
                message="Eyedropper failed: %s" % str(e),
            )
            status = {"CANCELLED"}

        self._teardown(context)
        tag_redraw(context.screen)

        return status
