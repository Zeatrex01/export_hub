"""UI: the N-panel export widget, the project/preset lists, and preferences."""

import bpy

from . import config, templates, updates, validate

_CHECK_ICONS = {
    'ERROR': 'CANCEL',
    'WARNING': 'ERROR',        # Blender's exclamation-mark triangle
    'INFO': 'INFO',
    'OK': 'CHECKMARK',
}


def _draw_validation(layout, prefs):
    """Show the last validation run — what passed as well as what did not.

    Nothing is drawn until the user asks for a run.
    """
    result = validate.last_result()
    if not result["ran"]:
        return

    checks = validate.sort_for_display(result["checks"])
    errors, warnings, passed = validate.summarise(checks)

    box = layout.box()
    header = box.row(align=True)
    if errors:
        header.alert = True
        header.label(text="%d problem(s), %d warning(s), %d passed"
                          % (errors, warnings, passed), icon='CANCEL')
    elif warnings:
        header.label(text="%d warning(s), %d passed" % (warnings, passed), icon='ERROR')
    else:
        header.label(text="All %d check(s) passed" % passed, icon='CHECKMARK')
    header.prop(prefs, "show_passed_checks", text="",
                icon='HIDE_OFF' if prefs.show_passed_checks else 'HIDE_ON')
    header.operator("export_hub.clear_validation", text="", icon='X', emboss=False)

    hidden = 0
    column = box.column(align=True)
    for check in checks:
        if check.level == 'OK' and not prefs.show_passed_checks:
            hidden += 1
            continue
        row = column.row()
        row.alert = check.level == 'ERROR'
        row.label(text=check.message, icon=_CHECK_ICONS.get(check.level, 'INFO'))

    if hidden:
        column.label(text="%d passed check(s) hidden" % hidden, icon='BLANK1')


def _draw_update_banner(layout):
    """A single line in the sidebar when a newer release exists. Silent otherwise."""
    info = updates.state()
    if info["status"] != "available":
        return
    box = layout.box()
    row = box.row()
    row.alert = True
    row.label(
        text="Version %s available" % updates.format_version(info["latest"]),
        icon='INFO',
    )
    box.operator("wm.url_open", text="Download", icon='URL').url = updates.RELEASES_PAGE


def _draw_update_row(layout, prefs):
    """Update controls and the last check's outcome, shown in Preferences."""
    box = layout.box()
    row = box.row(align=True)
    row.prop(prefs, "check_updates")
    row.operator("export_hub.check_updates", text="Check Now", icon='FILE_REFRESH')

    info = updates.state()
    status = info["status"]
    installed = updates.format_version(updates.current_version())

    if status == "checking":
        box.label(text="Checking...", icon='SORTTIME')
    elif status == "available":
        row = box.row()
        row.alert = True
        row.label(
            text="Version %s available — installed %s"
                 % (updates.format_version(info["latest"]), installed),
            icon='INFO',
        )
        box.operator(
            "wm.url_open", text="Open releases page", icon='URL'
        ).url = updates.RELEASES_PAGE
    elif status == "current":
        box.label(text="Up to date (%s)" % installed, icon='CHECKMARK')
    elif status == "none":
        box.label(text=info["message"], icon='INFO')
    elif status == "error":
        box.label(text="Update check failed: %s" % info["message"], icon='ERROR')


class EXH_MT_templates(bpy.types.Menu):
    """Built-in engine templates, grouped by engine, applied to the active preset."""

    bl_label = "Engine Template"
    bl_idname = "EXH_MT_templates"

    def draw(self, context):
        layout = self.layout
        for engine in templates.ENGINES:
            layout.label(text=engine)
            for template in templates.for_engine(engine):
                layout.operator(
                    "export_hub.apply_template",
                    text=template.variant,
                ).template_id = template.id
            layout.separator()


class EXH_MT_new_project(bpy.types.Menu):
    """Create a whole project preconfigured for one engine."""

    bl_label = "New Project from Engine"
    bl_idname = "EXH_MT_new_project"

    def draw(self, context):
        layout = self.layout
        layout.operator("export_hub.project_add", text="Empty Project", icon='ADD')
        layout.separator()
        for engine in templates.ENGINES:
            layout.operator(
                "export_hub.add_project_from_template",
                text=engine,
                icon='PRESET',
            ).engine = engine


