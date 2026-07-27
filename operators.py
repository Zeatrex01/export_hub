"""Operators: manage projects & presets, JSON import/export, and run exports."""

import os
import json
import datetime
import contextlib

import bpy
from bpy.props import StringProperty, EnumProperty, IntProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

from . import config, templates, updates, validate
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


_COPY_MARKER = "_export_hub_source_index"


@contextlib.contextmanager
def _transformed_copies(context, originals):
    """Yield {original: copy}, where each copy has its transforms applied.

    Applying transforms to the real objects is destructive and the add-on cannot
    put them back — the user asked for an export, not a permanent edit of their
    scene. So the baking happens on duplicates that live only for the duration of
    the export and are removed on the way out, including when it fails.

    The set is duplicated in a single operation on purpose: duplicating object by
    object would sever parenting and armature-modifier links between them, while
    one duplicate call rewires those relationships inside the new set.
    """
    previous_active = context.view_layer.objects.active

    # Duplicates inherit custom properties, and that is the only dependable way
    # to tell which copy came from which original: duplicate() returns no
    # mapping, and the generated names are not something to parse.
    for index, obj in enumerate(originals):
        obj[_COPY_MARKER] = index

    mapping = {}
    try:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in originals:
            obj.select_set(True)
        context.view_layer.objects.active = originals[0]

        bpy.ops.object.duplicate(linked=False)

        for copy in list(context.selected_objects):
            index = copy.get(_COPY_MARKER)
            if index is None:
                continue
            del copy[_COPY_MARKER]
            mapping[originals[index]] = copy

        # transform_apply refuses on data shared with anything else.
        try:
            bpy.ops.object.make_single_user(object=True, obdata=True)
        except RuntimeError:
            pass

        # Rotation and scale only — never location. Applying location moves the
        # object's origin to the world origin and bakes the offset into the
        # vertices. It looks identical in Blender, but the engine then has a
        # mesh whose pivot sits at zero with its geometry somewhere else, so the
        # prop rotates around a point it is nowhere near. The pivot is the
        # artist's decision; this only cleans up what the engine cares about.
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

        yield mapping
    finally:
        for obj in originals:
            if _COPY_MARKER in obj:
                del obj[_COPY_MARKER]
        for copy in mapping.values():
            try:
                bpy.data.objects.remove(copy, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        bpy.ops.object.select_all(action='DESELECT')
        for obj in originals:
            try:
                obj.select_set(True)
            except (ReferenceError, RuntimeError):
                pass
        context.view_layer.objects.active = previous_active


def _export_plan(context, mapping):
    """[(object_to_export, name_to_use_in_filenames), ...].

    With copies in play the object written to the FBX is a throwaway duplicate,
    but the filename must still come from the original — nobody wants
    `Chair.001.fbx`.
    """
    if mapping is None:
        return [(obj, obj.name) for obj in context.selected_objects]
    return [(copy, original.name) for original, copy in mapping.items()]


def _resolve_target(context, project, preset, object_name=None, export_dir_override=None):
    """Resolve a preset's absolute output path.

    Returns (export_dir, filepath, error). Both the export and the Export All
    collision check go through here, so the path that gets checked is by
    construction the same one that gets written.

    export_dir_override redirects a single export without touching the preset's
    saved folder — the export dialog uses it for one-off destinations.
    """
    source_dir = export_dir_override or preset.export_dir
    if source_dir.startswith("//") and not bpy.data.filepath:
        # "//" is relative to the .blend. With no .blend saved, Blender resolves
        # it against the process working directory, which is wherever Blender
        # happened to be launched from — files would land somewhere the user
        # never chose.
        return None, None, "save the .blend first, or set an absolute export folder"

    export_dir = bpy.path.abspath(source_dir)
    if not export_dir:
        return None, None, "no export folder set"

    filename = config.resolve_filename(
        preset.filename_template, context, project, preset, object_name=object_name) + ".fbx"
    return export_dir, os.path.join(export_dir, filename), None


def _apply_overwrite_mode(filepath, mode):
    """Apply a preset's "the file already exists" policy to a resolved path.

    Returns (filepath, reason). filepath is None when nothing should be written,
    and reason then says why, so the caller can report a skip instead of
    counting the preset as exported.
    """
    if mode == 'OVERWRITE' or not os.path.exists(filepath):
        return filepath, None

    name = os.path.basename(filepath)
    if mode == 'SKIP':
        return None, "%s already exists" % name

    base, ext = os.path.splitext(filepath)
    for number in range(1, 1000):
        candidate = "%s_%03d%s" % (base, number, ext)
        if not os.path.exists(candidate):
            return candidate, None
    # Every numbered name is taken. Refusing beats overwriting a file the user
    # explicitly asked to keep.
    return None, "%s already has 999 numbered copies" % name


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


def _export_single(context, project, preset, kwargs, plan, export_dir_override=None):
    """Export the whole export set to one file. Returns (status, message, folder)."""
    active = context.view_layer.objects.active
    display = next((name for obj, name in plan if obj is active), None)
    if display is None and plan:
        display = plan[0][1]

    export_dir, filepath, error = _resolve_target(
        context, project, preset, object_name=display, export_dir_override=export_dir_override)
    if error:
        return 'FAILED', error, None

    filepath, reason = _apply_overwrite_mode(filepath, preset.overwrite_mode)
    if filepath is None:
        return 'SKIPPED', reason, None

    ok, message = _export_fbx(context, filepath, kwargs)
    if not ok:
        return 'FAILED', message, None

    _record_history(context, project.name, preset.name, filepath, kwargs)
    return 'DONE', filepath, export_dir


def _export_per_object(context, project, preset, kwargs, plan, export_dir_override=None):
    """Export every object in the plan to its own file. Returns (status, message, folder).

    The selection is driven one object at a time and put back afterwards: the
    user pressed one button, they should get their scene back exactly as it was,
    including which object was active.
    """
    if "{object}" not in (preset.filename_template or ""):
        return 'FAILED', ("split export needs {object} in the filename template, "
                          "otherwise every object writes to the same file"), None

    was_selected = list(context.selected_objects)
    was_active = context.view_layer.objects.active

    written, skipped, failed, folder = [], [], [], None
    try:
        for obj, display in plan:
            bpy.ops.object.select_all(action='DESELECT')
            try:
                obj.select_set(True)
            except RuntimeError:
                # Hidden or excluded from the view layer; it cannot be exported
                # on its own, and skipping quietly would be a lie.
                failed.append("%s (not selectable in this view layer)" % display)
                continue
            context.view_layer.objects.active = obj

            export_dir, filepath, error = _resolve_target(
                context, project, preset, object_name=display,
                export_dir_override=export_dir_override)
            if error:
                return 'FAILED', error, None

            # Per object, not per preset: one object already on disk should not
            # stop the rest of the selection from being written.
            filepath, reason = _apply_overwrite_mode(filepath, preset.overwrite_mode)
            if filepath is None:
                skipped.append(reason)
                continue

            ok, message = _export_fbx(context, filepath, kwargs)
            if ok:
                written.append(filepath)
                folder = folder or export_dir
                _record_history(context, project.name, preset.name, filepath, kwargs)
            else:
                failed.append("%s (%s)" % (display, message))
    finally:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in was_selected:
            try:
                obj.select_set(True)
            except (ReferenceError, RuntimeError):
                pass
        context.view_layer.objects.active = was_active

    if not written:
        if skipped and not failed:
            return 'SKIPPED', "%d file(s) already exist, nothing written" % len(skipped), None
        return 'FAILED', "no object exported — %s" % "; ".join(failed + skipped), None

    detail = ""
    if skipped:
        detail += ", %d skipped (already exists)" % len(skipped)
    if failed:
        detail += ", %d failed: %s" % (len(failed), "; ".join(failed))
    return 'DONE', "%d file(s) in %s%s" % (len(written), folder, detail), folder


def _first_collision(context, project, presets, export_dir_override=None):
    """Return an error string if two presets would write to the same file.

    Shared by Export All and the export dialog so both refuse on the same
    grounds — two presets landing on one path means one export is silently lost.
    """
    seen = {}
    for preset in presets:
        _, filepath, error = _resolve_target(
            context, project, preset, export_dir_override=export_dir_override)
        if error:
            continue  # reported per preset when the export runs
        key = os.path.normcase(filepath)
        if key in seen:
            return ("'%s' and '%s' both export to %s — add {preset} to the filename template"
                    % (seen[key], preset.name, os.path.basename(filepath)))
        seen[key] = preset.name
    return None


def _run_export(context, project, preset, export_dir_override=None):
    """Perform a preset's export, split or combined.

    Returns (status, message) where status is 'DONE', 'SKIPPED' (the file was
    already on disk and the preset asked to keep it) or 'FAILED'. A skip is
    deliberately not a success: counting it as one would report an export the
    user never got.
    """
    fbx = preset.fbx_settings
    if fbx.use_selection and not context.selected_objects:
        return 'FAILED', "%s: nothing selected" % preset.name

    kwargs = {key: getattr(fbx, key) for key in FBX_SETTING_KEYS}

    # Baking transforms means copying the export set, so it needs a selection to
    # copy. With "visible" or "active collection" there is no such set.
    on_copies = (preset.apply_transform_before_export
                 and fbx.use_selection
                 and bool(context.selected_objects))

    def _export(mapping):
        plan = _export_plan(context, mapping)
        # Splitting only means anything when the export set is the selection.
        if preset.split_per_object and fbx.use_selection:
            return _export_per_object(
                context, project, preset, kwargs, plan, export_dir_override)
        return _export_single(context, project, preset, kwargs, plan, export_dir_override)

    try:
        if on_copies:
            with _transformed_copies(context, list(context.selected_objects)) as mapping:
                status, message, folder = _export(mapping)
        else:
            status, message, folder = _export(None)
    except RuntimeError as exc:
        # Duplication or transform_apply refused — object mode only, and it
        # baulks at library data. Reporting beats exporting something the user
        # believes was transformed and was not.
        return 'FAILED', "%s: could not apply transforms (%s)" % (preset.name, exc)

    if status != 'DONE':
        # Nothing was written, so nothing downstream should run: no version
        # bump for an export that did not happen, and no folder to open.
        return status, "%s: %s" % (preset.name, message)

    if preset.auto_increment_version:
        preset.version += 1
    if preset.open_folder_after_export and folder:
        try:
            bpy.ops.wm.path_open(filepath=folder)
        except RuntimeError:
            pass
    # An export is the natural checkpoint: it is also the point at which the
    # version counter and the history list have just changed.
    save_preferences()
    return 'DONE', message


def _run_presets(context, project, presets, export_dir_override=None):
    """Run several presets in order. Returns (done, skipped, failed_messages)."""
    done, skipped, failed = 0, 0, []
    for preset in presets:
        status, message = _run_export(context, project, preset, export_dir_override)
        if status == 'DONE':
            done += 1
        elif status == 'SKIPPED':
            skipped += 1
        else:
            failed.append(message)
    return done, skipped, failed


def _report_run(operator, project, done, skipped, failed):
    """Report a multi-preset run, naming everything that did not get written."""
    summary = "%d exported" % done
    if skipped:
        summary += ", %d skipped (file exists)" % skipped
    if failed:
        operator.report({'WARNING'}, "%s, %d failed: %s"
                        % (summary, len(failed), "; ".join(failed)))
    else:
        level = {'INFO'} if done else {'WARNING'}
        operator.report(level, "%s from '%s'" % (summary, project.name))


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


class EXH_OT_validate(bpy.types.Operator):
    bl_idname = "export_hub.validate"
    bl_label = "Validate"
    bl_description = ("Check the current selection against the active preset before "
                      "exporting: unapplied transforms, missing UVs, rig orientation "
                      "and animation range")

    @classmethod
    def poll(cls, context):
        prefs, project, preset = _active_preset(context)
        return preset is not None

    def execute(self, context):
        prefs, project, preset = _active_preset(context)
        if preset is None:
            self.report({'ERROR'}, "No preset selected")
            return {'CANCELLED'}

        checks = validate.run(context, project, preset)
        validate.store_result(preset.name, checks)
        errors, warnings, passed = validate.summarise(checks)

        if errors:
            self.report({'ERROR'}, "%d problem(s), %d warning(s), %d check(s) passed"
                        % (errors, warnings, passed))
        elif warnings:
            self.report({'WARNING'}, "%d warning(s), %d check(s) passed" % (warnings, passed))
        else:
            self.report({'INFO'}, "All %d check(s) passed for '%s'" % (passed, preset.name))
        return {'FINISHED'}


class EXH_OT_clear_validation(bpy.types.Operator):
    bl_idname = "export_hub.clear_validation"
    bl_label = "Dismiss"
    bl_description = "Hide the validation results"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        validate.clear_result()
        return {'FINISHED'}


class EXH_OT_check_updates(bpy.types.Operator):
    bl_idname = "export_hub.check_updates"
    bl_label = "Check for Updates"
    bl_description = "Ask GitHub whether a newer release of this add-on is available"

    def execute(self, context):
        prefs = config.get_prefs(context)
        if prefs is not None:
            prefs.last_update_check = datetime.date.today().isoformat()
            save_preferences()
        if not updates.start_check():
            self.report({'INFO'}, "Already checking")
            return {'CANCELLED'}
        self.report({'INFO'}, "Checking for updates...")
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
        status, message = _run_export(context, project, preset)
        if status == 'FAILED':
            self.report({'ERROR'}, "Failed: " + message)
            return {'CANCELLED'}
        # A skip is the preset doing what it was told, not an error — but it is
        # a warning, because the user pressed Export and got no new file.
        self.report({'WARNING'} if status == 'SKIPPED' else {'INFO'}, message)
        return {'FINISHED'}


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


# Dynamic enum items keep module-side references for the same reason the project
# dropdown does: Blender holds pointers to the strings a callback hands back.
_dialog_project_cache = ()
_dialog_preset_cache = ()


def _dialog_project_items(self, context):
    global _dialog_project_cache
    prefs = config.get_prefs(context)
    items = [(str(i), p.name or "Project %d" % i, "")
             for i, p in enumerate(prefs.projects)] if prefs else []
    _dialog_project_cache = tuple(items) or (("-1", "(no projects)", ""),)
    return _dialog_project_cache


def _dialog_preset_items(self, context):
    global _dialog_preset_cache
    prefs = config.get_prefs(context)
    items = []
    if prefs and self.project not in ("", "-1"):
        index = int(self.project)
        if 0 <= index < len(prefs.projects):
            items = [(str(i), p.name or "Preset %d" % i, "")
                     for i, p in enumerate(prefs.projects[index].presets)]
    _dialog_preset_cache = tuple(items) or (("-1", "(no presets)", ""),)
    return _dialog_preset_cache


class EXH_OT_export_dialog(bpy.types.Operator):
    """File > Export entry: pick a destination and run it, without leaving for the sidebar."""

    bl_idname = "export_hub.export_dialog"
    bl_label = "Export Hub"
    bl_description = "Export with a saved Export Hub project and preset"

    project: EnumProperty(name="Project", items=_dialog_project_items)
    preset: EnumProperty(name="Preset", items=_dialog_preset_items)
    mode: EnumProperty(
        name="Run",
        items=[
            ('ACTIVE', "This preset", "Export using the selected preset only"),
            ('ALL', "All enabled presets", "Run every enabled preset in this project"),
        ],
        default='ACTIVE',
    )
    use_custom_dir: BoolProperty(
        name="Override folder",
        default=False,
        description=("Write this export somewhere else, just this once. The preset keeps "
                     "its saved folder"),
    )
    custom_dir: StringProperty(name="Folder", subtype='DIR_PATH', default="")

    def _selection(self, context):
        """(prefs, project, preset) for the current dialog choices."""
        prefs = config.get_prefs(context)
        if prefs is None or self.project in ("", "-1"):
            return prefs, None, None
        index = int(self.project)
        if not (0 <= index < len(prefs.projects)):
            return prefs, None, None
        project = prefs.projects[index]
        if self.preset in ("", "-1"):
            return prefs, project, None
        pidx = int(self.preset)
        if not (0 <= pidx < len(project.presets)):
            return prefs, project, None
        return prefs, project, project.presets[pidx]

    def invoke(self, context, event):
        prefs = config.get_prefs(context)
        if prefs is None or not len(prefs.projects):
            self.report({'ERROR'}, "No projects configured — set one up in Preferences")
            return {'CANCELLED'}

        # Open on whatever the sidebar is showing, so the two never disagree.
        self.project = str(min(max(prefs.active_project_index, 0), len(prefs.projects) - 1))
        project = prefs.projects[int(self.project)]
        if len(project.presets):
            try:
                self.preset = str(
                    min(max(project.active_preset_index, 0), len(project.presets) - 1))
            except TypeError:
                pass
        return context.window_manager.invoke_props_dialog(self, width=440)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True

        layout.prop(self, "project")
        layout.prop(self, "mode")
        if self.mode == 'ACTIVE':
            layout.prop(self, "preset")

        layout.prop(self, "use_custom_dir")
        row = layout.row()
        row.enabled = self.use_custom_dir
        row.prop(self, "custom_dir")

        prefs, project, preset = self._selection(context)
        box = layout.box()
        if project is None:
            box.label(text="Pick a project", icon='ERROR')
            return

        if self.mode == 'ALL':
            enabled = [p for p in project.presets if p.enabled]
            box.label(text="%d enabled preset(s) in '%s'" % (len(enabled), project.name),
                      icon='PACKAGE')
            for p in enabled[:6]:
                box.label(text=p.name, icon='DOT')
            return

        if preset is None:
            box.label(text="This project has no presets", icon='ERROR')
            return

        folder = self.custom_dir if self.use_custom_dir else preset.export_dir
        box.label(text=folder or "(no folder set)", icon='FILE_FOLDER')
        name = config.resolve_filename(
            preset.filename_template, context, project, preset) + ".fbx"
        box.label(text="→ " + name, icon='FILE_TICK')
        if preset.split_per_object and preset.fbx_settings.use_selection:
            box.label(text="one file per selected object", icon='DUPLICATE')

    def execute(self, context):
        prefs, project, preset = self._selection(context)
        if project is None:
            self.report({'ERROR'}, "No project selected")
            return {'CANCELLED'}

        override = None
        if self.use_custom_dir:
            override = self.custom_dir
            if not bpy.path.abspath(override or ""):
                self.report({'ERROR'}, "Override folder is empty")
                return {'CANCELLED'}

        if self.mode == 'ALL':
            enabled = [p for p in project.presets if p.enabled]
            if not enabled:
                self.report({'WARNING'}, "No enabled presets in '%s'" % project.name)
                return {'CANCELLED'}
            collision = _first_collision(context, project, enabled, override)
            if collision:
                self.report({'ERROR'}, collision)
                return {'CANCELLED'}

            done, skipped, failed = _run_presets(context, project, enabled, override)
            _report_run(self, project, done, skipped, failed)
            return {'FINISHED'}

        if preset is None:
            self.report({'ERROR'}, "No preset selected")
            return {'CANCELLED'}
        status, message = _run_export(context, project, preset, override)
        if status == 'FAILED':
            self.report({'ERROR'}, "Failed: " + message)
            return {'CANCELLED'}
        self.report({'WARNING'} if status == 'SKIPPED' else {'INFO'}, message)
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
        collision = _first_collision(context, project, enabled)
        if collision:
            self.report({'ERROR'}, collision)
            return {'CANCELLED'}

        done, skipped, failed = _run_presets(context, project, enabled)
        _report_run(self, project, done, skipped, failed)
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
    EXH_OT_validate,
    EXH_OT_clear_validation,
    EXH_OT_check_updates,
    EXH_OT_save_settings,
    EXH_OT_apply_template,
    EXH_OT_add_project_from_template,
    EXH_OT_export_presets,
    EXH_OT_import_presets,
    EXH_OT_open_export_folder,
    EXH_OT_export,
    EXH_OT_export_dialog,
    EXH_OT_export_all,
    EXH_OT_history_reexport,
    EXH_OT_history_open,
    EXH_OT_history_remove,
    EXH_OT_history_clear,
)
