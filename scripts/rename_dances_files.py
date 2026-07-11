#!/usr/bin/env python3
"""Rename known ambiguous files in /media/dances via Portainer docker exec."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_PORTAINER = "http://192.168.10.96:9000"
DEFAULT_ENDPOINT = "3"
DEFAULT_CONTAINER = "c52a1cb6f97038a8c72dd61a42e5a5c26e49e6d2ec2611ccbcff3171da549119"
DANCES_DIR = "/media/dances"

# Confirmed renames only — filename on disk -> new basename (extension preserved).
RENAME_MAP = {
    "IMG_6367": "i2i",
    "Artistic%20Edge%20Nutcracker%202025_hd": "Artistic Edge Nutcracker 2025_hd",
}


class Portainer:
    def __init__(self, base: str, user: str, password: str, endpoint: str, container: str) -> None:
        self.base = base.rstrip("/")
        self.endpoint = endpoint
        self.container = container
        token_req = urllib.request.Request(
            f"{self.base}/api/auth",
            data=json.dumps({"Username": user, "Password": password}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(token_req, timeout=30) as resp:
            self.jwt = json.loads(resp.read())["jwt"]
        self.headers = {"Authorization": f"Bearer {self.jwt}"}

    def exec(self, cmd: list[str]) -> str:
        create_body = json.dumps(
            {"AttachStdout": True, "AttachStderr": True, "Cmd": cmd}
        ).encode()
        create_req = urllib.request.Request(
            f"{self.base}/api/endpoints/{self.endpoint}/docker/containers/{self.container}/exec",
            data=create_body,
            headers={**self.headers, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(create_req, timeout=30) as resp:
            exec_id = json.loads(resp.read())["Id"]

        start_req = urllib.request.Request(
            f"{self.base}/api/endpoints/{self.endpoint}/docker/exec/{exec_id}/start",
            data=json.dumps({"Detach": False, "Tty": False}).encode(),
            headers={**self.headers, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(start_req, timeout=120) as resp:
            raw = resp.read()

        # Docker multiplex stream: strip 8-byte headers when present.
        chunks: list[str] = []
        i = 0
        while i < len(raw):
            if i + 8 <= len(raw):
                length = int.from_bytes(raw[i + 4 : i + 8], "big")
                chunk = raw[i + 8 : i + 8 + length]
                chunks.append(chunk.decode("utf-8", "replace"))
                i += 8 + length
            else:
                chunks.append(raw[i:].decode("utf-8", "replace"))
                break
        return "".join(chunks).strip()


def related_paths(old_base: str, new_base: str) -> list[tuple[str, str]]:
    suffixes = ["", "-poster.jpg", ".trickplay"]
    pairs: list[tuple[str, str]] = []
    for suffix in suffixes:
        if suffix == ".trickplay":
            pairs.append(
                (f"{DANCES_DIR}/{old_base}.trickplay", f"{DANCES_DIR}/{new_base}.trickplay")
            )
            continue
        # Preserve original extension for media files by discovering via mv command later.
        pairs.append((old_base + suffix, new_base + suffix))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portainer", default=DEFAULT_PORTAINER)
    parser.add_argument("--user", default="djones0")
    parser.add_argument("--password", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    planned: list[str] = []
    for old_base, new_base in RENAME_MAP.items():
        planned.append(f"{old_base}.* -> {new_base}.*")

    print("Planned renames:")
    for line in planned:
        print(f"  - {line}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to rename on disk.")
        return 0

    portainer = Portainer(
        args.portainer, args.user, args.password, DEFAULT_ENDPOINT, DEFAULT_CONTAINER
    )

    for old_base, new_base in RENAME_MAP.items():
        # Rename media file with any extension, plus jellyfin sidecars.
        script = f"""
set -e
cd '{DANCES_DIR}'
for f in {old_base}.*; do
  [ -e "$f" ] || continue
  ext="${{f##{old_base}}}"
  git=true
  case "$f" in
    *.trickplay) mv "$f" "{new_base}.trickplay" ;;
    *) mv "$f" "{new_base}$ext" ;;
  esac
  echo "renamed $f -> {new_base}$ext"
done
if [ -d "{old_base}.trickplay" ]; then mv "{old_base}.trickplay" "{new_base}.trickplay"; echo "renamed dir"; fi
"""
        output = portainer.exec(["sh", "-c", script])
        print(output or f"Renamed {old_base} -> {new_base}")

    print("\nTrigger Jellyfin library scan afterward.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
