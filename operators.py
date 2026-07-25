"""Operators: manage projects & presets, JSON import/export, and run exports."""

import os
import json
import datetime

import bpy
from bpy.props import StringProperty, EnumProperty, IntProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

from . import config, templates
from .properties import FBX_SETTING_KEYS, save_preferences


def _active_project(context):
    prefs = config.get_prefs(context)
    if prefs is None:
        return None, None
    idx = prefs.active_project_index
    if 0 <= idx < len(prefs.projects):
        return prefs, prefs.projects[idx]
    return prefs, None


def _active_preset(context):
    prefs, project = _active_project(context)
    if project is None:
        return prefs, None, None
    idx = project.active_preset_index
    if 0 <= idx < len(project.presets):
        return prefs, project, project.presets[idx]
    return prefs, project, None


def _record_history(context, project_name, preset_name, filepath, kwargs):
    """Prepend an export to the history list, newest first, capped to MAX_HISTORY."""
    prefs = config.get_prefs(context)
    if prefs is None:
        return
    entry = prefs.history.add()
    entry.name = os.path.basename(filepath)
    entry.filepath = filepath
    entry.project_name = project_name
    entry.preset_name = preset_name
    entry.timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry.fbx_json = config.fbx_kwargs_to_json(kwargs)
    prefs.history.move(len(prefs.history) - 1, 0)
    while len(prefs.history) > config.MAX_HISTORY:
        prefs.history.remove(len(prefs.history) - 1)
    prefs.active_history_index = 0


def _resolve_target(context, project, preset):
    """Resolve a preset's absolute output path.

    Returns (export_dir, filepath, error). Both the export and the Export All
    collision check go through here, so the path that gets checked is by
    construction the same one that gets written.
    """
    if preset.export_dir.startswith("//") and not bpy.data.filepath:
        # "//" is relative to the .blend. With no .blend saved, Blender resolves
        # it against the process working directory, which is wherever Blender
        # happened to be launched from — files would land somewhere the user
        # never chose.
        return None, None, "save the .blend first, or set an absolute export folder"

    export_dir = bpy.path.abspath(preset.export_dir)
    if not export_dir:
        return None, None, "no export folder set"

    filename = config.resolve_filename(preset.filename_template, context, project, preset) + ".fbx"
    return export_dir, os.path.join(export_dir, filename), None


def _supported_fbx_kwargs(kwargs):
    """Drop arguments this Blender's FBX exporter does not accept.

    Blender adds and retires exporter options between versions. Passing one it
    does not know raises TypeError and kills the export outright, so the call is
    filtered against the operator's real signature rather than against an
    assumption about which Blender is running.
    """
    try:
        known = set(bpy.ops.export_scene.fbx.get_rna_type().properties.keys())
    except (AttributeError, RuntimeError):
        return kwargs  # cannot introspect; pass through and let the call decide

    supported = {key: val for key, val in kwargs.items() if key in known}
    dropped = sorted(set(kwargs) - set(supported))
    if dropped:
        # Not fatal, but the user configured these and they are not being
        # applied — say so on the console rather than pretending otherwise.
        print("[Export Hub] this Blender does not support: %s" % ", ".join(dropped))
    return supported


def _export_fbx(context, filepath, kwargs):
    """Run the FBX exporter to filepath. Returns (success, message)."""
    # Guard before touching the filesystem, so an aborted export does not leave
    # an empty folder behind.
    if kwargs.get("use_selection") and not context.selected_objects:
        return False, "nothing selected"
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
    except OSError as exc:
        return False, "could not create folder (%s)" % exc
    try:
        bpy.ops.export_scene.fbx(
            filepath=filepath, check_existing=False, **_supported_fbx_kwargs(kwargs)
        )
    except Exception as exc:
        return False, "export failed (%s)" % exc
    return True, filepath


