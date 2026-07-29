# Export Hub — per-project FBX export presets for Blender.
# Copyright (C) 2026 Malik3D
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see <https://www.gnu.org/licenses/>.

bl_info = {
    "name": "Export Hub",
    "author": "Malik3D",
    "version": (1, 8, 0),
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

from . import properties, operators, ui, updates, validate

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
    bpy.types.TOPBAR_MT_file_export.append(ui.menu_func_export)
    bpy.app.timers.register(_startup_update_check, first_interval=5.0)


def unregister():
    # Timers and menu entries outlive class registration, so they go first —
    # otherwise disabling the add-on leaves a callback or a menu item pointing
    # at code that no longer exists.
    if bpy.app.timers.is_registered(_startup_update_check):
        bpy.app.timers.unregister(_startup_update_check)
    updates.unregister_timers()
    bpy.types.TOPBAR_MT_file_export.remove(ui.menu_func_export)
    # Module state, so it outlives the add-on without this. It still survives
    # File > Open — a result from another .blend can be on screen until the user
    # validates again, which the panel's label at least makes visible.
    validate.clear_result()

    for mod in reversed(_modules):
        for cls in reversed(mod.classes):
            bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
