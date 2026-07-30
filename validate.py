"""Pre-export sanity checks.

These catch the mistakes that export *successfully* and only surface in the
engine: an unapplied scale, a mirrored object whose normals invert, a mesh with
no UVs, a rig yawed away from the axis the engine treats as forward, an
animation preset with nothing to bake.

Every rule reports on success as well as failure. A validator that only speaks
up when something is wrong leaves you unable to tell "everything is fine" from
"nothing was actually checked", so each rule returns what it looked at and what
it found either way.

The rules are plain functions over plain values — no bpy — so they can be
reasoned about and tested without launching Blender. `run()` is the only part
that touches Blender data, and all it does is read values and hand them over.
"""

import math
from collections import namedtuple

# level: 'ERROR'   almost certainly broken in the engine
#        'WARNING' suspicious, usually a mistake, sometimes deliberate
#        'INFO'    context: what was checked, and against what
#        'OK'      this rule ran and the data passed it
Check = namedtuple("Check", "level message")

_SCALE_TOLERANCE = 1e-4
_ANGLE_TOLERANCE = math.radians(0.05)

# Blender characters are conventionally modelled facing -Y, which is what the
# engine presets translate into the engine's own forward axis.
FORWARD_CONVENTION = "-Y"

# Rates engines and DCC tools actually deal in. Anything else is almost always
# a scene that was set up by accident.
_STANDARD_FRAME_RATES = (24, 25, 30, 48, 50, 60, 120)

# Compared with a tolerance rather than by rounding. Blender stores 23.976 fps as
# fps=24 with fps_base=1.001, and rounding the real rate back to 24 is exactly
# how an NTSC scene — the case this rule exists to catch — used to pass.
_FPS_TOLERANCE = 0.01

# Which object_types entry the FBX exporter files each Blender type under.
# Curves, text, metaballs and surfaces are converted to meshes on the way out but
# the exporter counts them as OTHER, not MESH, so the mapping cannot be skipped.
_FBX_TYPE_OF = {
    'MESH': 'MESH',
    'ARMATURE': 'ARMATURE',
    'EMPTY': 'EMPTY',
    'CAMERA': 'CAMERA',
    'LIGHT': 'LIGHT',
}

# Types where Ctrl+A has something to bake the transform into. An empty, a camera
# or a light carries no data, so "apply the rotation" there is advice that cannot
# be followed — and the exported transform of an empty is usually deliberate.
_TRANSFORMABLE = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'ARMATURE', 'LATTICE'}

# Worst first — the panel lists them in this order.
_SEVERITY = {'ERROR': 0, 'WARNING': 1, 'INFO': 2, 'OK': 3}


def check_transform(name, scale, rotation_euler, baked_on_export=False):
    """Unapplied transforms on an object about to be exported.

    `baked_on_export` says the preset will apply transforms to a temporary copy.
    In that case an unapplied scale is not a problem to fix, and telling the user
    to press Ctrl+A would be advising a destructive edit the add-on is about to
    handle for them. Negative scale still matters — baking it does not un-invert
    the normals.
    """
    checks = []
    sx, sy, sz = scale

    if min(sx, sy, sz) < 0.0:
        checks.append(Check(
            'ERROR',
            "%s: negative scale (%.3f, %.3f, %.3f) — faces will be inside out "
            "in the engine. Apply scale, then flip normals." % (name, sx, sy, sz),
        ))
    elif any(abs(s - 1.0) > _SCALE_TOLERANCE for s in (sx, sy, sz)):
        uniform = abs(max(sx, sy, sz) - min(sx, sy, sz)) <= _SCALE_TOLERANCE
        if baked_on_export:
            checks.append(Check(
                'OK',
                "%s: scale is %s(%.3f, %.3f, %.3f) — baked into a temporary copy "
                "at export, your object is left alone"
                % (name, "" if uniform else "non-uniform ", sx, sy, sz),
            ))
        else:
            checks.append(Check(
                'WARNING',
                "%s: scale is %s(%.3f, %.3f, %.3f), not applied — Ctrl+A > Scale"
                % (name, "" if uniform else "non-uniform ", sx, sy, sz),
            ))
    else:
        checks.append(Check('OK', "%s: scale applied (1, 1, 1)" % name))

    degrees = [math.degrees(r) for r in rotation_euler]
    if any(abs(r) > _ANGLE_TOLERANCE for r in rotation_euler):
        if baked_on_export:
            checks.append(Check(
                'OK',
                "%s: rotation (%.1f°, %.1f°, %.1f°) — baked into a temporary copy at export"
                % (name, degrees[0], degrees[1], degrees[2]),
            ))
        else:
            checks.append(Check(
                'WARNING',
                "%s: rotation is (%.1f°, %.1f°, %.1f°), not applied — Ctrl+A > Rotation"
                % (name, degrees[0], degrees[1], degrees[2]),
            ))
    else:
        checks.append(Check('OK', "%s: rotation applied (0°, 0°, 0°)" % name))

    return checks