def _run_export(context, project, preset):
    """Perform one FBX export from a preset. Returns (success: bool, message: str)."""
    export_dir, filepath, error = _resolve_target(context, project, preset)
    if error:
        return False, "%s: %s" % (preset.name, error)

    fbx = preset.fbx_settings
    if fbx.use_selection and not context.selected_objects:
        return False, "%s: nothing selected" % preset.name

    if preset.apply_transform_before_export and context.selected_objects:
        try:
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        except RuntimeError:
            pass

    kwargs = {key: getattr(fbx, key) for key in FBX_SETTING_KEYS}
    ok, message = _export_fbx(context, filepath, kwargs)
    if not ok:
        return False, "%s: %s" % (preset.name, message)

    _record_history(context, project.name, preset.name, filepath, kwargs)

    if preset.auto_increment_version:
        preset.version += 1
    if preset.open_folder_after_export:
        try:
            bpy.ops.wm.path_open(filepath=export_dir)
        except RuntimeError:
            pass
    # An export is the natural checkpoint: it is also the point at which the
    # version counter and the history list have just changed.
    save_preferences()
    return True, filepath


# --------------------------------------------------------------------------- #
# Project management
# --------------------------------------------------------------------------- #

class EXH_OT_project_add(bpy.types.Operator):
    bl_idname = "export_hub.project_add"
    bl_label = "Add Project"
    bl_description = "Add a new project"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs = config.get_prefs(context)
        p = prefs.projects.add()
        p.name = "New Project"
        prefs.active_project_index = len(prefs.projects) - 1
        save_preferences()
        return {'FINISHED'}


class EXH_OT_project_remove(bpy.types.Operator):
    bl_idname = "export_hub.project_remove"
    bl_label = "Remove Project"
    bl_description = "Remove the selected project"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs = config.get_prefs(context)
        idx = prefs.active_project_index
        if 0 <= idx < len(prefs.projects):
            prefs.projects.remove(idx)
            prefs.active_project_index = max(0, idx - 1)
            save_preferences()
        return {'FINISHED'}


class EXH_OT_project_move(bpy.types.Operator):
    bl_idname = "export_hub.project_move"
    bl_label = "Move Project"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")])

    def execute(self, context):
        prefs = config.get_prefs(context)
        idx = prefs.active_project_index
        new_idx = idx + (-1 if self.direction == 'UP' else 1)
        if 0 <= new_idx < len(prefs.projects):
            prefs.projects.move(idx, new_idx)
            prefs.active_project_index = new_idx
            save_preferences()
        return {'FINISHED'}


class EXH_OT_project_duplicate(bpy.types.Operator):
    bl_idname = "export_hub.project_duplicate"
    bl_label = "Duplicate Project"
    bl_description = "Duplicate the selected project with all its presets"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs, project = _active_project(context)
        if project is None:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}
        data = config.project_to_dict(project)
        data["name"] = project.name + " Copy"
        config.dict_to_project(prefs.projects.add(), data)
        prefs.active_project_index = len(prefs.projects) - 1
        save_preferences()
        return {'FINISHED'}


# --------------------------------------------------------------------------- #
# Preset management (within the active project)
# --------------------------------------------------------------------------- #

class EXH_OT_preset_add(bpy.types.Operator):
    bl_idname = "export_hub.preset_add"
    bl_label = "Add Preset"
    bl_description = "Add an export preset to the active project"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs, project = _active_project(context)
        if project is None:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}
        preset = project.presets.add()
        preset.name = "New Preset"
        project.active_preset_index = len(project.presets) - 1
        save_preferences()
        return {'FINISHED'}


class EXH_OT_preset_remove(bpy.types.Operator):
    bl_idname = "export_hub.preset_remove"
    bl_label = "Remove Preset"
    bl_description = "Remove the selected preset"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs, project = _active_project(context)
        if project is None:
            return {'CANCELLED'}
        idx = project.active_preset_index
        if 0 <= idx < len(project.presets):
            project.presets.remove(idx)
            project.active_preset_index = max(0, idx - 1)
            save_preferences()
        return {'FINISHED'}


class EXH_OT_preset_move(bpy.types.Operator):
    bl_idname = "export_hub.preset_move"
    bl_label = "Move Preset"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")])

    def execute(self, context):
        prefs, project = _active_project(context)
        if project is None:
            return {'CANCELLED'}
        idx = project.active_preset_index
        new_idx = idx + (-1 if self.direction == 'UP' else 1)
        if 0 <= new_idx < len(project.presets):
            project.presets.move(idx, new_idx)
            project.active_preset_index = new_idx
            save_preferences()
        return {'FINISHED'}


