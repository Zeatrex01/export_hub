"""Update check against the project's GitHub releases.

Three constraints shape this file:

* Blender's UI is single-threaded. A blocking network call made from a panel
  draw or an operator freezes the whole application until it returns or times
  out, so the request runs on a worker thread.
* Blender data must not be touched from that thread. The worker only writes
  plain strings and tuples into `_state`; asking Blender to redraw is done by a
  timer running on the main thread.
* An add-on reaching the network without the user knowing is rude. The check is
  off-switchable, runs at most once a day, and reports what it did.
"""

import re
import sys
import json
import datetime
import threading
import urllib.error
import urllib.request

import bpy

REPO_URL = "https://github.com/Zeatrex01/export_hub"
RELEASES_API = "https://api.github.com/repos/Zeatrex01/export_hub/releases/latest"
RELEASES_PAGE = REPO_URL + "/releases"

_TIMEOUT = 6.0

# Written by the worker thread, read by the UI. Plain data only, no bpy types.
#   idle      nothing has been attempted yet
#   checking  a request is in flight
#   current   this install is up to date
#   available a newer release exists
#   none      the repository has no published releases
#   error     the check could not complete
_state = {"status": "idle", "latest": None, "message": ""}
_lock = threading.Lock()


def current_version():
    """This add-on's version, read from bl_info at call time.

    Looked up through sys.modules rather than imported, because this module is
    imported *by* the package __init__ that defines bl_info — importing it back
    at module level would be circular.
    """
    package = sys.modules.get(__package__)
    version = getattr(package, "bl_info", {}).get("version", (0, 0, 0))
    return _pad(tuple(version))


def _pad(version):
    """Normalise a version tuple to three parts so comparisons are total."""
    return (tuple(version) + (0, 0, 0))[:3]


def _parse_version(tag):
    """Turn a release tag such as 'v1.6.0' or '1.6' into a comparable tuple."""
    numbers = re.findall(r"\d+", tag or "")
    if not numbers:
        return None
    return _pad(tuple(int(n) for n in numbers[:3]))


def state():
    """A snapshot of the check result, safe to read from a draw callback."""
    with _lock:
        return dict(_state)


def due_today(prefs):
    """True when no successful check has been started yet today."""
    return prefs.last_update_check != datetime.date.today().isoformat()


def _worker():
    try:
        request = urllib.request.Request(
            RELEASES_API,
            headers={
                "User-Agent": "export-hub-addon",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # A repository with no releases yet answers 404. That is a normal state,
        # not a failure the user should see as a problem.
        if exc.code == 404:
            result = ("none", None, "No releases published yet")
        else:
            result = ("error", None, "GitHub returned %s" % exc.code)
    except Exception as exc:                      # network down, DNS, timeout...
        result = ("error", None, "%s" % exc)
    else:
        latest = _parse_version(payload.get("tag_name", ""))
        if latest is None:
            result = ("error", None, "Could not read the release tag")
        elif latest > current_version():
            result = ("available", latest, "")
        else:
            result = ("current", latest, "")

    with _lock:
        _state["status"], _state["latest"], _state["message"] = result


def _redraw_when_done():
    """Main-thread timer: refresh the sidebar once the worker has finished."""
    with _lock:
        still_running = _state["status"] == "checking"
    if still_running:
        return 0.5

    window_manager = bpy.context.window_manager
    if window_manager:
        for window in window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    return None


def start_check():
    """Kick off a check unless one is already running."""
    with _lock:
        if _state["status"] == "checking":
            return False
        _state["status"] = "checking"
        _state["latest"] = None
        _state["message"] = ""

    threading.Thread(target=_worker, daemon=True).start()
    if not bpy.app.timers.is_registered(_redraw_when_done):
        bpy.app.timers.register(_redraw_when_done, first_interval=0.5)
    return True


def unregister_timers():
    """Drop the redraw timer so disabling the add-on leaves nothing behind."""
    if bpy.app.timers.is_registered(_redraw_when_done):
        bpy.app.timers.unregister(_redraw_when_done)


def format_version(version):
    return ".".join(str(part) for part in version) if version else "?"
