bl_info = {
    "name": "Export Hub",
    "author": "",
    "version": (1, 5, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar (N) > Export",
    "description": "One-click FBX export of the current selection to per-project folders, "
                   "each with its own saved FBX settings and filename template. "
                   "Presets are shareable via JSON import/export.",
    "category": "Import-Export",
}

import bpy

from . import properties, operators, ui

_modules = (properties, operators, ui)


def register():
    for mod in _modules:
        for cls in mod.classes:
            bpy.utils.register_class(cls)


def unregister():
    for mod in reversed(_modules):
        for cls in reversed(mod.classes):
            bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
