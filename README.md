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
- **Validate before export** — catch unapplied transforms, missing UVs, mirrored objects
  and clipped animation ranges before they reach the engine.
- **One file per object** — optionally split the selection so every object exports separately.
- **Your call on existing files** — per preset: overwrite, keep both, or skip.
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

## Two ways to export

**From the sidebar** — the fastest path once a project is set up: pick a preset, press Export.

**From File → Export → Export Hub (.fbx)** — the same export, reachable where Blender users
already look for exporting. The dialog lets you pick the project and preset, run a single preset
or every enabled one in the project, and shows the folder and resolved filename before you commit.

The dialog also has an **Override folder** switch for sending one export somewhere else without
disturbing the preset's saved folder — useful for a quick hand-off without editing your setup.

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

## Validate

**Validate** checks the current selection against the active preset and lists what it finds
in the sidebar. It never blocks an export — it tells you, you decide.

Every rule reports whether it passed or failed, so a clean result reads as *these things were
examined and they are fine* rather than an unexplained thumbs up:

```
  Checked 2 selected object(s) against 'Skeletal Mesh' — exporting ARMATURE, MESH, animation baked
  Body: scale applied (1, 1, 1)
  Body: rotation applied (0°, 0°, 0°)
  Body: 4812 face(s)
  Body: 1 UV map(s)
  Rig: rig unrotated, so it faces -Y as the engine presets expect
  Rig: action 'Run' spans 1-60, inside the scene range 1-100
```

Problems sort to the top, and the eye icon in the header hides the passing lines once you
only care about what is wrong.

| Check | Level |
|---|---|
| Nothing selected to export | error |
| Negative scale — faces import inside out | error |
| Mesh has no faces | error |
| Armature has no bones | error |
| Animation preset, but the rig has no action | error |
| One file per object is on, but the filename has no `{object}` | error |
| Scene unit scale is not 1.0 | warning |
| Scale or rotation not applied | warning |
| Non-uniform scale | warning |
| Mesh has no UV map | warning |
| Rig has more than one root bone | warning |
| Rig is yawed away from the `-Y` forward convention | warning |
| Scene frame rate is not a standard rate | warning |
| Action is longer than the scene frame range, so the bake will cut it | warning |

Scene-wide checks come first, because a wrong unit scale invalidates every object under it at
once. Unit scale is the one worth reading twice: engines treat one Blender unit as one metre, so
a scene authored at 0.01 looks correct in Blender and arrives 100× off, with nothing in the
viewport hinting at it.

That last one is worth knowing about: the FBX exporter bakes over the **scene** frame range,
not the action's, so an action running past `frame_end` exports truncated with no warning from
Blender.

**On rig orientation:** Validate reports the rig object's yaw, because that is what is
actually knowable from the file. Whether the character *model* was sculpted facing the wrong
way cannot be read out of geometry — no tool can tell you where a face is pointing — so that
one stays a human check. The convention the engine presets assume is: characters face `-Y` in
Blender, unrotated.

## Baking rotation and scale without touching your scene

Engines want assets with clean rotation and scale, but applying them in Blender is a permanent
edit to your working file. **Bake rotation & scale** gets both: the selection is duplicated, the
transforms are applied to the duplicates, the duplicates are exported and then deleted. Your
objects keep their rotation and scale exactly as you left them.

**Location is deliberately not applied.** Applying it moves an object's origin to the world
origin and bakes the offset into the vertices — identical in Blender, but the engine then holds a
mesh whose pivot sits at zero while its geometry is somewhere else, so the prop rotates around a
point it is nowhere near. Where the pivot goes is a modelling decision, not something an exporter
should quietly change.

The whole selection is duplicated in one step, so parenting and armature-modifier links between
the objects survive into the export. Filenames still come from the original object names, not
from Blender's `Chair.001` duplicate naming. If anything fails partway, the duplicates are
removed anyway.

Validation knows about this: with baking on, an unapplied scale is reported as fine rather than
as something to go and fix by hand. Negative scale is still an error, since baking it does not
un-invert the normals.

## One file per object

Prop libraries usually want one FBX per asset, not one FBX containing everything. Turn on
**One file per object** in a preset and the selection is walked one object at a time, each
exported separately and each recorded in history.

The filename template must contain `{object}` — without it every object would resolve to the
same path and only the last would survive, so the add-on refuses rather than quietly
overwriting. The selection and the active object are restored afterwards.

## When the file already exists

Every preset carries an **If the file exists** setting, because there is no single right answer:
a prop you are iterating on wants to be replaced, a delivered asset does not.

| Mode | What happens |
|---|---|
| **Overwrite** | The existing file is replaced. This is the default and the long-standing behaviour. |
| **Keep both** | The existing file is left alone and the export goes to the next free numbered name: `Chair.fbx`, then `Chair_001.fbx`, `Chair_002.fbx`. |
| **Skip** | Nothing is written and the export says so. |

A skipped export is reported as a skip, never as a success — Export All counts exported, skipped
and failed presets separately, so "3 exported" always means three files were actually written.
Nothing else runs for a preset that wrote nothing: the version counter does not bump and the
export folder does not open.

With **One file per object** the policy applies per object, so one asset already on disk does not
stop the rest of the selection from exporting.

## Sharing configuration

**Preferences → Export Config to JSON** writes every project and preset to a file. Import it
on another machine, or hand it to a teammate, with *Replace all* or *Append*. Exported JSON
carries the actual values, so it stays valid even if the built-in templates change later.

## Update notifications

The add-on asks GitHub once a day whether a newer release exists, and shows a line in the
sidebar when there is one. The request runs on a background thread, so Blender never stalls
waiting for the network.

Turn it off with **Check for updates** in Preferences — with it unchecked the add-on makes no
network requests at all. **Check Now** runs one on demand.

Note that it compares against published **Releases**, not commits or tags.

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

## Author

Made by **Malik3D**.

- Source and issues: <https://github.com/Zeatrex01/export_hub>
- YouTube: <https://www.youtube.com/c/Zeatrex/>

## License

**GNU General Public License v3.0 or later.** The full text is in [LICENSE](LICENSE).

In plain terms:

- **Using it costs you nothing and requires nothing.** Export whatever you like, commercially or
  not. Files you export are yours — they are not derived from this add-on, and no credit is owed
  for them.
- **Building on it does require credit.** Modify the add-on and distribute your version, and you
  must keep the copyright notice, say what you changed, and release your version under the same
  licence with its source available.

Blender add-ons import `bpy`, which makes them derivative works of Blender itself, so the licence
has to be GPL-compatible — this is not a preference, it applies to every Blender add-on.

## Known limitations

- Fields you type into directly (export folder, filename template) are written to disk on your
  next export or button press. Use **Save Settings** in Preferences to write them immediately.
- Baking transforms requires the *Selected Objects* export mode, since the copies are made from
  the selection.
- Re-exporting from history writes to that entry's original path, so `{date}` and `{version}`
  tokens are not re-resolved — it overwrites the original file rather than producing a new one.
  The **If the file exists** policy does not apply here: you picked a specific file to write again.
- Export All refuses to run if two presets resolve to the same output path, rather than
  letting one silently overwrite the other. Add `{preset}` to the filename template to
  separate them; projects created from an engine template already do. This is about the preset
  configuration, so it applies whatever the **If the file exists** policy is set to.
- Exporting to a `//` relative folder requires the .blend to be saved first, since there is
  nothing to resolve the path against otherwise.
