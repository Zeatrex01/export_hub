# Agent Change Log

This document records changes made by the AI agent. The most recent change set
is kept at the top.

## Sidebar panel redesign (UI)

Reworked the 3D-viewport sidebar panel (`ui.py`, `EXH_PT_export`) into a
clearer, more modern card-based layout. No operator logic or behaviour changed —
only presentation.

### Changed

- The panel is now a set of titled, numbered cards that read as an ordered flow:
  `1. Project`, `2. Preset`, `3. Destination`, `4. Check & Export`. A small
  `_card()` helper draws each section header consistently (icon + title).
- `3. Destination` shows the folder, the editable filename with its token
  picker, and a resolved `Output` preview on labelled rows. When no folder is
  set it turns red and offers a direct "Set export folder" button.
- `4. Check & Export` groups Validate, the validation results, and the export
  actions together, with the primary `Export` button given strong emphasis and
  `Export All Presets` as a clearly secondary action.
- The first-run state is now a friendly "Welcome to Export Hub" card with a
  prominent "Start from an Engine" action instead of a bare label.

### Verified

- Registers cleanly and the headless E2E suite still passes 9/9.
- Rendered in the Blender 4.5.1 GUI with no draw/Python errors; Validate and
  Export both work from the new layout (see the demo recording in the PR).

## Cloud Agent development environment setup

Added a reproducible Cloud Agent development environment for the Export Hub
Blender add-on and an end-to-end test harness that drives the add-on headlessly.

### Added

- `.cursor/environment.json` — Cloud Agent environment definition. Runs the
  install script below after checkout. No `start`/`terminals` are needed because
  Blender is a command-line tool here, not a long-running service.
- `.cursor/install.sh` — idempotent install step. Installs the system libraries
  a headless Blender needs, downloads a pinned Blender build (default 4.5.1 LTS,
  the top of the supported range; overridable with `BLENDER_VERSION`), and links
  `blender` into both `~/.local/bin` and `/usr/local/bin` so a bare `blender`
  works in any shell. Re-running reuses an existing Blender.
- `tests/run_matrix.sh` — runs the suite against several Blender versions,
  downloading any that are missing. Default matrix: 3.6.23 (minimum), 4.2.23 and
  4.5.1 (ceiling). Verified the add-on passes on all three, covering the full
  supported range (Blender 3.6 up to the 4.5 LTS line).
- `tests/test_export_hub.py` — headless end-to-end test suite. Installs the
  repository as the `export_hub` add-on, enables Blender's bundled FBX exporter,
  builds a small scene and exercises the real user flows: engine-template
  projects, single export, Export All, validation, one-file-per-object, the
  "keep both" overwrite policy, JSON config round-trip and filename sanitising.
  It asserts on FBX files actually written to disk and exits non-zero on any
  failure, so it is usable as the canonical automated check.
- `package.sh` — a Linux/macOS counterpart to the Windows-only `package.bat`,
  building `build/export_hub-<version>.zip` with the same whitelist of modules.

### How to use

- Install: `bash ./.cursor/install.sh`
- Run the test suite:
  `blender --background --factory-startup --python tests/test_export_hub.py`
- Build the release zip: `bash package.sh`

### Notes

- No application code was modified; only environment configuration, a test
  harness and a packaging helper were added.
