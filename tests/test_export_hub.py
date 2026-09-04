"""End-to-end test harness for the Export Hub Blender add-on.

Run headless with:

    blender --background --factory-startup --python tests/test_export_hub.py

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
    """Empty the current scene so each test starts from a known state."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


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


def _add_rig(name="Rig"):
    arm = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, arm)
    bpy.context.collection.objects.link(obj)

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bone = arm.edit_bones.new("Bone")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")

    # A short action so the animation preset has something to bake.
    obj.animation_data_create()
    action = bpy.data.actions.new("Run")
    obj.animation_data.action = action
    pbone = obj.pose.bones["Bone"]
    for frame, angle in ((1, 0.0), (24, 0.5)):
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


def main():
    print("Blender:", bpy.app.version_string)
    _install_addon()

    _run("addon_registered", test_addon_registered)
    _run("engine_template_creates_three_presets",
         test_engine_template_creates_three_presets)
    _run("single_static_export_writes_file", test_single_static_export_writes_file)
    _run("export_all_writes_one_file_per_preset",
         test_export_all_writes_one_file_per_preset)
    _run("validate_reports_checks", test_validate_reports_checks)
    _run("split_per_object_writes_each_object",
         test_split_per_object_writes_each_object)
    _run("overwrite_increment_keeps_both", test_overwrite_increment_keeps_both)
    _run("json_config_roundtrip", test_json_config_roundtrip)
    _run("filename_sanitising", test_filename_sanitising)

    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    total = len(_RESULTS)
    print("\n==================== SUMMARY ====================")
    for name, ok, detail in _RESULTS:
        print("  %-40s %s" % (name, "PASS" if ok else "FAIL: " + detail))
    print("  %d/%d tests passed" % (passed, total))
    print("=================================================")

    # Blender ignores a raised exception's exit code in some paths, so exit
    # explicitly to make CI and shell callers see the real result.
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