def check_scene_units(unit_scale):
    """Scene unit scale, the most common cause of an asset arriving at the wrong size.

    Engines read one Blender unit as one metre. A scene authored at unit scale
    0.01 exports geometry that is right in Blender and 100x off in the engine,
    and nothing in the viewport hints at it.
    """
    if abs(unit_scale - 1.0) > _SCALE_TOLERANCE:
        return [Check(
            'WARNING',
            "Scene unit scale is %.4f, not 1.0 — the engine reads 1 Blender unit as "
            "1 metre, so everything will import at the wrong size" % unit_scale,
        )]
    return [Check('OK', "Scene unit scale is 1.0 (1 unit = 1 metre)")]


def check_frame_rate(fps):
    """Flag a frame rate that is not one of the rates engines expect.

    `fps` is the *effective* rate, fps/fps_base, not Blender's integer fps field.
    The two differ for exactly the rates worth flagging: Blender's "23.98 fps"
    preset is fps=24 with fps_base=1.001, and reading the integer alone reports a
    clean 24.
    """
    if not any(abs(fps - rate) <= _FPS_TOLERANCE for rate in _STANDARD_FRAME_RATES):
        return [Check(
            'WARNING',
            "Scene frame rate is %g fps — engines expect one of %s, and animation "
            "sampled at an odd rate lands with drifting keys"
            % (fps, ", ".join(str(r) for r in _STANDARD_FRAME_RATES)),
        )]
    return [Check('OK', "Scene frame rate is %g fps" % fps)]


def exported_as(object_type):
    """The object_types entry the FBX exporter files this Blender type under."""
    return _FBX_TYPE_OF.get(object_type, 'OTHER')


def check_root_bones(name, root_bone_names):
    """More than one parentless bone confuses every engine importer."""
    if not root_bone_names:
        return [Check('ERROR', "%s: armature has no bones" % name)]
    if len(root_bone_names) > 1:
        return [Check(
            'WARNING',
            "%s: %d root bones (%s) — engines take one as the root and reparent "
            "the rest, usually not the way you meant"
            % (name, len(root_bone_names), ", ".join(sorted(root_bone_names)[:4])),
        )]
    return [Check('OK', "%s: single root bone '%s'" % (name, root_bone_names[0]))]


def check_split_template(split_enabled, template):
    """Splitting without {object} would write every object to one path."""
    if not split_enabled:
        return []
    if "{object}" not in (template or ""):
        return [Check(
            'ERROR',
            "One file per object is on, but the filename template has no {object} — "
            "every object would overwrite the same file",
        )]
    return [Check('OK', "One file per object, named from {object}")]


def check_mesh(name, polygon_count, uv_layer_count):
    """Mesh data problems an engine will reject, or silently shade wrong."""
    checks = []
    if polygon_count == 0:
        checks.append(Check('ERROR', "%s: mesh has no faces — nothing to export" % name))
        return checks

    checks.append(Check('OK', "%s: %d face(s)" % (name, polygon_count)))
    if uv_layer_count == 0:
        checks.append(Check(
            'WARNING', "%s: no UV map — the engine cannot texture this" % name))
    else:
        checks.append(Check('OK', "%s: %d UV map(s)" % (name, uv_layer_count)))
    return checks


