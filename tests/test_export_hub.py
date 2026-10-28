"""End-to-end test harness for the Export Hub Blender add-on.

Run headless with:

    blender --background --factory-startup --python tests/test_export_hub.py

or, with the ``bpy`` module from PyPI (``pip install bpy``):

    python tests/test_export_hub.py

The harness and its first nine tests come from PR #1
(cursor/setup-blender-dev-environment-5287); the regression tests after them
pin the fixes made for the 1.8.0 release.

The script installs the repository as the ``export_hub`` add-on into a throwaway
Blender scripts directory, enables it alongside Blender's bundled FBX exporter,
builds a small scene and then drives the add-on the way a user would: creating a
project from an engine template, validating a selection and exporting real FBX
files. Every check asserts on observable results (files on disk, reported
counts, restored scene state) rather than merely importing modules.

It exits with status 0 only when every test passes, so it is safe to use as the
repository's canonical automated check.
"""

import os
import sys
import shutil
import tempfile
import traceback

import bpy
import addon_utils


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_MODULE = "export_hub"

_RESULTS = []


# --------------------------------------------------------------------------- #
# Tiny test runner
# --------------------------------------------------------------------------- #

def _run(name, func):
    try:
        func()
    except Exception as exc:  # noqa: BLE001 - report every failure, keep going
        _RESULTS.append((name, False, "%s: %s" % (type(exc).__name__, exc)))
        print("[FAIL] %s\n%s" % (name, traceback.format_exc()))
    else:
        _RESULTS.append((name, True, ""))
        print("[PASS] %s" % name)


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


# --------------------------------------------------------------------------- #
# Add-on installation and Blender setup
# --------------------------------------------------------------------------- #

def _install_addon():
    """Expose the repository as an importable ``export_hub`` package."""
    scripts_dir = bpy.utils.user_resource("SCRIPTS", path="addons", create=True)
    link_path = os.path.join(scripts_dir, ADDON_MODULE)

    if os.path.islink(link_path) or os.path.exists(link_path):
        if os.path.islink(link_path):
            os.unlink(link_path)
        else:
            shutil.rmtree(link_path)
    os.symlink(REPO_ROOT, link_path)

    # ``import export_hub`` needs the add-ons directory (the symlink's parent) on
    # the module search path; Blender does not always add it under
    # --factory-startup.
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    addon_utils.modules_refresh()
    # Blender's bundled FBX exporter is what the add-on ultimately calls.
    addon_utils.enable("io_scene_fbx", default_set=True, persistent=True)
    ok = addon_utils.enable(ADDON_MODULE, default_set=True, persistent=True)
    _assert(ok is not None, "add-on module failed to load")


def _prefs():
    from export_hub import config
    return config.get_prefs(bpy.context)


