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

try:  # the rules below are plain Python; only run() and its helpers need Blender
    import bpy
except ImportError:  # pragma: no cover
    bpy = None

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


def check_transform(name, scale, rotation_euler, baked_on_export=False, own_mirror=None,
                    parent_mirror=False):
    """Unapplied transforms on an object about to be exported.

    `scale` and `rotation_euler` are the object's own transform as the engine
    will receive it (run() decomposes the object's basis matrix, so quaternion
    and axis-angle rotation modes and delta transforms count too).

    Mirroring is a sign of the transform's determinant, not of any one scale
    component: (-1, -1, 1) is a 180° turn, not a mirror. `own_mirror` says this
    object's own transform mirrors (derived from `scale` when left out);
    `parent_mirror` says a parent mirrors it.

    `baked_on_export` says the preset will apply rotation and scale to a
    temporary copy. Then an unapplied scale is not a problem to fix, and a
    mirroring scale of the object's own is baked too: Blender keeps the faces
    pointing outward when it applies a negative scale. A parent's mirror is not
    baked, because only the object's own transform is applied.
    """
    checks = []
    sx, sy, sz = scale
    if own_mirror is None:
        own_mirror = sx * sy * sz < 0.0
    magnitudes = (abs(sx), abs(sy), abs(sz))

    if parent_mirror and baked_on_export:
        checks.append(Check(
            'ERROR',
            "%s: mirrored by a parent's negative scale — baking applies only this "
            "object's own rotation and scale, so the faces will be inside out in "
            "the engine. Apply scale on the parent." % name,
        ))
    elif own_mirror != parent_mirror and not baked_on_export:
        checks.append(Check(
            'ERROR',
            "%s: negative scale (%.3f, %.3f, %.3f)%s — faces will be inside out in "
            "the engine. Apply scale (Ctrl+A), then Mesh > Normals > Recalculate "
            "Outside if any face still looks inverted."
            % (name, sx, sy, sz, " mirrored by a parent" if parent_mirror else ""),
        ))
    elif own_mirror and baked_on_export:
        checks.append(Check(
            'OK',
            "%s: mirroring scale (%.3f, %.3f, %.3f) — baked into a temporary copy at "
            "export; Blender keeps the faces pointing outward" % (name, sx, sy, sz),
        ))
    elif any(s < 0.0 for s in scale) and not own_mirror:
        checks.append(Check(
            'OK' if baked_on_export else 'WARNING',
            "%s: scale (%.3f, %.3f, %.3f) is a 180° turn, not a mirror%s"
            % (name, sx, sy, sz, " — baked into a temporary copy at export"
               if baked_on_export else ", and it is not applied — Ctrl+A > Rotation & Scale"),
        ))
    elif any(abs(m - 1.0) > _SCALE_TOLERANCE for m in magnitudes):
        uniform = abs(max(magnitudes) - min(magnitudes)) <= _SCALE_TOLERANCE
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


def check_baked_animated_armature(name, scale, animated, baked_on_export):
    """Baking scale into an animated armature breaks its animation.

    transform_apply rescales the rest pose but not the pose-bone location keys,
    so an armature with scale 2 and animated bones drifts away from its own mesh
    (measured in Blender 5.2: 1 m off after a 1 m move). Export refuses this; the
    validator says so beforehand.
    """
    if not (baked_on_export and animated):
        return []
    if any(abs(abs(s) - 1.0) > _SCALE_TOLERANCE for s in scale):
        return [Check(
            'ERROR',
            "%s: animated armature with scale (%.3f, %.3f, %.3f) — baking would "
            "rescale its rest pose but not its keys, so the animation would drift. "
            "Apply scale before animating, or turn baking off for this preset; the "
            "export refuses it." % ((name,) + tuple(scale)),
        )]
    return []


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


