#!/usr/bin/env python3
"""Render a parameterized per-user macOS LaunchAgent to stdout; installs nothing."""
import argparse
from pathlib import Path
import plistlib
import sys


def build_plist(project_dir, python, log_dir, host="127.0.0.1", port=8790, enable_gost=False):
    project = Path(project_dir).expanduser().resolve()
    # Keep the virtualenv interpreter path: resolving its symlink loses venv discovery.
    executable = Path(python).expanduser().absolute()
    logs = Path(log_dir).expanduser().resolve()
    arguments = [str(executable), str(project / "server.py"), "--host", host, "--port", str(port)]
    if enable_gost:
        arguments.append("--enable-gost")
    return {"Label": "com.example.sidescreen", "ProgramArguments": arguments,
            "WorkingDirectory": str(project), "RunAtLoad": True, "KeepAlive": True,
            "ThrottleInterval": 10, "StandardOutPath": str(logs / "sidescreen.log"),
            "StandardErrorPath": str(logs / "sidescreen.log")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--enable-gost", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not (Path(args.project_dir).expanduser() / "server.py").is_file():
        parser.error("--project-dir must contain server.py")
    if not Path(args.python).expanduser().is_file():
        parser.error("--python must name an existing interpreter")
    sys.stdout.buffer.write(plistlib.dumps(build_plist(args.project_dir, args.python, args.log_dir,
                                                      args.host, args.port, args.enable_gost), sort_keys=False))


if __name__ == "__main__":
    main()