def _reset_scene():
    """Empty the file so each test starts from a known state."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in (bpy.data.meshes, bpy.data.armatures, bpy.data.actions, bpy.data.materials):
        for block in list(collection):
            collection.remove(block)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 250


def _add_cube(name, location=(0.0, 0.0, 0.0)):
    mesh = bpy.data.meshes.new(name)
    # A unit cube's 8 verts / 6 faces, built directly so no operator context is
    # needed in background mode.
    verts = [
        (-1, -1, -1), (-1, -1, 1), (-1, 1, -1), (-1, 1, 1),
        (1, -1, -1), (1, -1, 1), (1, 1, -1), (1, 1, 1),
    ]
    faces = [
        (0, 1, 3, 2), (4, 6, 7, 5), (0, 2, 6, 4),
        (1, 5, 7, 3), (0, 4, 5, 1), (2, 3, 7, 6),
    ]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    bpy.context.collection.objects.link(obj)
    return obj


def _add_rig(name="Rig", action_name="Run", frames=((1, 0.0), (24, 0.5)), extra_root_bones=()):
    """An armature with one deform bone and, unless action_name is None, an action.

    extra_root_bones adds parentless non-deform bones (IK targets, controls).
    """
    arm = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, arm)
    bpy.context.collection.objects.link(obj)

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bone = arm.edit_bones.new("Bone")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    for extra in extra_root_bones:
        control = arm.edit_bones.new(extra)
        control.head = (1.0, 0.0, 0.0)
        control.tail = (1.0, 0.0, 1.0)
        control.use_deform = False
    bpy.ops.object.mode_set(mode="OBJECT")

    if action_name:
        # A short action so the animation preset has something to bake.
        obj.animation_data_create()
        action = bpy.data.actions.new(action_name)
        obj.animation_data.action = action
        pbone = obj.pose.bones["Bone"]
        for frame, angle in frames:
            pbone.rotation_quaternion = (1.0, angle, 0.0, 0.0)
            pbone.keyframe_insert("rotation_quaternion", frame=frame)
    return obj


def _select_only(objects):
    for obj in bpy.data.objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]


def _make_project_from_engine(engine, export_dir, filename_template=None):
    prefs = _prefs()
    prefs.projects.clear()
    bpy.ops.export_hub.add_project_from_template(engine=engine)
    project = prefs.projects[prefs.active_project_index]
    for preset in project.presets:
        preset.export_dir = export_dir
        if filename_template is not None:
            preset.filename_template = filename_template
    return project


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_addon_registered():
    _assert(_prefs() is not None, "preferences not reachable after enable")
    for idname in ("export", "export_all", "validate", "add_project_from_template"):
        _assert(hasattr(bpy.ops.export_hub, idname),
                "operator export_hub.%s missing" % idname)


def test_engine_template_creates_three_presets():
    out = tempfile.mkdtemp(prefix="exh_tpl_")
    project = _make_project_from_engine("Unity", out)
    _assert(project.name == "Unity", "project name should match engine")
    _assert(len(project.presets) == 3,
            "expected 3 presets, got %d" % len(project.presets))
    variants = {p.name for p in project.presets}
    _assert(variants == {"Static Mesh", "Skeletal Mesh", "Animation"},
            "unexpected preset variants: %s" % variants)


def test_single_static_export_writes_file():
    _reset_scene()
    cube = _add_cube("Prop")
    out = tempfile.mkdtemp(prefix="exh_static_")
    project = _make_project_from_engine("Unity", out, filename_template="{preset}")

    # Static Mesh preset is first; drive it via the active-preset export button.
    project.active_preset_index = 0
    _select_only([cube])

    result = bpy.ops.export_hub.export()
    _assert(result == {"FINISHED"}, "export operator did not finish: %s" % (result,))

    expected = os.path.join(out, "Static Mesh.fbx")
    _assert(os.path.isfile(expected), "expected FBX not written: %s" % expected)
    _assert(os.path.getsize(expected) > 0, "exported FBX is empty")


def test_export_all_writes_one_file_per_preset():
    _reset_scene()
    cube = _add_cube("Body")
    rig = _add_rig("Rig")
    out = tempfile.mkdtemp(prefix="exh_all_")
    project = _make_project_from_engine("Unity", out, filename_template="{preset}")
    _select_only([cube, rig])

    result = bpy.ops.export_hub.export_all()
    _assert(result == {"FINISHED"}, "export_all did not finish: %s" % (result,))

    written = sorted(f for f in os.listdir(out) if f.endswith(".fbx"))
    _assert(len(written) == 3,
            "expected 3 FBX files from Export All, got %s" % written)


def test_validate_reports_checks():
    from export_hub import validate
    _reset_scene()
    rig = _add_rig("Rig")
    cube = _add_cube("Body")
    out = tempfile.mkdtemp(prefix="exh_val_")
    project = _make_project_from_engine("Unity", out)
    # Skeletal Mesh preset exports MESH + ARMATURE.
    project.active_preset_index = 1
    _select_only([cube, rig])

    result = bpy.ops.export_hub.validate()
    _assert(result == {"FINISHED"}, "validate did not finish: %s" % (result,))

    preset = project.presets[1]
    checks = validate.run(bpy.context, project, preset)
    errors, warnings, passed = validate.summarise(checks)
    _assert(len(checks) > 0, "validate produced no checks")
    _assert(passed > 0, "expected at least one passing check")


def test_split_per_object_writes_each_object():
    _reset_scene()
    a = _add_cube("Chair", location=(0, 0, 0))
    b = _add_cube("Table", location=(3, 0, 0))
    out = tempfile.mkdtemp(prefix="exh_split_")
    project = _make_project_from_engine("Unity", out, filename_template="{object}")
    project.active_preset_index = 0
    preset = project.presets[0]
    preset.split_per_object = True
    _select_only([a, b])

    result = bpy.ops.export_hub.export()
    _assert(result == {"FINISHED"}, "split export did not finish: %s" % (result,))

    for expected in ("Chair.fbx", "Table.fbx"):
        path = os.path.join(out, expected)
        _assert(os.path.isfile(path), "missing per-object file: %s" % expected)


def test_overwrite_increment_keeps_both():
    _reset_scene()
    cube = _add_cube("Prop")
    out = tempfile.mkdtemp(prefix="exh_inc_")
    project = _make_project_from_engine("Unity", out, filename_template="{preset}")
    project.active_preset_index = 0
    preset = project.presets[0]
    preset.overwrite_mode = "INCREMENT"
    _select_only([cube])

    bpy.ops.export_hub.export()
    bpy.ops.export_hub.export()

    written = sorted(f for f in os.listdir(out) if f.endswith(".fbx"))
    _assert(written == ["Static Mesh.fbx", "Static Mesh_001.fbx"],
            "increment mode did not keep both files: %s" % written)


def test_json_config_roundtrip():
    from export_hub import config
    _reset_scene()
    out = tempfile.mkdtemp(prefix="exh_json_")
    _make_project_from_engine("Unreal", out)
    prefs = _prefs()

    before = config.projects_to_data(prefs)
    json_path = os.path.join(out, "config.json")
    import json
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(before, fh)

    prefs.projects.clear()
    _assert(len(prefs.projects) == 0, "projects not cleared before import")

    with open(json_path, "r", encoding="utf-8") as fh:
        loaded = config.data_to_projects(prefs, json.load(fh), replace=True)
    _assert(loaded == 1, "expected one project imported, got %d" % loaded)
    _assert(len(prefs.projects[0].presets) == 3,
            "imported project lost its presets")


def test_json_import_refuses_malformed_file_and_keeps_projects():
    import json
    out = tempfile.mkdtemp(prefix="exh_badjson_")
    _make_project_from_engine("Unity", out)
    prefs = _prefs()
    path = os.path.join(out, "bad.json")
    malformed = (
        [1, 2],
        {"config_version": 2},
        {"config_version": 2, "projects": []},
        {"config_version": 2, "projects": [1, 2]},
        {"config_version": 2, "projects": [{"name": "X", "presets": "oops"}]},
        {"config_version": 2, "projects": [{"name": "X", "presets": [{"fbx": [1]}]}]},
        {"config_version": "two", "projects": [{"name": "X"}]},
    )
    for data in malformed:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        result = _call(bpy.ops.export_hub.import_presets, filepath=path, mode='REPLACE')
        _assert(result != {"FINISHED"}, "malformed config accepted: %s" % (data,))
        _assert([p.name for p in prefs.projects] == ["Unity"],
                "a refused import must leave the projects alone (%s): %s"
                % (data, [p.name for p in prefs.projects]))
        _assert(len(prefs.projects[0].presets) == 3, "presets lost after refusing %s" % (data,))

    # Odd but readable values are tolerated rather than crashing the import.
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"config_version": 2, "projects": [
            {"name": 5, "active_preset_index": "x", "presets": [{"name": "A"}]}]}, fh)
    result = _call(bpy.ops.export_hub.import_presets, filepath=path, mode='APPEND')
    _assert(result == {"FINISHED"}, "tolerable config refused: %s" % (result,))
    _assert([p.name for p in prefs.projects] == ["Unity", "5"], [p.name for p in prefs.projects])


def test_history_reexport_repeats_the_recorded_export():
    from export_hub import operators
    _reset_scene()
    chair = _add_cube("Chair")
    chair.scale = (2.0, 2.0, 2.0)
    table = _add_cube("Table", location=(3, 0, 0))
    other = _add_cube("Other", location=(6, 0, 0))
    out = tempfile.mkdtemp(prefix="exh_hist_")
    project = _make_project_from_engine("Unity", out, filename_template="{object}")
    project.active_preset_index = 0
    preset = project.presets[0]
    preset.split_per_object = True
    preset.apply_transform_before_export = True
    _select_only([chair, table])
    _assert(bpy.ops.export_hub.export() == {"FINISHED"}, "first export failed")
    prefs = _prefs()
    index = next(i for i, e in enumerate(prefs.history) if e.name == "Chair.fbx")

    # The user has moved on: another object is selected now.
    _select_only([other])
    seen = []
    real_export = operators._export_fbx

    def spy(context, filepath, kwargs):
        seen.append((os.path.basename(filepath),
                     sorted((o.name, tuple(round(v, 3) for v in o.scale)) for o in context.selected_objects)))
        return real_export(context, filepath, kwargs)

    operators._export_fbx = spy
    try:
        result = bpy.ops.export_hub.history_reexport(index=index)
    finally:
        operators._export_fbx = real_export
    _assert(result == {"FINISHED"}, "re-export failed: %s" % (result,))
    _assert(seen == [("Chair.fbx", [("Chair", (1.0, 1.0, 1.0))])],
            "re-export should write the recorded object, baked again: %s" % seen)
    _assert(_fbx_objects(os.path.join(out, "Chair.fbx"), b"Model") == ["Chair"],
            _fbx_objects(os.path.join(out, "Chair.fbx"), b"Model"))
    _assert(list(bpy.context.selected_objects) == [other] and bpy.context.view_layer.objects.active == other,
            "selection not restored after the re-export")
    _assert(tuple(chair.scale) == (2.0, 2.0, 2.0), "original object was modified")
    _assert(prefs.history[0].name == "Chair.fbx" and prefs.history[0].baked,
            "the re-export's own history entry should repeat the recording")

    chair.name = "Stool"
    result = _call(bpy.ops.export_hub.history_reexport, index=0)
    _assert(result != {"FINISHED"}, "re-export of an object that is gone should be refused")


def test_update_check_honours_online_access():
    import export_hub
    from export_hub import updates
    prefs = _prefs()
    prefs.check_updates = True
    prefs.last_update_check = ""
    updates.reset()
    real = updates.network_allowed
    updates.network_allowed = lambda: False   # Preferences > System > Allow Online Access off
    try:
        result = _call(bpy.ops.export_hub.check_updates)
        _assert(result != {"FINISHED"}, "Check Now must not go online with online access off")
        export_hub._startup_update_check()
        _assert(updates.state()["status"] == "idle", "a check started: %s" % updates.state())
        _assert(prefs.last_update_check == "", "no check ran, so none is recorded")
    finally:
        updates.network_allowed = real
    _assert(updates.network_allowed() == bool(getattr(bpy.app, "online_access", True)),
            "network_allowed must follow bpy.app.online_access")


def test_failed_update_check_is_retried():
    import datetime
    from export_hub import updates
    prefs = _prefs()
    prefs.last_update_check = ""
    updates._state.update(status="error", latest=None, message="offline")
    updates._redraw_when_done()
    _assert(prefs.last_update_check == "", "a failed check must not count as today's check")
    updates._state.update(status="current", latest=(1, 8, 0), message="")
    updates._redraw_when_done()
    _assert(prefs.last_update_check == datetime.date.today().isoformat(),
            "a completed check is recorded: %r" % prefs.last_update_check)
    updates.reset()


def test_startup_update_timer_survives_loading_a_file():
    import addon_utils
    import export_hub
    addon_utils.disable(ADDON_MODULE)
    addon_utils.enable(ADDON_MODULE, default_set=True)
    import export_hub
    bpy.ops.wm.read_homefile(use_empty=True)
    _assert(bpy.app.timers.is_registered(export_hub._startup_update_check),
            "Blender drops non-persistent timers when the startup file loads")


def test_template_notes_and_settings():
    from export_hub import templates
    unreal = templates.get("unreal_static")
    _assert("Uniform Scale to 100" not in unreal.notes,
            "All Local already writes centimetres; Import Uniform Scale 100 makes it 100x too big")
    unity_static = templates.get("unity_static")
    _assert("placed" in unity_static.notes,
            "Unity Static should warn that toggling Apply Transform lays placed copies down")
    for template in templates.for_engine("Unity"):
        _assert(template.settings.get("use_tspace") is False,
                "%s: Unity recalculates tangents on import" % template.id)


def test_buttons_respect_auto_save_preferences():
    preferences = bpy.context.preferences
    path = os.path.join(bpy.utils.user_resource("CONFIG"), "userpref.blend")
    old = preferences.use_preferences_save
    try:
        preferences.use_preferences_save = False
        preferences.is_dirty = False
        if os.path.exists(path):
            os.remove(path)
        bpy.ops.export_hub.project_add()
        _assert(not os.path.exists(path),
                "with Auto-Save Preferences off a button must not write userpref.blend")
        _assert(preferences.is_dirty, "the change should light up Save Preferences instead")
        from export_hub import ui

        class _Layout:
            def __init__(self):
                self.labels, self.operators = [], []

            def row(self, **_kwargs):
                return self

            def label(self, text="", **_kwargs):
                self.labels.append(text)

            def operator(self, idname, **_kwargs):
                self.operators.append(idname)
                return type("Props", (), {})()

        layout = _Layout()
        ui._draw_unsaved_hint(layout, bpy.context)
        _assert(layout.operators == ["export_hub.save_settings"] and "Auto-Save" in layout.labels[0],
                "the panel should say the changes are unsaved: %s %s" % (layout.labels, layout.operators))
        _assert(bpy.ops.export_hub.save_settings() == {"FINISHED"}, "Save Settings failed")
        _assert(os.path.exists(path), "Save Settings writes the preferences on request")

        preferences.use_preferences_save = True
        os.remove(path)
        bpy.ops.export_hub.project_add()
        _assert(os.path.exists(path), "with Auto-Save Preferences on a button saves at once")
    finally:
        preferences.use_preferences_save = old


def test_fbx_settings_cover_the_exporter():
    from export_hub import properties
    known = set(bpy.ops.export_scene.fbx.get_rna_type().properties.keys())
    # Not settings: the file dialog's own fields, and batch mode, which Export Hub's
    # presets replace. use_mesh_modifiers_render has done nothing since Blender 2.8.
    not_settings = {"rna_type", "filepath", "check_existing", "filter_glob", "collection",
                    "batch_mode", "use_batch_own_dir", "use_mesh_modifiers_render", "use_metadata"}
    missing = sorted(known - not_settings - set(properties.FBX_SETTING_KEYS))
    _assert(not missing, "exporter options the presets cannot set: %s" % missing)
    fbx = properties.EXH_FBXSettings.bl_rna.properties
    smoothing = [item.identifier for item in fbx["mesh_smooth_type"].enum_items]
    _assert("SMOOTH_GROUP" in smoothing, "Smoothing Groups missing: %s" % smoothing)

    # A value this Blender's exporter does not know (a newer smoothing mode on an
    # older Blender) is dropped, not passed on to fail the whole export.
    from export_hub import operators
    kept = operators._supported_fbx_kwargs({"mesh_smooth_type": "FROM_THE_FUTURE", "use_tspace": True,
                                            "object_types": {"MESH", "HOLOGRAM"}})
    _assert(kept == {"use_tspace": True, "object_types": {"MESH"}}, "unknown values kept: %s" % kept)


def test_filenames_fit_byte_limits_and_avoid_reserved_names():
    from export_hub import config
    long_name = config.sanitize_filename("ş" * 300)
    _assert(len(long_name.encode("utf-8")) <= config.MAX_FILENAME,
            "%d bytes: Linux and macOS limit a name to 255 bytes, not characters"
            % len(long_name.encode("utf-8")))
    _assert(long_name == "ş" * (config.MAX_FILENAME // 2), "cut inside a character: %r" % long_name[-3:])
    _assert(config.sanitize_filename("CON.v001") == "CON_.v001",
            "Windows reserves CON whatever follows the dot: %s" % config.sanitize_filename("CON.v001"))
    _assert(config.sanitize_filename("lpt1 .old") == "lpt1_ .old", config.sanitize_filename("lpt1 .old"))
    _assert(config.sanitize_filename("Console.v001") == "Console.v001", "only whole device names are reserved")


def test_split_export_refuses_two_objects_on_one_file():
    _reset_scene()
    first = _add_cube("Chair:1")
    second = _add_cube("Chair/1", location=(3, 0, 0))
    out = tempfile.mkdtemp(prefix="exh_clash_")
    project = _make_project_from_engine("Unity", out, filename_template="{object}")
    project.active_preset_index = 0
    preset = project.presets[0]
    preset.split_per_object = True
    preset.overwrite_mode = 'OVERWRITE'
    _select_only([first, second])
    from export_hub import operators
    status, message = operators._run_export(bpy.context, project, preset, save=False)
    _assert(_fbx_objects(os.path.join(out, "Chair_1.fbx"), b"Model") == ["Chair:1"],
            "the second object overwrote the first one's file")
    _assert("Chair/1" in message and "same file" in message, "the clash should be reported: %s" % message)
    history = [e.name for e in _prefs().history]
    _assert(history.count("Chair_1.fbx") == 1, "one file, one history entry: %s" % history)


def test_validator_warns_when_split_separates_skin_from_rig():
    from export_hub import validate
    _reset_scene()
    rig = _add_rig("Rig", action_name=None)
    body = _add_cube("Body")
    body.modifiers.new("Armature", 'ARMATURE').object = rig
    body.parent = rig
    out = tempfile.mkdtemp(prefix="exh_skin_")
    project = _make_project_from_engine("Unity", out, filename_template="{object}")
    preset = project.presets[1]
    preset.split_per_object = True
    _select_only([body, rig])
    warnings = _messages(validate.run(bpy.context, project, preset), 'WARNING')
    _assert(any("Body" in m and "Rig" in m and "separate" in m for m in warnings),
            "splitting a skinned mesh from its armature should be flagged: %s" % warnings)


def test_folder_fields_support_relative_paths():
    if "is_path_supports_blend_relative" not in bpy.types.Property.bl_rna.properties:
        return  # Blender before the option existed
    from export_hub import properties, operators
    fields = (properties.EXH_ExportPreset.bl_rna.properties["export_dir"],
              bpy.ops.export_hub.export_dialog.get_rna_type().properties["custom_dir"])
    for field in fields:
        _assert(field.is_path_supports_blend_relative,
                "%s should offer // paths in the file browser" % field.identifier)


def test_filename_sanitising():
    from export_hub import config
    _assert(config.sanitize_filename("a/b:c*d") == "a_b_c_d",
            "illegal characters not replaced")
    _assert(config.sanitize_filename("CON") == "CON_",
            "reserved device name not suffixed")
    _assert(config.sanitize_filename("name. .") == "name",
            "trailing dots/spaces not trimmed")
    _assert(config.sanitize_filename("") == "export",
            "empty name did not fall back")


# --------------------------------------------------------------------------- #
# Regression tests for the 1.8.0 review
# --------------------------------------------------------------------------- #

def _load_repo_module(name):
    """Import a top-level script of the repository (package.py) by path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_exh_" + name, os.path.join(REPO_ROOT, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fbx_objects(path, kind):
    """Names of the FBX objects of one kind (b"AnimationStack", b"Material", ...)."""
    from io_scene_fbx import parse_fbx
    root, _version = parse_fbx.parse(path)
    names = []
    for top in root.elems:
        if top.id == b"Objects":
            for elem in top.elems:
                if elem.id == kind:
                    names.append(elem.props[1].split(b"\x00")[0].decode())
    return names


