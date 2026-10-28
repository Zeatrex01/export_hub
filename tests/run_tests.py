"""Run the Export Hub test suite against a throwaway Blender profile.

    python tests/run_tests.py                      # with the bpy module (pip install bpy)
    python tests/run_tests.py /path/to/blender     # with a Blender build

The suite installs and removes the add-on, deletes and rewrites userpref.blend and
installs an extension, so it must never see your everyday Blender profile. This
script points every Blender user folder at a new temporary directory, runs the
suite there and deletes the directory afterwards. The suite refuses to start
without it.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE = os.path.join(HERE, "test_export_hub.py")


def main(argv):
    profile = tempfile.mkdtemp(prefix="export_hub_test_profile_")
    env = dict(os.environ)
    env.update({
        "EXH_TEST_PROFILE": profile,
        # 4.2+ takes everything from BLENDER_USER_RESOURCES; the others cover 3.6 to 4.1.
        "BLENDER_USER_RESOURCES": profile,
        "BLENDER_USER_CONFIG": os.path.join(profile, "config"),
        "BLENDER_USER_SCRIPTS": os.path.join(profile, "scripts"),
        "BLENDER_USER_DATAFILES": os.path.join(profile, "datafiles"),
        "BLENDER_USER_EXTENSIONS": os.path.join(profile, "extensions"),
    })
    if len(argv) > 1:
        command = [argv[1], "--background", "--factory-startup", "--python", SUITE]
    else:
        command = [sys.executable, "-I", SUITE]
    try:
        return subprocess.call(command, env=env)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