class EXH_MT_tokens(bpy.types.Menu):
    """Dropdown that inserts a filename token at the end of the template."""

    bl_label = "Insert Token"
    bl_idname = "EXH_MT_tokens"

    def draw(self, context):
        layout = self.layout
        for token, desc in config.FILENAME_TOKENS:
            layout.operator(
                "export_hub.insert_token",
                text="{%s}   %s" % (token, desc),
            ).token = token


def _filename_row(layout, preset):
    """A filename field with a token-picker button beside it."""
    row = layout.row(align=True)
    row.prop(preset, "filename_template", text="", icon='FILE')
    row.menu("EXH_MT_tokens", text="", icon='DOWNARROW_HLT')


class EXH_UL_named(bpy.types.UIList):
    """Generic list drawing an item's editable .name. Used for projects & presets."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            if hasattr(item, "enabled"):
                row.prop(item, "enabled", text="")
            row.prop(item, "name", text="", emboss=False, icon='FILE_3D')
        else:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='FILE_3D')


class EXH_UL_history(bpy.types.UIList):
    """Read-only list of past exports: filename, project/preset, and time."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            split = layout.split(factor=0.55)
            split.label(text=item.name, icon='FILE_3D')
            sub = split.row()
            sub.label(text="%s / %s" % (item.project_name, item.preset_name))
            sub.label(text=item.timestamp)
        else:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='FILE_3D')


def _draw_fbx_settings(layout, fbx):
    box = layout.box()
    box.label(text="Include", icon='RESTRICT_SELECT_OFF')
    row = box.row(align=True)
    row.prop(fbx, "use_selection", toggle=True)
    row.prop(fbx, "use_visible", toggle=True)
    row.prop(fbx, "use_active_collection", toggle=True)
    box.prop(fbx, "object_types")
    box.prop(fbx, "use_custom_props")

    box = layout.box()
    box.label(text="Transform", icon='ORIENTATION_GLOBAL')
    box.prop(fbx, "global_scale")
    box.prop(fbx, "apply_scale_options")
    box.prop(fbx, "apply_unit_scale")
    row = box.row(align=True)
    row.prop(fbx, "axis_forward")
    row.prop(fbx, "axis_up")
    box.prop(fbx, "use_space_transform")
    box.prop(fbx, "bake_space_transform")

    box = layout.box()
    box.label(text="Geometry", icon='MESH_DATA')
    box.prop(fbx, "mesh_smooth_type")
    box.prop(fbx, "use_subsurf")
    box.prop(fbx, "use_mesh_modifiers")
    box.prop(fbx, "use_mesh_edges")
    box.prop(fbx, "use_tspace")
    box.prop(fbx, "use_triangles")
    box.prop(fbx, "colors_type")

    box = layout.box()
    box.label(text="Armature", icon='ARMATURE_DATA')
    row = box.row(align=True)
    row.prop(fbx, "primary_bone_axis")
    row.prop(fbx, "secondary_bone_axis")
    box.prop(fbx, "armature_nodetype")
    box.prop(fbx, "use_armature_deform_only")
    box.prop(fbx, "add_leaf_bones")

    box = layout.box()
    box.label(text="Animation", icon='ANIM')
    box.prop(fbx, "bake_anim")
    col = box.column()
    col.enabled = fbx.bake_anim
    col.prop(fbx, "bake_anim_use_all_bones")
    col.prop(fbx, "bake_anim_use_nla_strips")
    col.prop(fbx, "bake_anim_use_all_actions")
    col.prop(fbx, "bake_anim_force_startend_keying")
    col.prop(fbx, "bake_anim_step")
    col.prop(fbx, "bake_anim_simplify_factor")

    box = layout.box()
    box.label(text="Extras", icon='TOOL_SETTINGS')
    box.prop(fbx, "path_mode")
    box.prop(fbx, "embed_textures")