def _messages(checks, level=None):
    return [c.message for c in checks if level is None or c.level == level]


def _call(op, **kwargs):
    """Run an operator; an operator that reports an error raises, return its text instead."""
    try:
        return op(**kwargs)
    except RuntimeError as exc:
        return "ERROR: %s" % exc


def test_package_zip_uses_forward_slashes():
    package = _load_repo_module("package")
    out = tempfile.mkdtemp(prefix="exh_zip_")
    path, entries = package.build(out)
    _assert(os.path.isfile(path), "no zip written")
    _assert(all("\\" not in e and e.startswith("export_hub/") for e in entries),
            "entries must sit in export_hub/ with forward slashes: %s" % entries)
    shipped = {e.split("/", 1)[1] for e in entries}
    _assert(set(package.FILES) <= shipped, "required files missing: %s" % (set(package.FILES) - shipped))
    _assert("blender_manifest.toml" not in shipped,
            "a manifest makes 4.2+ install the classic zip as an extension, under another module name")
    _assert(shipped <= set(package.FILES + package.OPTIONAL),
            "files outside the whitelist shipped: %s" % (shipped - set(package.FILES + package.OPTIONAL)))


def test_baked_copy_exports_one_clip_and_leaks_nothing():
    _reset_scene()
    edit = bpy.context.preferences.edit
    old = edit.use_duplicate_action
    edit.use_duplicate_action = True
    try:
        rig = _add_rig("Rig")
        import math
        rig.rotation_euler = (0.0, 0.0, math.radians(90))
        out = tempfile.mkdtemp(prefix="exh_clip_")
        project = _make_project_from_engine("Unity", out, filename_template="{preset}")
        project.active_preset_index = 2
        project.presets[2].apply_transform_before_export = True
        project.presets[2].overwrite_mode = 'OVERWRITE'
        _select_only([rig])
        for _run_number in range(2):
            result = bpy.ops.export_hub.export()
            _assert(result == {"FINISHED"}, "export did not finish: %s" % (result,))
            stacks = _fbx_objects(os.path.join(out, "Animation.fbx"), b"AnimationStack")
            _assert(len(stacks) == 1, "expected one clip, got %s" % stacks)
            _assert(sorted(a.name for a in bpy.data.actions) == ["Run"],
                    "duplicated actions left behind: %s" % [a.name for a in bpy.data.actions])
        _assert(rig.animation_data.action.name == "Run", "original rig lost its action")
        _assert(edit.use_duplicate_action, "the user's Duplicate Data > Action was not put back")
        from export_hub import operators
        bpy.context.preferences.is_dirty = False
        with operators._duplicates_share_animation_and_materials(bpy.context):
            _assert(not edit.use_duplicate_action, "copies should share the action")
        _assert(edit.use_duplicate_action and not bpy.context.preferences.is_dirty,
                "borrowing the preference must leave it, and the unsaved flag, as they were")
    finally:
        edit.use_duplicate_action = old