def check_rig_facing(name, z_rotation):
    """Report the rig's yaw relative to the forward convention.

    Honest about its limits: this measures the object's yaw, which is the part
    that is actually knowable. Whether the *model* was sculpted facing the wrong
    way cannot be read out of the data — no amount of geometry inspection tells
    you where a character's face is — so that stays a human check.
    """
    if abs(z_rotation) > _ANGLE_TOLERANCE:
        return [Check(
            'WARNING',
            "%s: rig is yawed %.1f° — the engine will import it facing that way. "
            "Rigs should sit unrotated, facing %s."
            % (name, math.degrees(z_rotation), FORWARD_CONVENTION),
        )]
    return [Check(
        'OK',
        "%s: rig unrotated, so it faces %s as the engine presets expect "
        "(whether the model itself was built facing that way is yours to eyeball)"
        % (name, FORWARD_CONVENTION),
    )]


def check_animation(name, has_action, action_name, action_range, scene_range):
    """Animation-preset problems: nothing to bake, or a bake window that clips it."""
    if not has_action:
        return [Check(
            'ERROR',
            "%s: this preset bakes animation but the rig has no action assigned" % name,
        )]

    if not (action_range and scene_range):
        return [Check('OK', "%s: action '%s' assigned" % (name, action_name))]

    a_start, a_end = action_range
    s_start, s_end = scene_range
    if a_start < s_start or a_end > s_end:
        return [Check(
            'WARNING',
            "%s: action '%s' spans %d-%d but the scene range is %d-%d — the bake "
            "uses the scene range, so the clip will be cut"
            % (name, action_name, a_start, a_end, s_start, s_end),
        )]
    return [Check(
        'OK',
        "%s: action '%s' spans %d-%d, inside the scene range %d-%d"
        % (name, action_name, a_start, a_end, s_start, s_end),
    )]


def summarise(checks):
    """Return (errors, warnings, passed) counts for a one-line report."""
    errors = sum(1 for c in checks if c.level == 'ERROR')
    warnings = sum(1 for c in checks if c.level == 'WARNING')
    passed = sum(1 for c in checks if c.level == 'OK')
    return errors, warnings, passed


def sort_for_display(checks):
    """Problems first, then context, then everything that passed."""
    return sorted(checks, key=lambda c: _SEVERITY.get(c.level, 9))


# --------------------------------------------------------------------------- #
# The Blender-facing edge: read values, delegate to the rules above.
# --------------------------------------------------------------------------- #

# Set by the operator, read by the panel.
_last_result = {"checks": [], "project": "", "preset": "", "ran": False}


def last_result():
    return dict(_last_result, checks=list(_last_result["checks"]))


def store_result(project_name, preset_name, checks):
    _last_result["checks"] = list(checks)
    _last_result["project"] = project_name
    _last_result["preset"] = preset_name
    _last_result["ran"] = True


def clear_result():
    _last_result["checks"] = []
    _last_result["project"] = ""
    _last_result["preset"] = ""
    _last_result["ran"] = False


def result_matches(result, project_name, preset_name):
    """True when a stored result describes this project's preset.

    Keyed on names rather than indices on purpose: a preset carries no stable
    identity, and move, remove, duplicate and JSON import all reorder the
    collections, so an index would quietly re-point at a different preset — worse
    than the staleness it was meant to fix, because it would look right.

    The project name is part of the key because projects created from an engine
    template name their presets after the variant: "Static Mesh" exists
    identically under Unity, Unreal and Godot.

    An empty name on either side means there is nothing to compare, and returning
    a mismatch there would be inventing a verdict the data does not support.
    """
    stored_preset = result.get("preset", "")
    if not stored_preset or not preset_name:
        return True

    stored_project = result.get("project", "")
    if stored_project and project_name and stored_project != project_name:
        return False
    return stored_preset == preset_name


