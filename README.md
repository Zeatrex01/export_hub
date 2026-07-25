# Export Hub

A Blender add-on for people who export the same assets to the same folders over and over.

Configure a destination once — the folder, the FBX settings, the naming convention — then
export with one button from the 3D viewport. No reopening the FBX dialog, no re-checking the
same boxes, no exporting a character with your prop settings by accident.

---

## The problem it solves

Blender's FBX exporter is a modal dialog with no memory. Every export means walking the same
options again, and every project wants different ones: your Unity props need Apply Transform
on, your rigged characters need it off, and your animation files should not carry mesh data at
all. Getting one of those wrong is silent — you find out in the engine.

Export Hub stores those decisions as **presets** grouped under **projects**, and exports from
the sidebar.

```
Project "Unity"                 Project "Unreal"
├── Static Mesh   → /Props      ├── Static Mesh   → /Content/Props
├── Skeletal Mesh → /Chars      ├── Skeletal Mesh → /Content/Chars
└── Animation     → /Anims      └── Animation     → /Content/Anims
```

## Features

- **Projects and presets** — group any number of export configurations per destination.
- **Full FBX control** — every option from Blender's exporter, saved per preset.
- **Built-in engine templates** — ready-made settings for Unity, Unreal and Godot.
- **Filename templates** — build output names from tokens like `{blend}`, `{object}`, `{date}`.
- **Export All** — run every enabled preset in a project in one click.
- **Export history** — the last 50 exports, each re-runnable with the exact settings used.
- **Shareable config** — export projects and presets to JSON, import them on another machine.
- **Auto-versioning** — optional version counter that bumps on every successful export.

## Installation

1. Download `export_hub-<version>.zip` from the releases, or build it yourself with
   `package.bat`.
2. In Blender: **Edit → Preferences → Add-ons → Install...**, pick the zip, enable it.
3. The panel appears in the 3D viewport sidebar (press <kbd>N</kbd>) under the **Export** tab.

## Quick start

**Fastest path — start from an engine.** In the sidebar, use **Start from an Engine** (or the
`+` menu in Preferences) and pick Unity, Unreal or Godot. You get a project with three presets
already configured. Set an export folder on each and you are done.

**Manual path.** Open **Preferences → Add-ons → Export Hub**, add a project, add a preset,
point it at a folder, and adjust the FBX settings underneath.

Then: select your objects in the viewport and press **Export**.

## Filename templates

The output name is built from tokens, so exports stay consistently named without typing.

| Token | Expands to |
|---|---|
| `{project}` | Project name |
| `{preset}` | Preset name |
| `{blend}` | .blend file name |
| `{object}` | Active object name |
| `{collection}` | Active collection name |
| `{scene}` | Scene name |
| `{date}` | `2026-07-25` |
| `{time}` | `18-30-00` |
| `{version}` | `v001`, from the preset's version counter |

`{blend}_{preset}` gives `Character_Skeletal Mesh.fbx`. The panel shows a live preview of the
resolved name before you export. Characters that are illegal in filenames are replaced
automatically.

## Engine templates

Each engine ships three variants rather than one preset, because a single set of options
cannot serve both a static prop and a rigged character:

| | Static Mesh | Skeletal Mesh | Animation |
|---|---|---|---|
| Exports | mesh, empties | mesh + armature | armature only |
| Apply Transform | on | **off** | **off** |
| Baked animation | off | off | on, all actions |

**Why Apply Transform differs.** Blender is Z-up, the engines are Y-up. Baking the space
transform cancels the rotation offset for static meshes, but it breaks armatures and parenting
relationships — so any variant carrying a rig leaves it off. If a character lands rotated in
Unity, fix it with *Bake Axis Conversion* on the model's import settings, not by turning this
on. Applying a template surfaces its caveats as a warning in Blender's status bar.

Templates are starting points, not locks: applying one writes the values onto your preset and
leaves. Every setting stays editable afterwards, and the export folder and filename template
are never touched.

## Sharing configuration

**Preferences → Export Config to JSON** writes every project and preset to a file. Import it
on another machine, or hand it to a teammate, with *Replace all* or *Append*. Exported JSON
carries the actual values, so it stays valid even if the built-in templates change later.

## Compatibility

- **Blender 3.6 and newer**, including 4.x. The version in `bl_info` is a minimum, not a
  ceiling. FBX options are filtered against the running Blender's actual exporter signature,
  so a version that adds or retires an option does not break the export — anything skipped is
  named on the system console.
- Requires Blender's bundled **FBX format** add-on to be enabled (it is, by default).
- Windows, macOS and Linux. `package.bat` is Windows-only; on other platforms zip the
  `export_hub` folder yourself, keeping the folder at the archive root.

## Building the zip

Run `package.bat`. It reads the version from `bl_info`, stages only the add-on's own modules —
a whitelist, so local notes and tooling can never leak into a release — and writes
`build/export_hub-<version>.zip` with the package folder at the archive root, which is the
layout Blender's installer expects. It prints the archive contents so you can see exactly what
shipped.

## Known limitations

- Fields you type into directly (export folder, filename template) are written to disk on your
  next export or button press. Use **Save Settings** in Preferences to write them immediately.
- *Apply transforms before export* modifies your scene and does not undo it afterwards.
- Re-exporting from history writes to that entry's original path, so `{date}` and `{version}`
  tokens are not re-resolved — it overwrites the original file rather than producing a new one.
- Export All refuses to run if two presets resolve to the same output path, rather than
  letting one silently overwrite the other. Add `{preset}` to the filename template to
  separate them; projects created from an engine template already do.
- Exporting to a `//` relative folder requires the .blend to be saved first, since there is
  nothing to resolve the path against otherwise.