def test_baked_copy_keeps_material_names():
    _reset_scene()
    edit = bpy.context.preferences.edit
    old = edit.use_duplicate_material
    edit.use_duplicate_material = True
    try:
        cube = _add_cube("Prop")
        cube.data.materials.append(bpy.data.materials.new("Wood"))
        cube.scale = (2.0, 2.0, 2.0)
        out = tempfile.mkdtemp(prefix="exh_mat_")
        project = _make_project_from_engine("Unity", out, filename_template="{preset}")
        project.active_preset_index = 0
        project.presets[0].apply_transform_before_export = True
        _select_only([cube])
        result = bpy.ops.export_hub.export()
        _assert(result == {"FINISHED"}, "export did not finish: %s" % (result,))
        materials = _fbx_objects(os.path.join(out, "Static Mesh.fbx"), b"Material")
        _assert(materials == ["Wood"], "FBX materials should be ['Wood'], got %s" % materials)
        _assert([m.name for m in bpy.data.materials] == ["Wood"],
                "duplicated materials left behind: %s" % [m.name for m in bpy.data.materials])
    finally:
        edit.use_duplicate_material = old


def test_scaled_animated_rig_bake_is_refused():
    from export_hub import validate
    _reset_scene()
    rig = _add_rig("Rig")
    rig.scale = (2.0, 2.0, 2.0)
    out = tempfile.mkdtemp(prefix="exh_scaled_")
    project = _make_project_from_engine("Unity", out, filename_template="{preset}")
    project.active_preset_index = 2
    preset = project.presets[2]
    preset.apply_transform_before_export = True
    _select_only([rig])
    errors = _messages(validate.run(bpy.context, project, preset), 'ERROR')
    _assert(any("drift" in m for m in errors), "validator should refuse the bake: %s" % errors)
    result = _call(bpy.ops.export_hub.export)
    _assert(result != {"FINISHED"}, "export should be refused")
    _assert(not os.listdir(out), "nothing should be written: %s" % os.listdir(out))
    _assert(tuple(rig.scale) == (2.0, 2.0, 2.0), "original rig was modified")


