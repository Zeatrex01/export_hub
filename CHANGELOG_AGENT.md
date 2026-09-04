# Agent Change Log

This document records changes made by the AI agent. The most recent change set
is kept at the top.

## Cloud Agent development environment setup

Added a reproducible Cloud Agent development environment for the Export Hub
Blender add-on and an end-to-end test harness that drives the add-on headlessly.

### Added

- `.cursor/environment.json` — Cloud Agent environment definition. Runs the
  install script below after checkout. No `start`/`terminals` are needed because
  Blender is a command-line tool here, not a long-running service.
- `.cursor/install.sh` — idempotent install step. Installs the system libraries
  a headless Blender needs, downloads a pinned Blender 4.2 LTS portable build,
  and links `blender` into both `~/.local/bin` and `/usr/local/bin` so a bare
  `blender` works in any shell. Re-running reuses an existing Blender.
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