class EXH_OT_preset_duplicate(bpy.types.Operator):
    bl_idname = "export_hub.preset_duplicate"
    bl_label = "Duplicate Preset"
    bl_description = "Duplicate the selected preset including all FBX settings"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs, project, preset = _active_preset(context)
        if preset is None:
            self.report({'ERROR'}, "No preset selected")
            return {'CANCELLED'}
        data = config._preset_to_dict(preset)
        data["name"] = preset.name + " Copy"
        config._dict_to_preset(project.presets.add(), data)
        project.active_preset_index = len(project.presets) - 1
        save_preferences()
        return {'FINISHED'}


class EXH_OT_insert_token(bpy.types.Operator):
    bl_idname = "export_hub.insert_token"
    bl_label = "Insert Token"
    bl_description = "Append this token to the active preset's filename"
    bl_options = {'INTERNAL', 'UNDO'}

    token: StringProperty()

    def execute(self, context):
        prefs, project, preset = _active_preset(context)
        if preset is None:
            return {'CANCELLED'}
        preset.filename_template = (preset.filename_template or "") + "{%s}" % self.token
        save_preferences()
        return {'FINISHED'}


class EXH_OT_save_settings(bpy.types.Operator):
    bl_idname = "export_hub.save_settings"
    bl_label = "Save Settings"
    bl_description = ("Write all projects, presets and history to disk now. Every button in "
                      "this add-on already saves; use this after typing into a field, which "
                      "Blender does not route through an operator")

    def execute(self, context):
        if not save_preferences():
            self.report({'ERROR'}, "Could not write preferences")
            return {'CANCELLED'}
        self.report({'INFO'}, "Settings saved")
        return {'FINISHED'}


class EXH_OT_apply_template(bpy.types.Operator):
    bl_idname = "export_hub.apply_template"
    bl_label = "Apply Engine Template"
    bl_description = "Overwrite the active preset's FBX settings with a built-in engine template"
    bl_options = {'REGISTER', 'UNDO'}

    template_id: EnumProperty(name="Template", items=templates.ENUM_ITEMS)

    def execute(self, context):
        prefs, project, preset = _active_preset(context)
        if preset is None:
            self.report({'ERROR'}, "No preset selected")
            return {'CANCELLED'}
        template = templates.get(self.template_id)
        if template is None:
            self.report({'ERROR'}, "Unknown template: %s" % self.template_id)
            return {'CANCELLED'}

        templates.apply_to(preset.fbx_settings, template)
        self.report(
            {'INFO'},
            "%s %s settings applied to '%s'" % (template.engine, template.variant, preset.name),
        )
        # Surface the template's caveat at the moment it becomes relevant,
        # rather than burying it in a tooltip nobody opens.
        if template.notes:
            self.report({'WARNING'}, template.notes)
        save_preferences()
        return {'FINISHED'}


class EXH_OT_add_project_from_template(bpy.types.Operator):
    bl_idname = "export_hub.add_project_from_template"
    bl_label = "New Project from Engine"
    bl_description = ("Create a project preconfigured for an engine, with one preset "
                      "per export type (static mesh, skeletal mesh, animation)")
    bl_options = {'REGISTER', 'UNDO'}

    engine: EnumProperty(name="Engine", items=templates.ENGINE_ENUM_ITEMS)

    def execute(self, context):
        prefs = config.get_prefs(context)
        if prefs is None:
            return {'CANCELLED'}
        entries = templates.for_engine(self.engine)
        if not entries:
            self.report({'ERROR'}, "Unknown engine: %s" % self.engine)
            return {'CANCELLED'}

        project = prefs.projects.add()
        project.name = self.engine
        for template in entries:
            preset = project.presets.add()
            preset.name = template.variant
            # Distinct filenames per preset, otherwise Export All would have
            # every preset in this project overwrite the same file.
            preset.filename_template = "{blend}_{preset}"
            templates.apply_to(preset.fbx_settings, template)

        project.active_preset_index = 0
        prefs.active_project_index = len(prefs.projects) - 1
        self.report(
            {'INFO'},
            "Created '%s' with %d preset(s). Set an export folder on each." % (
                project.name, len(entries)),
        )
        save_preferences()
        return {'FINISHED'}