def _animation_bake_project(prefix):
    out = tempfile.mkdtemp(prefix=prefix)
    project = _make_project_from_engine("Unity", out, filename_template="{preset}")
    project.active_preset_index = 2
    preset = project.presets[2]
    preset.apply_transform_before_export = True
    return out, project, preset


def test_baked_copy_of_a_rig_in_nla_tweak_mode():
    _reset_scene()
    rig = _add_rig("Rig")
    ad = rig.animation_data
    track = ad.nla_tracks.new()
    strip = track.strips.new("Run", 1, ad.action)
    ad.action = None
    track.select = True
    strip.select = True
    ad.nla_tracks.active = track
    ad.use_tweak_mode = True
    _assert(ad.use_tweak_mode, "test setup: tweak mode did not start")
    out, project, preset = _animation_bake_project("exh_tweak_")
    _select_only([rig])
    result = _call(bpy.ops.export_hub.export)
    _assert(result == {"FINISHED"}, "baked export in tweak mode failed: %s" % (result,))
    _assert(sorted(a.name for a in bpy.data.actions) == ["Run"],
            "duplicated actions left behind: %s" % [a.name for a in bpy.data.actions])
    _assert(rig.animation_data.use_tweak_mode, "the user's tweak mode was changed")


def test_bake_refuses_rigs_that_would_drift():
    from export_hub import validate
    # Scale inherited from a selected parent drifts just like the rig's own scale.
    _reset_scene()
    holder = bpy.data.objects.new("Holder", None)
    bpy.context.collection.objects.link(holder)
    holder.scale = (2.0, 2.0, 2.0)
    rig = _add_rig("Rig")
    rig.parent = holder
    bpy.context.view_layer.update()
    out, project, preset = _animation_bake_project("exh_drift_parent_")
    _select_only([rig, holder])
    errors = _messages(validate.run(bpy.context, project, preset), 'ERROR')
    _assert(any("drift" in m for m in errors), "validator missed the inherited scale: %s" % errors)
    _assert(_call(bpy.ops.export_hub.export) != {"FINISHED"}, "inherited-scale rig was baked")
    _assert(not os.listdir(out), os.listdir(out))

    # An unassigned action that All Actions exports is animation too.
    _reset_scene()
    rig = _add_rig("Rig")
    rig.animation_data.action.use_fake_user = True
    rig.animation_data.action = None
    rig.scale = (2.0, 2.0, 2.0)
    out, project, preset = _animation_bake_project("exh_drift_all_")
    _select_only([rig])
    errors = _messages(validate.run(bpy.context, project, preset), 'ERROR')
    _assert(any("drift" in m for m in errors), errors)
    _assert(_call(bpy.ops.export_hub.export) != {"FINISHED"}, "All Actions rig was baked")
    _assert(not os.listdir(out), os.listdir(out))