def draw_preferences(prefs, context):
    layout = prefs.layout

    row = layout.row(align=True)
    row.operator("export_hub.import_presets", icon='IMPORT')
    row.operator("export_hub.export_presets", icon='EXPORT')
    row.operator("export_hub.save_settings", icon='FILE_TICK')

    _draw_update_row(layout, prefs)

    layout.separator()

    # --- Projects ---
    layout.label(text="Projects", icon='OUTLINER')
    row = layout.row()
    row.template_list("EXH_UL_named", "projects", prefs, "projects",
                      prefs, "active_project_index", rows=4)
    col = row.column(align=True)
    col.menu("EXH_MT_new_project", icon='ADD', text="")
    col.operator("export_hub.project_remove", icon='REMOVE', text="")
    col.separator()
    col.operator("export_hub.project_duplicate", icon='DUPLICATE', text="")
    col.separator()
    col.operator("export_hub.project_move", icon='TRIA_UP', text="").direction = 'UP'
    col.operator("export_hub.project_move", icon='TRIA_DOWN', text="").direction = 'DOWN'

    idx = prefs.active_project_index
    if not (0 <= idx < len(prefs.projects)):
        layout.label(text="Add a project to get started.", icon='INFO')
        return
    project = prefs.projects[idx]

    # --- Presets within the active project ---
    box = layout.box()
    box.label(text="Presets in '%s'" % project.name, icon='PRESET')
    row = box.row()
    row.template_list("EXH_UL_named", "presets", project, "presets",
                      project, "active_preset_index", rows=3)
    col = row.column(align=True)
    col.operator("export_hub.preset_add", icon='ADD', text="")
    col.operator("export_hub.preset_remove", icon='REMOVE', text="")
    col.separator()
    col.operator("export_hub.preset_duplicate", icon='DUPLICATE', text="")
    col.separator()
    col.operator("export_hub.preset_move", icon='TRIA_UP', text="").direction = 'UP'
    col.operator("export_hub.preset_move", icon='TRIA_DOWN', text="").direction = 'DOWN'

    pidx = project.active_preset_index
    if not (0 <= pidx < len(project.presets)):
        box.label(text="Add a preset (e.g. Mesh, Animation).", icon='INFO')
        return
    preset = project.presets[pidx]

    dst = layout.box()
    dst.prop(preset, "export_dir")
    dst.label(text="Filename")
    _filename_row(dst, preset)
    row = dst.row(align=True)
    row.prop(preset, "version")
    row.prop(preset, "auto_increment_version", toggle=True)

    dst.prop(preset, "overwrite_mode")

    split = dst.row()
    # Splitting without {object} writes every object to one path, so make the
    # requirement visible at the switch rather than only at export time.
    split.alert = preset.split_per_object and "{object}" not in (preset.filename_template or "")
    split.prop(preset, "split_per_object")
    if split.alert:
        dst.label(text="Add {object} to the filename template", icon='ERROR')

    dst.prop(preset, "apply_transform_before_export")
    dst.prop(preset, "open_folder_after_export")

    layout.menu("EXH_MT_templates", icon='FILE_REFRESH')
    layout.label(text="FBX Settings for '%s'" % preset.name, icon='EXPORT')
    _draw_fbx_settings(layout, preset.fbx_settings)


class EXH_PT_export(bpy.types.Panel):
    bl_label = "Export Hub"
    bl_idname = "EXH_PT_export"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Export"

    def draw(self, context):
        layout = self.layout
        prefs = config.get_prefs(context)
        if prefs is None:
            layout.label(text="Add-on not available.", icon='ERROR')
            return

        _draw_update_banner(layout)

        if not len(prefs.projects):
            layout.label(text="No projects configured.", icon='INFO')
            layout.menu("EXH_MT_new_project", text="Start from an Engine", icon='PRESET')
            layout.operator("preferences.addon_show", text="Set up projects").module = __package__
            return

        layout.prop(prefs, "active_project_enum", text="")

        idx = prefs.active_project_index
        if not (0 <= idx < len(prefs.projects)):
            return
        project = prefs.projects[idx]

        if not len(project.presets):
            layout.label(text="No presets in this project.", icon='INFO')
            layout.operator("preferences.addon_show", text="Add presets").module = __package__
            return

        # Preset picker for this project.
        layout.template_list("EXH_UL_named", "panel_presets", project, "presets",
                             project, "active_preset_index", rows=3)

        pidx = project.active_preset_index
        if 0 <= pidx < len(project.presets):
            preset = project.presets[pidx]
            col = layout.column(align=True)
            col.label(text=preset.export_dir or "(no folder set)", icon='FILE_FOLDER')
            # Editable output name + token picker.
            _filename_row(col, preset)
            preview = config.resolve_filename(preset.filename_template, context, project, preset) + ".fbx"
            col.label(text="→ " + preview, icon='FILE_TICK')

        layout.separator()
        layout.operator("export_hub.validate", text="Validate", icon='CHECKMARK')
        _draw_validation(layout, prefs)

        row = layout.row()
        row.scale_y = 1.7
        row.operator("export_hub.export", text="Export", icon='EXPORT')
        layout.operator("export_hub.export_all", text="Export All Presets", icon='PACKAGE')

        row = layout.row(align=True)
        row.operator("export_hub.open_export_folder", text="Open Folder", icon='FOLDER_REDIRECT')
        row.operator("preferences.addon_show", text="Settings", icon='PREFERENCES').module = __package__


