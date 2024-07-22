"""This addon is a bridge between Blender and Ragdoll"""

import os
import sys
import platform

import bpy

bl_info = {
    "name": "Ragdoll",
    "version": (2077, 7, 7),        # Auto generated. DO NOT TOUCH!
    "blender": (3, 3, 0),           # The minimum Blender version required
    "ragdollcore": (2024, 5, 23),   # The minimum Ragdoll Core version required
    "category": "Animation",
    "author": "Ragdoll Dynamics",
    "description": "Animate with real-time physics.",
    "location": "Physics Properties",
    "doc_url": "https://learn.ragdolldynamics.com/overview/",
    "tracker_url": "https://forums.ragdolldynamics.com/",
}


PLATFORM_NAME = platform.system().lower()
CORE_VERSION = ".".join("%02d" % i for i in bl_info["ragdollcore"])

# Defined when Ragdoll should use a floating licence, formatted as:
# IP:PORT e.g. 127.0.0.1:8001
RAGDOLL_FLOATING = os.getenv("RAGDOLL_FLOATING")

# Let's get the basics right
assert PLATFORM_NAME in ("windows", "linux", "darwin"), (
    "%s unsupported platform" % PLATFORM_NAME
)

LICENCE_STATE = set()


def get_install_dir():
    if PLATFORM_NAME == "windows":
        prefix = ""
        suffix = "dll"
        root = os.getenv("PROGRAMFILES")
        path = os.path.join(
            root, "Ragdoll Dynamics", "Core", CORE_VERSION, "lib"
        )

    elif PLATFORM_NAME == "darwin":
        prefix = "lib"
        suffix = "so"
        path = "Not yet implemented"

    else:
        prefix = "lib"
        suffix = "so"
        root = os.path.expanduser("~")
        path = os.path.join(
            root, "ragdolldynamics", "core", CORE_VERSION, "lib"
        )

    # Enable override via environment variable
    path = os.getenv("RAGDOLL_CORE_PATH", path)

    return prefix, path, suffix


# Expose .pyd extension
prefix, path, suffix = get_install_dir()

# Enable the user to report where Core was attempted
print("Looking for Ragdoll Core @ '%s'" % path)
dll = os.path.join(path, "%sragdollcore.%s" % (prefix, suffix))

if bpy.app.version < (3, 4, 0):
    """Handle incompatible Blender version

    We only support Blender 3.4 and above

    """

    def register():
        from . import placeholder
        placeholder.install("old_version", "Requires Blender 3.4 or above",)

    def unregister():
        from . import placeholder
        placeholder.uninstall("old_version")


elif PLATFORM_NAME == "darwin" and bpy.app.version >= (3, 5, 0):
    """Handle unsupported Metal renderer

    On MacOS, Blender 3.5+ does not use OpenGL, but we do.

    """

    def register():
        from . import placeholder
        placeholder.install("metal", "On MacOS, Blender 3.4 is required",)

    def unregister():
        from . import placeholder
        placeholder.uninstall("metal")

elif not os.path.exists(dll):
    """Handle missing Ragdoll Core

    The user will need Ragdoll Core installed in
    order to use this Blender Addon

    """

    if PLATFORM_NAME in ("linux", "windows"):
        def download_page(*args):
            url = "https://learn.ragdolldynamics.com/download"

            # Help those looking at the terminal
            print("Go to %s" % url)

            # Help those looking at their UI with a browser available
            import webbrowser
            webbrowser.open_new(url)

        def register():
            from . import placeholder
            placeholder.install(
                "missing_core",
                "Download Ragdoll Core %s" % CORE_VERSION,
                download_page
            )

        def unregister():
            from . import placeholder
            placeholder.uninstall("missing_core")

    else:
        def register():
            from . import placeholder
            placeholder.install("macos", "Coming soon for MacOS")

        def unregister():
            from . import placeholder
            placeholder.uninstall("macos")

else:
    """Handle the supported case

    All is well, let's go!

    """

    def register():
        # Expose ragdollcore.pyd
        sys.path.insert(0, path)

        from . import main
        main.install()

    def unregister():
        from . import main
        main.uninstall()

        # Ensure ragdollc is uninstalled, for release of lease
        if RAGDOLL_FLOATING:
            import ragdollc
            if ragdollc.installed():
                ragdollc.licence.dropLease()