def test_validator_follows_all_actions_range():
    from export_hub import validate
    _reset_scene()
    rig = _add_rig("Rig", frames=((1, 0.0), (60, 0.5)))
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 24
    out = tempfile.mkdtemp(prefix="exh_range_")
    project = _make_project_from_engine("Unity", out)
    preset = project.presets[2]
    _select_only([rig])
    messages = _messages(validate.run(bpy.context, project, preset))
    _assert(not any("will be cut" in m for m in messages),
            "All Actions bakes each action over its own range: %s" % messages)
    _assert(any("1 clip(s) will be exported" in m for m in messages), messages)

    preset.fbx_settings.bake_anim_use_all_actions = False
    warnings = _messages(validate.run(bpy.context, project, preset), 'WARNING')
    _assert(any("will be cut" in m for m in warnings),
            "with both modes off the scene range applies: %s" % warnings)


def test_validator_flags_action_without_slot():
    from export_hub import validate
    _reset_scene()
    donor = _add_rig("RigA", action_name="Walk")
    action = donor.animation_data.action
    rig = _add_rig("RigB", action_name=None)
    rig.animation_data_create()
    rig.animation_data.action = action
    if not hasattr(rig.animation_data, "action_slot"):
        return  # before Blender 4.4 there are no slots
    bpy.data.objects.remove(donor)
    _assert(rig.animation_data.action_slot is None, "test setup: expected no slot")
    out = tempfile.mkdtemp(prefix="exh_slot_")
    project = _make_project_from_engine("Unity", out)
    _select_only([rig])
    checks = validate.run(bpy.context, project, project.presets[2])
    flagged = [m for m in _messages(checks) if "without a slot" in m]
    _assert(flagged, "unslotted action not reported: %s" % _messages(checks))


