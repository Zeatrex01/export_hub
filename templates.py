"""Built-in export templates for common game engines.

Pure data plus lookup helpers: no bpy import, no UI code, no operator logic.
Adding an engine or a variant means adding one entry to TEMPLATES and nothing
else -- the operator, the menu and the enum items all derive from this table.

Why variants instead of one template per engine
-----------------------------------------------
`bake_space_transform` ("Apply Transform") is the single setting that decides
whether a model lands upright in the engine. It is reliable for static meshes
but is known to break armatures and parenting relationships, so a skeletal or
animation export must leave it off. One template per engine cannot express
that, so every engine ships three variants instead.

Values marked VERIFY in `notes` are the ones that legitimately differ between
pipelines (unit scale in particular); they are sensible defaults, not laws.
"""

from collections import namedtuple

# id       stable key used by the operator enum and by saved configs
# engine   grouping label for the menu
# variant  short name shown to the user
# summary  one-line tooltip
# settings partial FBX settings; merged over _BASE
# notes    caveats worth surfacing in the UI/tooltip, or "" for none
Template = namedtuple("Template", "id engine variant summary settings notes")

# Settings every engine template agrees on. Anything an engine needs to differ
# on is overridden in its own entry, so the diffs below stay readable.
_BASE = {
    "use_selection": True,
    "use_visible": False,
    "use_active_collection": False,
    "use_custom_props": False,
    "global_scale": 1.0,
    "apply_unit_scale": True,
    # FBX standard orientation. Unity, Unreal and Godot all read Y-up FBX and
    # run their own conversion on import, so this is the safe baseline.
    "axis_forward": "-Z",
    "axis_up": "Y",
    "use_space_transform": True,
    "bake_space_transform": False,
    # Engines want smoothing groups; "Normals Only" triggers import warnings.
    "mesh_smooth_type": "FACE",
    "use_mesh_modifiers": True,
    "use_subsurf": False,
    "use_mesh_edges": False,
    "use_triangles": False,
    # Leaf bones are Blender-only padding; they show up as junk "_end" bones in
    # every engine below and break Unity's humanoid mapping.
    "add_leaf_bones": False,
    "primary_bone_axis": "Y",
    "secondary_bone_axis": "X",
    "armature_nodetype": "NULL",
    "use_armature_deform_only": True,
    "bake_anim": False,
    "path_mode": "AUTO",
    "embed_textures": False,
}

_STATIC_TYPES = {"MESH", "EMPTY", "OTHER"}
_SKELETAL_TYPES = {"MESH", "ARMATURE"}
_ANIM_TYPES = {"ARMATURE"}

# Animation variants share this block; only object_types differs per engine.
_ANIM_SETTINGS = {
    "object_types": _ANIM_TYPES,
    "bake_anim": True,
    "bake_anim_use_all_bones": True,
    "bake_anim_use_all_actions": True,
    # NLA strips on top of "all actions" is the usual cause of duplicated or
    # doubled-up clips in the engine, so it stays off here.
    "bake_anim_use_nla_strips": False,
    "bake_anim_force_startend_keying": True,
    "bake_anim_step": 1.0,
    "bake_anim_simplify_factor": 1.0,
    "use_mesh_modifiers": False,
}


def _merge(*layers):
    """Left-to-right merge of setting dicts into a new dict."""
    out = dict(_BASE)
    for layer in layers:
        out.update(layer)
    return out


