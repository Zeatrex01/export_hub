"""Property definitions.

Hierarchy:
    Preferences
      └── Project (a target app / destination, e.g. "Unity" or "Unreal")
            └── Export Preset (e.g. "Mesh", "Animation")
                  └── FBX settings + its own folder & filename template
"""

import bpy
from bpy.props import (
    StringProperty,
    BoolProperty,
    FloatProperty,
    IntProperty,
    EnumProperty,
    PointerProperty,
    CollectionProperty,
)

AXIS_ITEMS = [
    ('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", ""),
    ('-X', "-X", ""), ('-Y', "-Y", ""), ('-Z', "-Z", ""),
]

# Every property on EXH_FBXSettings that maps 1:1 to a bpy.ops.export_scene.fbx() argument.
# Used both to build the export call and to serialise settings to/from JSON.
FBX_SETTING_KEYS = [
    # Include
    "use_selection", "use_visible", "use_active_collection",
    "object_types", "use_custom_props",
    # Transform
    "global_scale", "apply_unit_scale", "apply_scale_options",
    "axis_forward", "axis_up", "use_space_transform", "bake_space_transform",
    # Geometry
    "mesh_smooth_type", "use_subsurf", "use_mesh_modifiers", "use_mesh_edges",
    "use_tspace", "use_triangles", "colors_type",
    # Armature
    "primary_bone_axis", "secondary_bone_axis", "armature_nodetype",
    "use_armature_deform_only", "add_leaf_bones",
    # Animation
    "bake_anim", "bake_anim_use_all_bones", "bake_anim_use_nla_strips",
    "bake_anim_use_all_actions", "bake_anim_force_startend_keying",
    "bake_anim_step", "bake_anim_simplify_factor",
    # Extras
    "path_mode", "embed_textures",
]

# Fields on EXH_ExportPreset (besides fbx_settings) persisted to JSON.
PRESET_KEYS = [
    "name", "export_dir", "filename_template", "version",
    "auto_increment_version", "apply_transform_before_export",
    "open_folder_after_export", "split_per_object", "overwrite_mode",
]


class EXH_FBXSettings(bpy.types.PropertyGroup):
    """Mirror of Blender's FBX exporter options, stored per export preset."""

    # --- Include ---
    use_selection: BoolProperty(name="Selected Objects", default=True)
    use_visible: BoolProperty(name="Visible Objects", default=False)
    use_active_collection: BoolProperty(name="Active Collection", default=False)
    object_types: EnumProperty(
        name="Object Types", options={'ENUM_FLAG'},
        items=[
            ('EMPTY', "Empty", ""), ('CAMERA', "Camera", ""), ('LIGHT', "Light", ""),
            ('ARMATURE', "Armature", ""), ('MESH', "Mesh", ""), ('OTHER', "Other", ""),
        ],
        default={'EMPTY', 'CAMERA', 'LIGHT', 'ARMATURE', 'MESH', 'OTHER'},
    )
    use_custom_props: BoolProperty(name="Custom Properties", default=False)

    # --- Transform ---
    global_scale: FloatProperty(name="Scale", default=1.0, min=0.001, max=1000.0)
    apply_unit_scale: BoolProperty(name="Apply Unit", default=True)
    apply_scale_options: EnumProperty(
        name="Apply Scalings",
        items=[
            ('FBX_SCALE_NONE', "All Local", ""),
            ('FBX_SCALE_UNITS', "FBX Units Scale", ""),
            ('FBX_SCALE_CUSTOM', "FBX Custom Scale", ""),
            ('FBX_SCALE_ALL', "FBX All", ""),
        ],
        default='FBX_SCALE_NONE',
    )
    axis_forward: EnumProperty(name="Forward", items=AXIS_ITEMS, default='-Z')
    axis_up: EnumProperty(name="Up", items=AXIS_ITEMS, default='Y')
    use_space_transform: BoolProperty(name="Use Space Transform", default=True)
    bake_space_transform: BoolProperty(name="Apply Transform", default=False)

    # --- Geometry ---
    mesh_smooth_type: EnumProperty(
        name="Smoothing",
        items=[('OFF', "Normals Only", ""), ('FACE', "Face", ""), ('EDGE', "Edge", "")],
        default='OFF',
    )
    use_subsurf: BoolProperty(name="Export Subdivision Surface", default=False)
    use_mesh_modifiers: BoolProperty(name="Apply Modifiers", default=True)
    use_mesh_edges: BoolProperty(name="Loose Edges", default=False)
    use_tspace: BoolProperty(name="Tangent Space", default=False)
    use_triangles: BoolProperty(name="Triangulate Faces", default=False)
    colors_type: EnumProperty(
        name="Vertex Colors",
        items=[('NONE', "None", ""), ('SRGB', "sRGB", ""), ('LINEAR', "Linear", "")],
        default='SRGB',
    )

    # --- Armature ---
    primary_bone_axis: EnumProperty(name="Primary Bone Axis", items=AXIS_ITEMS, default='Y')
    secondary_bone_axis: EnumProperty(name="Secondary Bone Axis", items=AXIS_ITEMS, default='X')
    armature_nodetype: EnumProperty(
        name="Armature FBXNode Type",
        items=[('NULL', "Null", ""), ('ROOT', "Root", ""), ('LIMBNODE', "LimbNode", "")],
        default='NULL',
    )
    use_armature_deform_only: BoolProperty(name="Only Deform Bones", default=False)
    add_leaf_bones: BoolProperty(name="Add Leaf Bones", default=False)

    # --- Animation ---
    bake_anim: BoolProperty(name="Baked Animation", default=True)
    bake_anim_use_all_bones: BoolProperty(name="Key All Bones", default=True)
    bake_anim_use_nla_strips: BoolProperty(name="NLA Strips", default=True)
    bake_anim_use_all_actions: BoolProperty(name="All Actions", default=True)
    bake_anim_force_startend_keying: BoolProperty(name="Force Start/End Keying", default=True)
    bake_anim_step: FloatProperty(name="Sampling Rate", default=1.0, min=0.01, max=100.0)
    bake_anim_simplify_factor: FloatProperty(name="Simplify", default=1.0, min=0.0, max=100.0)

    # --- Extras ---
    path_mode: EnumProperty(
        name="Path Mode",
        items=[
            ('AUTO', "Auto", ""), ('ABSOLUTE', "Absolute", ""), ('RELATIVE', "Relative", ""),
            ('MATCH', "Match", ""), ('STRIP', "Strip Path", ""), ('COPY', "Copy", ""),
        ],
        default='AUTO',
    )
    embed_textures: BoolProperty(name="Embed Textures", default=False)


class EXH_ExportPreset(bpy.types.PropertyGroup):
    """One export configuration within a project (e.g. "Mesh" or "Animation")."""

    name: StringProperty(name="Preset Name", default="New Preset")
    enabled: BoolProperty(
        name="Include in 'Export All'", default=True,
        description="When off, this preset is skipped by the Export All button",
    )
    export_dir: StringProperty(name="Export Folder", subtype='DIR_PATH', default="")
    filename_template: StringProperty(
        name="Filename Template",
        default="{blend}",
        description=(
            "Output name without extension. Tokens: {project} {preset} {blend} "
            "{object} {collection} {scene} {date} {time} {version}"
        ),
    )
    split_per_object: BoolProperty(
        name="One file per object",
        default=False,
        description=(
            "Export each selected object to its own FBX instead of one combined file. "
            "The filename template must contain {object}, otherwise every object would "
            "be written to the same path"
        ),
    )
    overwrite_mode: EnumProperty(
        name="If the file exists",
        items=[
            ('OVERWRITE', "Overwrite",
             "Replace the existing file. This is what the add-on has always done"),
            ('INCREMENT', "Keep both",
             "Leave the existing file and write to the next free numbered name: "
             "Chair.fbx, then Chair_001.fbx, Chair_002.fbx"),
            ('SKIP', "Skip",
             "Write nothing and report it, leaving the file on disk untouched"),
        ],
        default='OVERWRITE',
        description=(
            "What to do when the resolved filename is already on disk. The default "
            "overwrites, so existing presets keep behaving exactly as before"
        ),
    )
    version: IntProperty(name="Version", default=1, min=0)
    auto_increment_version: BoolProperty(
        name="Auto-increment version after export",
        default=False,
        description="Bump the version number by one on every successful export",
    )
    apply_transform_before_export: BoolProperty(
        name="Bake rotation & scale",
        default=False,
        description=(
            "Apply rotation and scale for the exported file, on temporary copies that are "
            "deleted afterwards — the objects in your scene are never modified. Location is "
            "deliberately left alone: applying it would move each object's origin to the "
            "world origin, so the engine would rotate the asset around a point away from "
            "its geometry. Requires the Selected Objects export mode"
        ),
    )
    open_folder_after_export: BoolProperty(name="Open folder after export", default=False)
    fbx_settings: PointerProperty(type=EXH_FBXSettings)


class EXH_Project(bpy.types.PropertyGroup):
    """A destination that groups one or more export presets."""

    name: StringProperty(name="Project Name", default="New Project")
    presets: CollectionProperty(type=EXH_ExportPreset)
    active_preset_index: IntProperty(default=0)


class EXH_HistoryEntry(bpy.types.PropertyGroup):
    """A record of one past export, re-runnable from the panel."""

    name: StringProperty(default="")          # == filename, used by the UIList
    filepath: StringProperty(default="")      # full absolute path written
    project_name: StringProperty(default="")
    preset_name: StringProperty(default="")
    timestamp: StringProperty(default="")
    fbx_json: StringProperty(default="")      # snapshot of the FBX kwargs used


def save_preferences():
    """Write this add-on's preferences to disk. Returns True on success.

    Blender only persists userpref.blend by itself when "Auto-Save Preferences"
    is enabled, and plenty of users have it off. Without this call every project,
    preset and history entry silently disappears when Blender closes.

    Lives here rather than in config.py because config.py imports from this
    module; putting persistence next to the data it persists also keeps the
    dependency direction one-way.
    """
    try:
        bpy.ops.wm.save_userpref()
    except RuntimeError:
        return False
    return True


# Blender keeps pointers to the strings an items callback hands back, so the
# returned sequence has to stay referenced module-side. A fresh tuple is built
# and stored on every call — the previous one is replaced, never mutated in
# place, because clearing it would free strings the UI is still drawing.
_project_enum_cache = ()


def _project_enum_items(self, context):
    global _project_enum_cache
    items = [(str(i), p.name or "Project %d" % i, "") for i, p in enumerate(self.projects)]
    if not items:
        items = [("-1", "(no projects yet)", "")]
    _project_enum_cache = tuple(items)
    return _project_enum_cache


# The dropdown is a *view* of active_project_index, not a second place the
# selection is stored. Deriving it through get/set is what makes the two
# impossible to disagree: every operator that moves the index moves the dropdown
# with it, for free.
def _project_enum_get(self):
    count = len(self.projects)
    if not count:
        return 0
    return min(max(self.active_project_index, 0), count - 1)


def _project_enum_set(self, value):
    if 0 <= value < len(self.projects):
        self.active_project_index = value


class EXH_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    projects: CollectionProperty(type=EXH_Project)
    active_project_index: IntProperty(default=0)
    active_project_enum: EnumProperty(
        name="Project",
        items=_project_enum_items,
        get=_project_enum_get,
        set=_project_enum_set,
    )
    history: CollectionProperty(type=EXH_HistoryEntry)
    active_history_index: IntProperty(default=0)

    show_passed_checks: BoolProperty(
        name="Show passed checks",
        default=True,
        description="List the checks that passed, not only the problems",
    )
    check_updates: BoolProperty(
        name="Check for updates",
        default=True,
        description=(
            "Ask GitHub once a day whether a newer release of this add-on exists. "
            "Turn off to stop the add-on contacting the network entirely"
        ),
    )
    last_update_check: StringProperty(default="")  # ISO date, throttles to once a day

    def draw(self, context):
        # Real drawing lives in ui.py to keep this module data-only.
        from . import ui
        ui.draw_preferences(self, context)


classes = (
    EXH_FBXSettings,
    EXH_ExportPreset,
    EXH_Project,
    EXH_HistoryEntry,
    EXH_Preferences,
)