def test_validator_counts_nla_only_animation():
    from export_hub import validate
    _reset_scene()
    rig = _add_rig("Rig")
    action = rig.animation_data.action
    rig.animation_data.nla_tracks.new().strips.new("Run", 1, action)
    rig.animation_data.action = None
    out = tempfile.mkdtemp(prefix="exh_nla_")
    project = _make_project_from_engine("Unity", out)
    _select_only([rig])
    errors = _messages(validate.run(bpy.context, project, project.presets[2]), 'ERROR')
    _assert(not errors, "All Actions exports the pushed-down action: %s" % errors)

    preset = project.presets[2]
    preset.fbx_settings.bake_anim_use_all_actions = False
    preset.fbx_settings.bake_anim_use_nla_strips = False
    errors = _messages(validate.run(bpy.context, project, preset), 'ERROR')
    _assert(not errors, "the scene-range bake evaluates the NLA too: %s" % errors)


def test_validator_reads_rotation_modes_and_mirrors():
    import math
    from mathutils import Quaternion
    from export_hub import validate
    _reset_scene()
    cube = _add_cube("Prop")
    cube.rotation_mode = 'QUATERNION'
    cube.rotation_quaternion = Quaternion((0.0, 0.0, 1.0), math.radians(90))
    out = tempfile.mkdtemp(prefix="exh_rot_")
    project = _make_project_from_engine("Unity", out)
    _select_only([cube])
    warnings = _messages(validate.run(bpy.context, project, project.presets[0]), 'WARNING')
    _assert(any("rotation" in m and "not applied" in m for m in warnings),
            "quaternion rotation not reported: %s" % warnings)

    # Through run(), with no depsgraph update in between: the values come from the
    # object itself, so a script that just set them is judged right too.
    cube.rotation_mode = 'XYZ'   # Blender converts the 90° turn into the euler
    cube.rotation_euler = (0.0, 0.0, 0.0)
    cube.scale = (-1.0, -1.0, 1.0)
    checks = validate.run(bpy.context, project, project.presets[0])
    _assert(not _messages(checks, 'ERROR'), "(-1, -1, 1) is a turn, not a mirror: %s" % _messages(checks))
    _assert(any("180° turn" in m for m in _messages(checks, 'WARNING')), _messages(checks))
    _assert(not any("rotation is" in m for m in _messages(checks)), "no rotation was set: %s" % _messages(checks))

    cube.scale = (-1.0, 1.0, 1.0)
    checks = validate.run(bpy.context, project, project.presets[0])
    errors = _messages(checks, 'ERROR')
    _assert(any("(-1.000, 1.000, 1.000)" in m for m in errors), "the user's scale should be shown: %s" % errors)
    _assert(not any("rotation is" in m for m in _messages(checks)),
            "a mirror is not a rotation: %s" % _messages(checks))

    rig = _add_rig("Rig", action_name=None)
    rig.scale = (1.0, 1.0, -1.0)
    _select_only([rig])
    messages = _messages(validate.run(bpy.context, project, project.presets[1]))
    _assert(not any("yawed" in m for m in messages), "a mirrored rig is not yawed: %s" % messages)

    _reset_scene()
    parent = bpy.data.objects.new("Mirror", None)
    bpy.context.collection.objects.link(parent)
    parent.scale = (-1.0, 1.0, 1.0)
    child = _add_cube("Child")
    child.parent = parent
    bpy.context.view_layer.update()
    _select_only([child])
    errors = _messages(validate.run(bpy.context, project, project.presets[0]), 'ERROR')
    _assert(any("mirrored by a parent" in m for m in errors), "parent mirror not reported: %s" % errors)