# --------------------------------------------------------------------------- #
# Share config as JSON
# --------------------------------------------------------------------------- #

class EXH_OT_export_presets(bpy.types.Operator, ExportHelper):
    bl_idname = "export_hub.export_presets"
    bl_label = "Export Config to JSON"
    bl_description = "Save all projects and presets to a JSON file for sharing"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        prefs = config.get_prefs(context)
        data = config.projects_to_data(prefs)
        try:
            with open(self.filepath, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except OSError as exc:
            self.report({'ERROR'}, "Could not write file: %s" % exc)
            return {'CANCELLED'}
        self.report({'INFO'}, "Exported %d project(s)" % len(prefs.projects))
        return {'FINISHED'}


class EXH_OT_import_presets(bpy.types.Operator, ImportHelper):
    bl_idname = "export_hub.import_presets"
    bl_label = "Import Config from JSON"
    bl_description = "Load projects and presets from a JSON file"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})
    mode: EnumProperty(
        name="Mode",
        items=[
            ('REPLACE', "Replace all", "Clear current projects, then load"),
            ('APPEND', "Append", "Add loaded projects to the current list"),
        ],
        default='APPEND',
    )

    def draw(self, context):
        self.layout.prop(self, "mode")

    def execute(self, context):
        prefs = config.get_prefs(context)
        try:
            with open(self.filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            self.report({'ERROR'}, "Could not read file: %s" % exc)
            return {'CANCELLED'}
        count = config.data_to_projects(prefs, data, replace=(self.mode == 'REPLACE'))
        self.report({'INFO'}, "Imported %d project(s)" % count)
        save_preferences()
        return {'FINISHED'}


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #

class EXH_OT_open_export_folder(bpy.types.Operator):
    bl_idname = "export_hub.open_export_folder"
    bl_label = "Open Export Folder"
    bl_description = "Open the active preset's export folder"

    def execute(self, context):
        prefs, project, preset = _active_preset(context)
        if preset is None:
            self.report({'ERROR'}, "No preset selected")
            return {'CANCELLED'}
        folder = bpy.path.abspath(preset.export_dir)
        if not os.path.isdir(folder):
            self.report({'ERROR'}, "Folder does not exist: %s" % folder)
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=folder)
        return {'FINISHED'}


class EXH_OT_export(bpy.types.Operator):
    bl_idname = "export_hub.export"
    bl_label = "Export"
    bl_description = "Export using the active preset's saved FBX settings"

    @classmethod
    def poll(cls, context):
        prefs, project, preset = _active_preset(context)
        return preset is not None and bool(preset.export_dir)

    def execute(self, context):
        prefs, project, preset = _active_preset(context)
        if preset is None:
            self.report({'ERROR'}, "No preset selected")
            return {'CANCELLED'}
        ok, message = _run_export(context, project, preset)
        self.report({'INFO'} if ok else {'ERROR'}, message if ok else "Failed: " + message)
        return {'FINISHED'} if ok else {'CANCELLED'}


class EXH_OT_history_reexport(bpy.types.Operator):
    bl_idname = "export_hub.history_reexport"
    bl_label = "Re-export"
    bl_description = "Export the current selection again to this entry's path with its saved settings"

    index: IntProperty(default=-1)

    def execute(self, context):
        prefs = config.get_prefs(context)
        idx = self.index if self.index >= 0 else prefs.active_history_index
        if not (0 <= idx < len(prefs.history)):
            self.report({'ERROR'}, "No history entry selected")
            return {'CANCELLED'}
        entry = prefs.history[idx]
        kwargs = config.json_to_fbx_kwargs(entry.fbx_json)
        ok, message = _export_fbx(context, entry.filepath, kwargs)
        if not ok:
            self.report({'ERROR'}, "Re-export failed: " + message)
            return {'CANCELLED'}
        _record_history(context, entry.project_name, entry.preset_name, entry.filepath, kwargs)
        self.report({'INFO'}, "Re-exported: %s" % entry.filepath)
        save_preferences()
        return {'FINISHED'}


