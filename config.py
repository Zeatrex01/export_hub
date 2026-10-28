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

# Windows refuses these as filenames whatever extension follows ("CON.fbx", and
# "CON.v001.fbx" too: only the part before the first dot counts), so a template
# resolving to one of them cannot produce a file at all.
_RESERVED_NAMES = frozenset(
    ("CON", "PRN", "AUX", "NUL")
    + tuple("COM%s" % n for n in "123456789¹²³")
    + tuple("LPT%s" % n for n in "123456789¹²³")
)

# In UTF-8 bytes: Linux and macOS limit a name to 255 bytes, not characters, and
# a Turkish or Japanese name takes two or three bytes per letter. Leaves room for
# ".fbx" and for the "_001" that "Keep both" appends.
MAX_FILENAME = 200

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


# What setting a value from a JSON file can raise: a wrong type, an unknown enum
# item, a number too large (1e999 parses as infinity), text Blender cannot store.
_BAD_VALUE = (TypeError, ValueError, OverflowError)


def _text(value, default):
    """A JSON value as text Blender can store (a lone surrogate cannot be)."""
    if value is None:
        return default
    return str(value).encode("utf-8", "replace").decode("utf-8")


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
        except _BAD_VALUE:
            pass


def _preset_to_dict(preset):
    data = {key: getattr(preset, key) for key in PRESET_KEYS}
    data["enabled"] = preset.enabled
    data["fbx"] = _fbx_to_dict(preset.fbx_settings)
    return data


def _dict_to_preset(preset, data):
    for key in PRESET_KEYS:
        if key in data:
            value = data[key]
            if isinstance(value, str):
                value = _text(value, "")
            try:
                setattr(preset, key, value)
            except _BAD_VALUE:
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
    project.name = _text(data.get("name"), "Project")
    project.presets.clear()
    for entry in data.get("presets", []):
        _dict_to_preset(project.presets.add(), entry)
    if len(project.presets):
        try:
            wanted = int(data.get("active_preset_index", 0))
        except _BAD_VALUE:
            wanted = 0
        project.active_preset_index = max(0, min(wanted, len(project.presets) - 1))


def projects_to_data(prefs):
    return {
        "config_version": CONFIG_VERSION,
        "projects": [project_to_dict(p) for p in prefs.projects],
    }


def _checked_entries(data):
    """(project entries, is_legacy) of a parsed config, or ValueError saying what is wrong.

    Everything is checked before anything is loaded: Replace clears the user's
    projects first, so a file that fails half-way would leave them with nothing.
    """
    if not isinstance(data, dict):
        raise ValueError("not an Export Hub config (expected a JSON object)")
    version = data.get("config_version", CONFIG_VERSION)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("config_version must be a whole number")
    entries = data.get("projects")
    if not isinstance(entries, list) or not entries:
        raise ValueError("the file has no projects")
    for number, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError("project %d is not a JSON object" % number)
        presets = entry.get("presets", [])
        if not isinstance(presets, list) or not all(isinstance(p, dict) for p in presets):
            raise ValueError("project %d: presets must be a list of JSON objects" % number)
        for block in [entry] + presets:
            if not isinstance(block.get("fbx", {}), dict):
                raise ValueError("project %d: fbx settings must be a JSON object" % number)
    return entries, version < 2


def data_to_projects(prefs, data, replace=True):
    """Load projects from a parsed JSON dict. replace clears existing first.

    Also migrates v1 configs, where each entry was a flat project == single preset.
    Returns the number of projects loaded; raises ValueError, with nothing
    changed, when the file is not a usable config. That holds even for a failure
    part-way through loading: the projects as they were are kept as data first
    and put back.
    """
    entries, is_legacy = _checked_entries(data)
    before = projects_to_data(prefs)["projects"]
    active_before = prefs.active_project_index

    number = 0
    try:
        if replace:
            prefs.projects.clear()
        for number, entry in enumerate(entries, 1):
            project = prefs.projects.add()
            if is_legacy or "presets" not in entry:
                # v1: promote the flat project into a project with one preset.
                project.name = _text(entry.get("name"), "Project")
                preset = project.presets.add()
                _dict_to_preset(preset, {k: v for k, v in entry.items() if k != "name"})
                preset.name = "Default"
            else:
                dict_to_project(project, entry)
    except Exception as exc:  # anything at all: the user's projects come first
        prefs.projects.clear()
        for entry in before:
            dict_to_project(prefs.projects.add(), entry)
        prefs.active_project_index = active_before
        raise ValueError("project %d could not be loaded (%s)" % (number, exc))

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
    """Turn a resolved template into a name the filesystem will actually accept."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name).lstrip()
    # Cut by bytes, never inside a character.
    cleaned = cleaned.encode("utf-8")[:MAX_FILENAME].decode("utf-8", "ignore")

    # Trailing dots and spaces are trimmed in a loop rather than with one
    # strip().strip("."): "Chair. ." kept its trailing space that way, and Windows
    # silently drops trailing spaces and dots from a path — the file would land
    # under a name the add-on had already reported as something else.
    while cleaned and cleaned[-1] in " .":
        cleaned = cleaned[:-1]

    stem, dot, rest = cleaned.partition(".")
    device = stem.rstrip(" ")
    if device.upper() in _RESERVED_NAMES:
        cleaned = device + "_" + stem[len(device):] + dot + rest
    return cleaned or "export"


def resolve_filename(template, context, project, preset, object_name=None):
    """Expand tokens in a filename template into a safe, extension-less filename.

    object_name overrides the {object} token. Exports that run on temporary
    copies pass the original object's name, so files are named after what the
    user sees in the outliner rather than after a throwaway "Cube.001".
    """
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
        "object": object_name or (obj.name if obj else "object"),
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
