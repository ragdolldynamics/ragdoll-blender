import bpy
import math
import ctypes


E_SPACE_EMPTY = 0
E_SPACE_VIEW3D = 1
E_SPACE_GRAPH = 2
E_SPACE_OUTLINER = 3
E_SPACE_PROPERTIES = 4
E_SPACE_FILE = 5
E_SPACE_IMAGE = 6
E_SPACE_INFO = 7
E_SPACE_SEQ = 8
E_SPACE_TEXT = 9
E_SPACE_ACTION = 12
E_SPACE_NLA = 13
E_SPACE_SCRIPT = 14
E_SPACE_NODE = 16
E_SPACE_CONSOLE = 18
E_SPACE_USERPREF = 19
E_SPACE_CLIP = 20
E_SPACE_TOPBAR = 21
E_SPACE_STATUSBAR = 22
E_SPACE_SPREADSHEET = 23


def create_window(
        width: int,
        height: int,
        space_type: int,
) -> bpy.types.Window:
    """Create new window with specified size and space type"""

    # There's no API for creating window with size specified, nor API for
    # resizing existing window. Best chance you get is to split up an area
    # into the size you need and then run `bpy.ops.screen.area_dupli()` to
    # duplicate that area as a window.
    #
    # Fortunately, with ctypes and `bpy.ops.wm.window_new()`, we can trick
    # blender to create new window in any size we want, even able to specify
    # which space type (Editor Type).
    #
    # From reading the source code of `wm.window_new()` operator (function
    # `wm_window_new_exec` in `blender/windowmanager/intern/wm_window.cc`),
    # we learnt that new window size is determined by current window. 95%
    # of its width and 90% of its height. And the space type is determined
    # by the biggest area in current window screen. Here's the simplified
    # source code:
    #
    # ```
    # int wm_window_new_exec(bContext *C, wmOperator *op)
    # {
    #     wmWindow *win_src = CTX_wm_window(C);
    #     ScrArea *area = BKE_screen_find_big_area(CTX_wm_screen(C), ...);
    #     const rcti window_rect = {
    #         0,
    #         int(win_src->sizex * 0.95f),
    #         0,
    #         int(win_src->sizey * 0.9f),
    #     };
    #
    #     bool ok = (WM_window_open(..., area->spacetype, ...) != nullptr);
    #
    #     // do return
    # }
    # ```
    #
    # So, what we need to do is to change `win_src.sizex`, `win_src.sizey`,
    # and `area->spacetype` before calling `bpy.ops.wm.window_new()`, then
    # restore values afterward.
    #
    # Note that changing `win_src.sizex` and `sizey` does not resize window.
    # Those two were just cached values for other computations, therefore we
    # still need to restore them back. The true windowing tasks are done via
    # another beast, GHOST API (Generic Handy Operating System Toolkit).

    window_manager = bpy.context.window_manager
    window = bpy.context.window
    screen = bpy.context.screen
    area = screen_find_big_area(screen)

    c_window = _get_content(window.as_pointer(), _WM_WINDOW)
    c_area = _get_content(area.as_pointer(), _SCREEN_AREA)

    original_spacetype = c_area.spacetype
    original_width = c_window.sizex
    original_height = c_window.sizey

    c_area.spacetype = space_type
    c_window.sizex = math.ceil(width / 0.95)
    c_window.sizey = math.ceil(height / 0.9)
    try:
        bpy.ops.wm.window_new()
    finally:
        c_area.spacetype = original_spacetype
        c_window.sizex = original_width
        c_window.sizey = original_height

    new_window = window_manager.windows[-1]
    return new_window


def screen_find_big_area(screen: bpy.types.Screen) -> bpy.types.Area:
    """Returns biggest sized area in given screen

    Ported from:
    https://github.com/blender/blender/blob/v4.0.0/source/blender/blenkernel/intern/screen.cc#L831

    """

    big = None
    maxsize = 0

    for area in screen.areas:
        if area.width >= 0 and area.height >= 0:
            size = area.width * area.height
            if size > maxsize:
                maxsize = size
                big = area

    return big


def _get_content(ptr, type_):
    _ptr = ctypes.cast(ptr, ctypes.POINTER(type_))
    return _ptr.contents if _ptr else None


# Interface for underlying C struct
#
# NOTE: The order and type of members must match that of the struct.
#       At least up until the member we want, i.e. spacetype, sizey.
#       The below was derived from Blender 4.0 (tested in version 3.4)
#
_PLACEHOLDER = type("_PLACEHOLDER", (ctypes.Structure,), {})

# ListBase
_LIST_BASE = type("_LIST_BASE", (ctypes.Structure,), {
    "_fields_": [
        ("first", ctypes.c_void_p),
        ("last", ctypes.c_void_p),
    ]
})

# ScrAreaMap
_SCREEN_AREA_MAP = type("_SCREEN_AREA_MAP", (ctypes.Structure,), {
    "_fields_": [
        ("vertbase", _LIST_BASE),
        ("edgebase", _LIST_BASE),
        ("areabase", _LIST_BASE),
    ]
})

# rcti
_RCTI = type("_RCTI", (ctypes.Structure,), {
    "_fields_": [
        ("xmin", ctypes.c_int),
        ("xmax", ctypes.c_int),
        ("ymin", ctypes.c_int),
        ("ymax", ctypes.c_int),
    ]
})

# ScrArea
# https://github.com/blender/blender/blob/v4.0.0/source/blender/makesdna/DNA_screen_types.h#L367
_SCREEN_AREA = type("_SCREEN_AREA", (ctypes.Structure,), {
    "_fields_": [
        ("next", ctypes.POINTER(_PLACEHOLDER)),
        ("prev", ctypes.POINTER(_PLACEHOLDER)),
        ("v1", ctypes.POINTER(_PLACEHOLDER)),
        ("v2", ctypes.POINTER(_PLACEHOLDER)),
        ("v3", ctypes.POINTER(_PLACEHOLDER)),
        ("v4", ctypes.POINTER(_PLACEHOLDER)),
        ("full", ctypes.POINTER(_PLACEHOLDER)),
        ("totrct", _RCTI),
        ("spacetype", ctypes.c_char),
    ]
})

# wmWindow
# https://github.com/blender/blender/blob/v4.0.0/source/blender/makesdna/DNA_windowmanager_types.h#L242
_WM_WINDOW = type("_WM_WINDOW", (ctypes.Structure,), {
    "_fields_": [
        ("next", ctypes.POINTER(_PLACEHOLDER)),
        ("prev", ctypes.POINTER(_PLACEHOLDER)),
        ("ghostwin", ctypes.c_void_p),
        ("gpuctx", ctypes.c_void_p),
        ("parent", ctypes.POINTER(_PLACEHOLDER)),
        ("scene", ctypes.POINTER(_PLACEHOLDER)),
        ("new_scene", ctypes.POINTER(_PLACEHOLDER)),
        ("view_layer_name", ctypes.c_char * 64),
        ("unpinned_scene", ctypes.POINTER(_PLACEHOLDER)),
        ("workspace_hook", ctypes.POINTER(_PLACEHOLDER)),
        ("global_areas", _SCREEN_AREA_MAP),
        ("screen", ctypes.POINTER(_PLACEHOLDER)),
        ("winid", ctypes.c_int),
        ("posx", ctypes.c_short),
        ("posy", ctypes.c_short),
        ("sizex", ctypes.c_short),
        ("sizey", ctypes.c_short),
    ]
})