class EXH_OT_history_open(bpy.types.Operator):
    bl_idname = "export_hub.history_open"
    bl_label = "Open Containing Folder"
    bl_description = "Open the folder this file was exported to"

    index: IntProperty(default=-1)

    def execute(self, context):
        prefs = config.get_prefs(context)
        idx = self.index if self.index >= 0 else prefs.active_history_index
        if not (0 <= idx < len(prefs.history)):
            return {'CANCELLED'}
        folder = os.path.dirname(prefs.history[idx].filepath)
        if not os.path.isdir(folder):
            self.report({'ERROR'}, "Folder no longer exists")
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=folder)
        return {'FINISHED'}


class EXH_OT_history_remove(bpy.types.Operator):
    bl_idname = "export_hub.history_remove"
    bl_label = "Remove Entry"
    bl_description = "Remove this entry from the history"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)

    def execute(self, context):
        prefs = config.get_prefs(context)
        idx = self.index if self.index >= 0 else prefs.active_history_index
        if 0 <= idx < len(prefs.history):
            prefs.history.remove(idx)
            prefs.active_history_index = max(0, min(idx, len(prefs.history) - 1))
            save_preferences()
        return {'FINISHED'}


class EXH_OT_history_clear(bpy.types.Operator):
    bl_idname = "export_hub.history_clear"
    bl_label = "Clear History"
    bl_description = "Remove all export history entries"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs = config.get_prefs(context)
        prefs.history.clear()
        prefs.active_history_index = 0
        save_preferences()
        return {'FINISHED'}


class EXH_OT_export_all(bpy.types.Operator):
    bl_idname = "export_hub.export_all"
    bl_label = "Export All"
    bl_description = "Run every enabled preset in the active project"

    @classmethod
    def poll(cls, context):
        prefs, project = _active_project(context)
        return project is not None and len(project.presets) > 0

    def execute(self, context):
        prefs, project = _active_project(context)
        if project is None:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        enabled = [p for p in project.presets if p.enabled]
        if not enabled:
            self.report({'WARNING'}, "No enabled presets in '%s'" % project.name)
            return {'CANCELLED'}

        # Resolve every destination before writing anything. Two presets landing
        # on the same path would overwrite each other silently — the run would
        # report success and one export would simply be gone. Refusing up front
        # is the only outcome that does not lose work.
        targets = {}
        for preset in enabled:
            _, filepath, error = _resolve_target(context, project, preset)
            if error:
                continue  # _run_export reports this per preset
            key = os.path.normcase(filepath)
            if key in targets:
                self.report(
                    {'ERROR'},
                    "'%s' and '%s' both export to %s — add {preset} to the filename template"
                    % (targets[key], preset.name, os.path.basename(filepath)),
                )
                return {'CANCELLED'}
            targets[key] = preset.name

        done, failed = 0, []
        for preset in enabled:
            ok, message = _run_export(context, project, preset)
            if ok:
                done += 1
            else:
                failed.append(message)

        if failed:
            self.report({'WARNING'}, "%d exported, %d failed: %s" % (done, len(failed), "; ".join(failed)))
        else:
            self.report({'INFO'}, "Exported %d preset(s) from '%s'" % (done, project.name))
        return {'FINISHED'}


classes = (
    EXH_OT_project_add,
    EXH_OT_project_remove,
    EXH_OT_project_move,
    EXH_OT_project_duplicate,
    EXH_OT_preset_add,
    EXH_OT_preset_remove,
    EXH_OT_preset_move,
    EXH_OT_preset_duplicate,
    EXH_OT_insert_token,
    EXH_OT_save_settings,
    EXH_OT_apply_template,
    EXH_OT_add_project_from_template,
    EXH_OT_export_presets,
    EXH_OT_import_presets,
    EXH_OT_open_export_folder,
    EXH_OT_export,
    EXH_OT_export_all,
    EXH_OT_history_reexport,
    EXH_OT_history_open,
    EXH_OT_history_remove,
    EXH_OT_history_clear,
)
