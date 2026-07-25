bl_info = {
    "name": "Export Hub",
    "author": "Malik3D",
    "version": (1, 6, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar (N) > Export",
    "description": "One-click FBX export of the current selection to per-project folders, "
                   "each with its own saved FBX settings and filename template. "
                   "Presets are shareable via JSON import/export.",
    "doc_url": "https://github.com/Zeatrex01/export_hub",
    "tracker_url": "https://github.com/Zeatrex01/export_hub/issues",
    "category": "Import-Export",
}

import datetime

import bpy

from . import properties, operators, ui, updates

_modules = (properties, operators, ui)


def _startup_update_check():
    """One-shot timer that runs shortly after the add-on is enabled.

    Not done inside register(): at that point Blender is still starting up and
    the add-on's own preferences are not reliably reachable yet. Returning None
    tells Blender not to schedule the timer again.
    """
    from . import config

    prefs = config.get_prefs(bpy.context)
    if prefs is not None and prefs.check_updates and updates.due_today(prefs):
        prefs.last_update_check = datetime.date.today().isoformat()
        updates.start_check()
    return None


def register():
    for mod in _modules:
        for cls in mod.classes:
            bpy.utils.register_class(cls)
    bpy.app.timers.register(_startup_update_check, first_interval=5.0)


def unregister():
    # Timers outlive class registration, so they have to go first or disabling
    # the add-on leaves a callback pointing at unregistered code.
    if bpy.app.timers.is_registered(_startup_update_check):
        bpy.app.timers.unregister(_startup_update_check)
    updates.unregister_timers()

    for mod in reversed(_modules):
        for cls in reversed(mod.classes):
            bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