def check_split_skin(mesh_name, armature_names):
    """One file per object writes a skinned mesh without the armature that deforms it."""
    if not armature_names:
        return []
    return [Check(
        'WARNING',
        "%s: deformed by %s, but one file per object writes them to separate files — "
        "the engine gets the mesh unskinned. Turn splitting off for skinned characters"
        % (mesh_name, ", ".join(sorted(armature_names))),
    )]


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


def check_animation(name, clips, scene_range=None, scene_range_mode=False, unslotted_action=None,
                    modes=""):
    """Animation-preset problems, judged by what the FBX exporter will write.

    `clips` is [(label, start, end)] the exporter will bake for this rig: one per
    NLA strip with NLA Strips on, one per fitting action (over the action's own
    frame range) with All Actions on, or, with both off, the assigned action over
    the scene range (`scene_range_mode`). `unslotted_action` names an assigned
    action without a slot (Blender 4.4+): the exporter skips it.
    """
    checks = []
    if unslotted_action:
        checks.append(Check(
            'WARNING' if clips else 'ERROR',
            "%s: action '%s' is assigned without a slot, so the exporter skips it — "
            "pick its slot in the Action editor" % (name, unslotted_action),
        ))
    if not clips:
        if not unslotted_action:
            checks.append(Check(
                'ERROR',
                "%s: this preset bakes animation but nothing would be exported for "
                "this rig (%s)" % (name, modes or "no action assigned"),
            ))
        return checks

    if scene_range_mode and scene_range:
        label, a_start, a_end = clips[0]
        s_start, s_end = scene_range
        if a_start < s_start or a_end > s_end:
            checks.append(Check(
                'WARNING',
                "%s: action '%s' spans %g-%g but the scene range is %g-%g — with NLA "
                "Strips and All Actions off the bake uses the scene range, so the "
                "clip will be cut" % (name, label, a_start, a_end, s_start, s_end),
            ))
        else:
            checks.append(Check(
                'OK',
                "%s: action '%s' spans %g-%g, inside the scene range %g-%g"
                % (name, label, a_start, a_end, s_start, s_end),
            ))
        return checks

    shown = ", ".join("%s (%g-%g)" % c for c in clips[:6])
    if len(clips) > 6:
        shown += " and %d more" % (len(clips) - 6)
    checks.append(Check(
        'OK', "%s: %d clip(s) will be exported, each over its own range: %s"
        % (name, len(clips), shown)))
    return checks


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


def _export_scope(context, fbx):
    """The objects the exporter will consider: selection (or the scene), narrowed by
    Visible Objects and Active Collection the same way the exporter narrows them."""
    objects = list(context.selected_objects) if fbx.use_selection else list(context.scene.objects)
    if getattr(fbx, "use_visible", False):
        objects = [o for o in objects if o.visible_get()]
    if getattr(fbx, "use_active_collection", False):
        collection = context.view_layer.active_layer_collection.collection
        members = set(collection.all_objects)
        objects = [o for o in objects if o in members]
    return objects


def _own_transform(obj):
    """(scale, euler rotation, own mirror, parent mirror) as the engine receives the
    object: from the basis matrix (rotation mode and delta transforms included), with
    mirroring read from determinants rather than from scale signs."""
    _loc, rotation, scale = obj.matrix_basis.decompose()
    own_mirror = obj.matrix_basis.determinant() < 0.0
    world_mirror = obj.matrix_world.determinant() < 0.0
    return tuple(scale), tuple(rotation.to_euler('XYZ')), own_mirror, world_mirror != own_mirror


def _exported_root_bones(armature, deform_only):
    """Root bones as the exporter writes them: with Only Deform Bones it keeps deform
    bones and the bones above them, and drops the rest (IK targets, poles, controls)."""
    bones = armature.data.bones
    if deform_only:
        kept = set()
        for bone in bones:
            if bone.use_deform:
                b = bone
                while b is not None:
                    kept.add(b.name)
                    b = b.parent
    else:
        kept = {b.name for b in bones}
    return [b.name for b in bones if b.name in kept and (b.parent is None or b.parent.name not in kept)]