def test_validator_root_bones_follow_deform_only():
    from export_hub import validate
    _reset_scene()
    rig = _add_rig("Rig", extra_root_bones=("IK_foot.L", "IK_foot.R"))
    out = tempfile.mkdtemp(prefix="exh_roots_")
    project = _make_project_from_engine("Unity", out)
    preset = project.presets[1]
    preset.fbx_settings.use_armature_deform_only = True
    _select_only([rig])
    messages = _messages(validate.run(bpy.context, project, preset))
    _assert(any("single root bone 'Bone'" in m for m in messages),
            "control bones are not exported with Only Deform Bones: %s" % messages)
    preset.fbx_settings.use_armature_deform_only = False
    warnings = _messages(validate.run(bpy.context, project, preset), 'WARNING')
    _assert(any("3 root bones" in m for m in warnings), warnings)


def test_zz_extension_package_installs_and_knows_its_version():
    """Last on purpose: swaps the add-on for its extension build and back."""
    if bpy.app.version < (4, 2, 0):
        return
    import subprocess
    import addon_utils
    package = _load_repo_module("package")
    out = tempfile.mkdtemp(prefix="exh_ext_")
    path, entries = package.build_extension(out)
    _assert("blender_manifest.toml" in entries, entries)
    cli = os.path.join(bpy.utils.system_resource("SCRIPTS"), "addons_core", "bl_pkg", "cli", "blender_ext.py")
    if os.path.isfile(cli):
        run = subprocess.run([sys.executable, "-I", cli, "validate", path], capture_output=True, text=True)
        _assert(run.returncode == 0, "manifest rejected: %s%s" % (run.stdout, run.stderr))

    module = "bl_ext.user_default.export_hub"
    addon_utils.disable(ADDON_MODULE, default_set=True)
    try:
        bpy.ops.extensions.package_install_files(filepath=path, repo="user_default", enable_on_install=True)
        _assert(module in bpy.context.preferences.addons, "extension did not enable")
        updates = sys.modules[module + ".updates"]
        expected = tuple(int(v) for v in package.version().split("."))
        _assert(updates.current_version() == expected,
                "Blender strips bl_info from extensions; the update check read %s"
                % (updates.current_version(),))
        _reset_scene()
        _add_cube("Prop")
        _select_only([bpy.data.objects["Prop"]])
        bpy.ops.export_hub.add_project_from_template(engine="Unity")
        prefs = bpy.context.preferences.addons[module].preferences
        project = prefs.projects[prefs.active_project_index]
        project.presets[0].export_dir = out
        project.presets[0].filename_template = "{preset}"
        _assert(bpy.ops.export_hub.export() == {"FINISHED"}, "export from the extension failed")
        _assert(os.path.isfile(os.path.join(out, "Static Mesh.fbx")), os.listdir(out))
    finally:
        addon_utils.disable(module, default_set=True)
        repo_index = [r.module for r in bpy.context.preferences.extensions.repos].index("user_default")
        bpy.ops.extensions.package_uninstall(repo_index=repo_index, pkg_id="export_hub")
        addon_utils.enable(ADDON_MODULE, default_set=True)


def main():
    print("Blender:", bpy.app.version_string)
    _install_addon()

    only = os.environ.get("EXH_TESTS", "")
    tests = [(name, func) for name, func in globals().items()
             if name.startswith("test_") and callable(func)
             and (not only or any(part in name for part in only.split(",")))]
    for name, func in tests:
        _run(name[len("test_"):], func)

    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    total = len(_RESULTS)
    print("\n==================== SUMMARY ====================")
    for name, ok, detail in _RESULTS:
        print("  %-48s %s" % (name, "PASS" if ok else "FAIL: " + detail))
    print("  %d/%d tests passed" % (passed, total))
    print("=================================================")

    # Blender ignores a raised exception's exit code in some paths, so exit
    # explicitly to make CI and shell callers see the real result.
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