TEMPLATES = (
    # ----------------------------------------------------------------- Unity
    Template(
        id="unity_static",
        engine="Unity",
        variant="Static Mesh",
        summary="Props and environment meshes, no armature",
        settings=_merge({
            "object_types": _STATIC_TYPES,
            # Unity applies a -89.98 deg X rotation to plain Y-up FBX. Baking
            # the space transform cancels it, and is safe here precisely
            # because there is no armature to break.
            "bake_space_transform": True,
            "apply_scale_options": "FBX_SCALE_UNITS",
            "use_tspace": True,
        }),
        notes="",
    ),
    Template(
        id="unity_skeletal",
        engine="Unity",
        variant="Skeletal Mesh",
        summary="Rigged character mesh with its armature, no animation baked",
        settings=_merge({
            "object_types": _SKELETAL_TYPES,
            # Deliberately off: baking the transform breaks armatures.
            "bake_space_transform": False,
            "apply_scale_options": "FBX_SCALE_UNITS",
            "use_tspace": True,
        }),
        notes="Apply Transform stays off for rigs. If the character lands "
              "rotated in Unity, enable Bake Axis Conversion on the model "
              "import settings rather than turning it on here.",
    ),
    Template(
        id="unity_animation",
        engine="Unity",
        variant="Animation",
        summary="Armature and actions only, for a separate animation clip file",
        settings=_merge(_ANIM_SETTINGS, {
            "apply_scale_options": "FBX_SCALE_UNITS",
            "bake_space_transform": False,
        }),
        notes="Exports the armature without mesh data. Pair it with a "
              "Skeletal Mesh export of the same rig.",
    ),
    # ---------------------------------------------------------------- Unreal
    Template(
        id="unreal_static",
        engine="Unreal",
        variant="Static Mesh",
        summary="Props and environment meshes, no armature",
        settings=_merge({
            "object_types": _STATIC_TYPES,
            "apply_scale_options": "FBX_SCALE_NONE",
            "use_tspace": True,
        }),
        notes="VERIFY: Unreal works in centimetres (1 uu = 1 cm) while Blender "
              "works in metres. This exports at scale 1.0; set Import Uniform "
              "Scale to 100 in Unreal, or author your scene in centimetres.",
    ),
    Template(
        id="unreal_skeletal",
        engine="Unreal",
        variant="Skeletal Mesh",
        summary="Rigged character mesh with its armature, no animation baked",
        settings=_merge({
            "object_types": _SKELETAL_TYPES,
            "apply_scale_options": "FBX_SCALE_NONE",
            "use_tspace": True,
        }),
        notes="Name your armature 'root' before exporting, otherwise Unreal "
              "turns the 'Armature' object itself into a bone and the scale "
              "comes in wrong.",
    ),
    Template(
        id="unreal_animation",
        engine="Unreal",
        variant="Animation",
        summary="Armature and actions only, for a separate animation asset",
        settings=_merge(_ANIM_SETTINGS, {
            "apply_scale_options": "FBX_SCALE_NONE",
        }),
        notes="Import against the existing skeleton in Unreal rather than "
              "letting it create a new one.",
    ),
    # ----------------------------------------------------------------- Godot
    Template(
        id="godot_static",
        engine="Godot",
        variant="Static Mesh",
        summary="Props and environment meshes, no armature",
        settings=_merge({
            "object_types": _STATIC_TYPES,
            "apply_scale_options": "FBX_SCALE_UNITS",
            "use_tspace": True,
        }),
        notes="",
    ),
    Template(
        id="godot_skeletal",
        engine="Godot",
        variant="Skeletal Mesh",
        summary="Rigged character mesh with its armature, no animation baked",
        settings=_merge({
            "object_types": _SKELETAL_TYPES,
            "apply_scale_options": "FBX_SCALE_UNITS",
            "use_tspace": True,
        }),
        notes="Only deform bones are exported; Godot shades blend shapes "
              "incorrectly when non-deforming bones come along.",
    ),
    Template(
        id="godot_animation",
        engine="Godot",
        variant="Animation",
        summary="Armature and actions only, for a separate animation file",
        settings=_merge(_ANIM_SETTINGS, {
            "apply_scale_options": "FBX_SCALE_UNITS",
        }),
        notes="",
    ),
)

# Engine order for menus, derived from the table so it can never drift out of
# sync with it.
ENGINES = tuple(dict.fromkeys(t.engine for t in TEMPLATES))

_BY_ID = {t.id: t for t in TEMPLATES}

# Built once at import time and never mutated. Blender needs the strings backing
# a dynamic EnumProperty to stay alive, and a module-level constant guarantees
# that far more simply than a regenerated cache would.
ENUM_ITEMS = tuple(
    (t.id, "%s - %s" % (t.engine, t.variant), t.summary) for t in TEMPLATES
)

ENGINE_ENUM_ITEMS = tuple(
    (engine, engine, "Create a project preconfigured for %s" % engine)
    for engine in ENGINES
)


def get(template_id):
    """Return the Template with this id, or None if it is unknown."""
    return _BY_ID.get(template_id)


def for_engine(engine):
    """Return every template belonging to one engine, in table order."""
    return tuple(t for t in TEMPLATES if t.engine == engine)


def apply_to(fbx, template):
    """Write a template's settings onto an FBX settings property group.

    Unknown keys are skipped so a config written by a newer version of the
    add-on cannot break an older one.
    """
    for key, value in template.settings.items():
        if not hasattr(fbx, key):
            continue
        try:
            setattr(fbx, key, value)
        except (TypeError, ValueError):
            pass