def _action_fits(action, obj):
    """The exporter's All Actions test: an action fits when every F-curve of one of its
    slots resolves on the object (layered actions, Blender 4.4+), or every F-curve of a
    legacy action does."""
    for layer in getattr(action, "layers", ()):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", ()):
                if not bag.fcurves:
                    continue
                try:
                    for fc in bag.fcurves:
                        obj.path_resolve(fc.data_path if not fc.array_index
                                         else "%s[%d]" % (fc.data_path, fc.array_index))
                except ValueError:
                    continue
                return True
    if getattr(action, "layers", None):
        return False
    curves = list(getattr(action, "fcurves", ()))
    if not curves:
        return False
    try:
        for fc in curves:
            obj.path_resolve(fc.data_path if not fc.array_index
                             else "%s[%d]" % (fc.data_path, fc.array_index))
    except ValueError:
        return False
    return True


def _animation_clips(obj, fbx, scene_range):
    """(clips, unslotted action name, scene-range mode, modes text) for one rig, the way
    the FBX exporter picks its animation stacks."""
    ad = getattr(obj, "animation_data", None)
    action = getattr(ad, "action", None)
    has_slots = ad is not None and hasattr(ad, "action_slot")
    unslotted = action.name if (action is not None and has_slots and ad.action_slot is None) else None
    nla_on = bool(getattr(fbx, "bake_anim_use_nla_strips", False))
    all_on = bool(getattr(fbx, "bake_anim_use_all_actions", False))
    clips = []
    if ad is not None and nla_on:
        for track in ad.nla_tracks:
            if track.mute:
                continue
            for strip in track.strips:
                if not strip.mute:
                    clips.append((strip.name, strip.frame_start, strip.frame_end))
    if ad is not None and all_on:
        for act in bpy.data.actions:
            if act == action:
                if unslotted:
                    continue
            elif not _action_fits(act, obj):
                continue
            clips.append((act.name, act.frame_range[0], act.frame_range[1]))
    scene_mode = not nla_on and not all_on
    if scene_mode and action is not None and not unslotted:
        clips.append((action.name, action.frame_range[0], action.frame_range[1]))
    modes = ", ".join(m for m, on in (("NLA strips", nla_on), ("all actions", all_on)) if on)
    modes = ("no action assigned" if scene_mode else
             "no %s fit this rig" % modes)
    return clips, unslotted, scene_mode, modes


def run(context, project, preset):
    """Validate the current selection against one preset. Returns [Check]."""
    fbx = preset.fbx_settings
    from_selection = bool(fbx.use_selection)
    objects = _export_scope(context, fbx)

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
            scale, rotation, own_mirror, parent_mirror = _own_transform(obj)
            checks.extend(check_transform(obj.name, scale, rotation, baked_on_export=baking,
                                          own_mirror=own_mirror, parent_mirror=parent_mirror))

        if obj.type == 'MESH':
            polygons, uv_layers = _mesh_counts(context, obj, bool(fbx.use_mesh_modifiers))
            checks.extend(check_mesh(obj.name, polygons, uv_layers))
            if splitting and 'ARMATURE' in types_exported:
                rigs = {m.object.name for m in obj.modifiers
                        if m.type == 'ARMATURE' and m.object is not None and m.object in objects}
                checks.extend(check_split_skin(obj.name, rigs))

        elif obj.type == 'ARMATURE':
            scale, rotation, _own, _parent = _own_transform(obj)
            checks.extend(check_rig_facing(obj.name, rotation[2]))
            roots = _exported_root_bones(obj, bool(getattr(fbx, "use_armature_deform_only", False)))
            checks.extend(check_root_bones(obj.name, roots))
            clips = []
            if wants_anim:
                clips, unslotted, scene_mode, modes = _animation_clips(obj, fbx, scene_range)
                checks.extend(check_animation(obj.name, clips, scene_range, scene_mode, unslotted, modes))
            animated = bool(clips) or bool(getattr(getattr(obj, "animation_data", None), "action", None))
            checks.extend(check_baked_animated_armature(obj.name, scale, animated, baking))

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