def _mesh_counts(context, obj, use_modifiers):
    """(polygon_count, uv_layer_count) as the exporter will actually see them.

    With Apply Modifiers on, the FBX exporter writes the *evaluated* mesh, so
    counting faces on the base mesh reports "no faces — nothing to export" for
    anything whose geometry is generated: a Skin modifier, geometry nodes, a
    mirrored half, a Boolean. Those export perfectly well.

    Falls back to the base mesh if evaluation is unavailable, which is the honest
    answer when the depsgraph cannot be reached rather than a guess.
    """
    mesh = obj.data
    if not use_modifiers:
        return len(mesh.polygons), len(mesh.uv_layers)

    evaluated = None
    try:
        evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
        eval_mesh = evaluated.to_mesh()
    except (AttributeError, RuntimeError):
        return len(mesh.polygons), len(mesh.uv_layers)

    try:
        if eval_mesh is None:
            return len(mesh.polygons), len(mesh.uv_layers)
        return len(eval_mesh.polygons), len(eval_mesh.uv_layers)
    finally:
        # to_mesh() owns a temporary datablock; it has to be released on the same
        # object it came from, on every path out of here.
        try:
            evaluated.to_mesh_clear()
        except (AttributeError, RuntimeError):
            pass


def run(context, project, preset):
    """Validate the current selection against one preset. Returns [Check]."""
    fbx = preset.fbx_settings
    from_selection = bool(fbx.use_selection)
    objects = list(context.selected_objects) if from_selection else list(context.scene.objects)

    if not objects:
        return [Check('ERROR', "Nothing selected to export")]

    types_exported = set(fbx.object_types)
    wants_anim = bool(fbx.bake_anim)
    scene = context.scene
    scene_range = (scene.frame_start, scene.frame_end)

    # State the terms of the check, so a clean result is readable as "these
    # things were examined" rather than an unexplained thumbs up.
    splitting = bool(getattr(preset, "split_per_object", False)) and from_selection
    baking = bool(getattr(preset, "apply_transform_before_export", False)) and from_selection
    checks = [Check(
        'INFO',
        "Checked %d %s against '%s' — exporting %s%s%s"
        % (len(objects),
           "selected object(s)" if from_selection else "scene object(s)",
           preset.name,
           ", ".join(sorted(types_exported)) or "nothing",
           ", animation baked" if wants_anim else "",
           ", one file per object" if splitting else ""),
    )]

    if baking:
        checks.append(Check(
            'OK',
            "Rotation and scale are baked into temporary copies at export — your scene "
            "objects are not modified, and object origins stay where you put them",
        ))

    # Scene-wide settings first: they invalidate every object at once, so seeing
    # them at the top explains any per-object weirdness underneath.
    checks.extend(check_scene_units(scene.unit_settings.scale_length))
    if wants_anim:
        # The effective rate, not the integer field — see check_frame_rate.
        checks.extend(check_frame_rate(scene.render.fps / (scene.render.fps_base or 1.0)))
    checks.extend(check_split_template(splitting, preset.filename_template))

    considered = 0
    for obj in objects:
        if exported_as(obj.type) not in types_exported:
            # Not part of this preset's payload; nothing about it can break the
            # export, and reporting on it buries the objects that can.
            continue
        considered += 1

        if obj.type in _TRANSFORMABLE:
            checks.extend(check_transform(
                obj.name, tuple(obj.scale), tuple(obj.rotation_euler), baked_on_export=baking))

        if obj.type == 'MESH':
            polygons, uv_layers = _mesh_counts(context, obj, bool(fbx.use_mesh_modifiers))
            checks.extend(check_mesh(obj.name, polygons, uv_layers))

        elif obj.type == 'ARMATURE':
            checks.extend(check_rig_facing(obj.name, obj.rotation_euler[2]))
            roots = [b.name for b in obj.data.bones if b.parent is None]
            checks.extend(check_root_bones(obj.name, roots))
            if wants_anim:
                action = getattr(getattr(obj, "animation_data", None), "action", None)
                checks.extend(check_animation(
                    obj.name,
                    action is not None,
                    getattr(action, "name", ""),
                    tuple(int(v) for v in action.frame_range) if action else None,
                    scene_range,
                ))

    if not considered:
        checks.append(Check(
            'WARNING',
            "None of the selected objects match this preset's object types — "
            "the export would be empty",
        ))

    # "In the export set" means both selected *and* covered by object_types — a
    # preset that bakes animation while filtering armatures out has nothing to
    # bake either way, and that is the harder mistake to spot in the UI.
    armature_exported = ('ARMATURE' in types_exported
                         and any(o.type == 'ARMATURE' for o in objects))
    if wants_anim and not armature_exported:
        checks.append(Check(
            'WARNING',
            "This preset bakes animation but no armature is in the export set",
        ))

    return checks