class EXH_PT_quick(bpy.types.Panel):
    """Collapsible sub-panel: edit the active preset's most-used settings inline."""

    bl_label = "Quick Settings"
    bl_idname = "EXH_PT_quick"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Export"
    bl_parent_id = "EXH_PT_export"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        prefs = config.get_prefs(context)
        if prefs is None or not len(prefs.projects):
            return False
        idx = prefs.active_project_index
        if not (0 <= idx < len(prefs.projects)):
            return False
        project = prefs.projects[idx]
        return 0 <= project.active_preset_index < len(project.presets)

    def draw(self, context):
        layout = self.layout
        prefs = config.get_prefs(context)
        project = prefs.projects[prefs.active_project_index]
        preset = project.presets[project.active_preset_index]
        fbx = preset.fbx_settings

        col = layout.column(align=True)
        col.prop(preset, "export_dir", text="")

        row = layout.row(align=True)
        row.prop(preset, "version")
        row.prop(preset, "auto_increment_version", text="", icon='SORTSIZE')

        box = layout.box()
        box.label(text="Options", icon='TOOL_SETTINGS')
        box.prop(fbx, "use_selection")
        row = box.row()
        row.enabled = fbx.use_selection
        row.prop(preset, "split_per_object")
        box.prop(preset, "apply_transform_before_export")
        box.prop(preset, "open_folder_after_export")
        box.prop(preset, "overwrite_mode")

        box = layout.box()
        box.label(text="FBX", icon='EXPORT')
        box.prop(fbx, "use_mesh_modifiers")
        box.prop(fbx, "use_triangles")
        box.prop(fbx, "bake_anim")
        row = box.row(align=True)
        row.prop(fbx, "axis_forward")
        row.prop(fbx, "axis_up")


class EXH_PT_history(bpy.types.Panel):
    """Collapsible sub-panel: re-export from a list of past exports."""

    bl_label = "History"
    bl_idname = "EXH_PT_history"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Export"
    bl_parent_id = "EXH_PT_export"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        prefs = config.get_prefs(context)
        count = len(prefs.history) if prefs else 0
        self.layout.label(text="(%d)" % count)

    def draw(self, context):
        layout = self.layout
        prefs = config.get_prefs(context)
        if prefs is None:
            return

        if not len(prefs.history):
            layout.label(text="No exports yet.", icon='INFO')
            return

        layout.template_list("EXH_UL_history", "", prefs, "history",
                             prefs, "active_history_index", rows=5)

        idx = prefs.active_history_index
        has_active = 0 <= idx < len(prefs.history)

        row = layout.row(align=True)
        row.enabled = has_active
        row.scale_y = 1.3
        row.operator("export_hub.history_reexport", text="Re-export", icon='EXPORT').index = -1

        row = layout.row(align=True)
        row.enabled = has_active
        row.operator("export_hub.history_open", text="Open Folder", icon='FOLDER_REDIRECT').index = -1
        row.operator("export_hub.history_remove", text="Remove", icon='X').index = -1

        layout.operator("export_hub.history_clear", text="Clear History", icon='TRASH')


def menu_func_export(self, context):
    """Entry appended to File > Export.

    Not a class, so it is registered by hand in __init__ rather than through the
    `classes` tuple — and removed there too, or a disabled add-on leaves a dead
    menu item behind.
    """
    self.layout.operator("export_hub.export_dialog", text="Export Hub (.fbx)", icon='EXPORT')


classes = (
    EXH_MT_templates,
    EXH_MT_new_project,
    EXH_MT_tokens,
    EXH_UL_named,
    EXH_UL_history,
    EXH_PT_export,
    EXH_PT_quick,
    EXH_PT_history,
)
