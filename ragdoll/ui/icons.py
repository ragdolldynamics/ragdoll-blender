import os
import sys
import bpy.utils.previews  # noqa

fname_to_icon_id = {}

# Keep persistent reference to icon ids
_collection = None


def install():
    dirname = os.path.dirname(os.path.dirname(__file__))  # ragdoll
    dirname = os.path.join(dirname, "resources", "icons")

    icons = [
        "logo.png",
        "logo2.png",
        "record.png",
        "snap.png",
        "ctrl-mac.png",
        "ctrl.png",
    ]

    global _collection
    _collection = bpy.utils.previews.new()  # Note: a subclass of dict

    for fname in icons:
        path = os.path.join(dirname, fname)
        _collection.load(fname, path, "IMAGE")

        # Note: Accessing the 0-th index somehow improves quality
        _collection[fname].icon_size[0]

        fname_to_icon_id[fname] = _collection[fname].icon_id


def uninstall():
    try:
        bpy.utils.previews.remove(fname_to_icon_id)
    except AttributeError:
        pass

    fname_to_icon_id.clear()


def ls() -> list[str]:
    """Returns a list of loaded icon names"""
    return sorted(fname_to_icon_id.keys())


def fname_to_icon_path(fname: str) -> str:
    dirname = os.path.dirname(os.path.dirname(__file__))  # ragdoll
    dirname = os.path.join(dirname, "resources", "icons")
    return os.path.join(dirname, fname)
