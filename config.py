"""Serialisation helpers and filename-template resolution.

Add-on preferences (projects, their presets and settings) are persisted
automatically by Blender in userpref.blend. The JSON functions here exist only
for explicit export/import so config can be shared between machines and teammates.
"""

import os
import re
import json
import datetime

import bpy

from .properties import FBX_SETTING_KEYS, PRESET_KEYS

CONFIG_VERSION = 2
MAX_HISTORY = 50
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# (token, human description) — single source of truth for the picker and docs.
FILENAME_TOKENS = [
    ("project", "Project name"),
    ("preset", "Preset name"),
    ("blend", ".blend file name"),
    ("object", "Active object name"),
    ("collection", "Active collection name"),
    ("scene", "Scene name"),
    ("date", "Date  YYYY-MM-DD"),
    ("time", "Time  HH-MM-SS"),
    ("version", "Version  v001"),
]


def get_prefs(context):
    """Return this add-on's preferences, or None if it is not registered."""
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _fbx_to_dict(fbx):
    out = {}
    for key in FBX_SETTING_KEYS:
        val = getattr(fbx, key)
        if isinstance(val, (set, frozenset)):
            val = sorted(val)
        out[key] = val
    return out


def _dict_to_fbx(fbx, data):
    for key, val in data.items():
        if not hasattr(fbx, key):
            continue  # tolerate settings from another add-on version
        try:
            current = getattr(fbx, key)
            if isinstance(current, set) and isinstance(val, list):
                setattr(fbx, key, set(val))
            else:
                setattr(fbx, key, val)
        except (TypeError, ValueError):
            pass


def _preset_to_dict(preset):
    data = {key: getattr(preset, key) for key in PRESET_KEYS}
    data["enabled"] = preset.enabled
    data["fbx"] = _fbx_to_dict(preset.fbx_settings)
    return data


def _dict_to_preset(preset, data):
    for key in PRESET_KEYS:
        if key in data:
            try:
                setattr(preset, key, data[key])
            except (TypeError, ValueError):
                pass
    preset.enabled = bool(data.get("enabled", True))
    _dict_to_fbx(preset.fbx_settings, data.get("fbx", {}))


def project_to_dict(project):
    return {
        "name": project.name,
        "active_preset_index": project.active_preset_index,
        "presets": [_preset_to_dict(p) for p in project.presets],
    }


def dict_to_project(project, data):
    project.name = data.get("name", "Project")
    project.presets.clear()
    for entry in data.get("presets", []):
        _dict_to_preset(project.presets.add(), entry)
    if len(project.presets):
        project.active_preset_index = min(
            int(data.get("active_preset_index", 0)), len(project.presets) - 1
        )


def projects_to_data(prefs):
    return {
        "config_version": CONFIG_VERSION,
        "projects": [project_to_dict(p) for p in prefs.projects],
    }


def data_to_projects(prefs, data, replace=True):
    """Load projects from a parsed JSON dict. replace clears existing first.

    Also migrates v1 configs, where each entry was a flat project == single preset.
    Returns the number of projects loaded.
    """
    entries = data.get("projects", []) if isinstance(data, dict) else []
    is_legacy = data.get("config_version", CONFIG_VERSION) < 2

    if replace:
        prefs.projects.clear()

    for entry in entries:
        project = prefs.projects.add()
        if is_legacy or "presets" not in entry:
            # v1: promote the flat project into a project with one preset.
            project.name = entry.get("name", "Project")
            preset = project.presets.add()
            preset.name = "Default"
            for key in PRESET_KEYS:
                if key in entry and key != "name":
                    try:
                        setattr(preset, key, entry[key])
                    except (TypeError, ValueError):
                        pass
            preset.name = "Default"
            _dict_to_fbx(preset.fbx_settings, entry.get("fbx", {}))
        else:
            dict_to_project(project, entry)

    if len(prefs.projects):
        prefs.active_project_index = min(prefs.active_project_index, len(prefs.projects) - 1)
    return len(entries)


def fbx_kwargs_to_json(kwargs):
    """Serialise a dict of export_scene.fbx kwargs to a JSON string (sets -> lists)."""
    safe = {k: (sorted(v) if isinstance(v, (set, frozenset)) else v) for k, v in kwargs.items()}
    return json.dumps(safe)


def json_to_fbx_kwargs(text):
    """Parse a stored kwargs snapshot back into export_scene.fbx kwargs.

    Only keys still known to this add-on version are kept; object_types -> set.
    """
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    out = {}
    for key in FBX_SETTING_KEYS:
        if key not in data:
            continue
        val = data[key]
        if key == "object_types" and isinstance(val, list):
            val = set(val)
        out[key] = val
    return out


def sanitize_filename(name):
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name).strip().strip(".")
    return cleaned or "export"


def resolve_filename(template, context, project, preset):
    """Expand tokens in a filename template into a safe, extension-less filename."""
    obj = context.active_object
    coll = context.collection
    scene = context.scene

    blend = ""
    if bpy.data.filepath:
        blend = os.path.splitext(os.path.basename(bpy.data.filepath))[0]

    now = datetime.datetime.now()
    tokens = {
        "project": project.name or "project",
        "preset": preset.name or "preset",
        "blend": blend or "untitled",
        "object": obj.name if obj else "object",
        "collection": coll.name if coll else "collection",
        "scene": scene.name if scene else "scene",
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H-%M-%S"),
        "version": "v%03d" % preset.version,
    }

    result = template or "{blend}"
    for key, value in tokens.items():
        result = result.replace("{%s}" % key, str(value))

    return sanitize_filename(result)
