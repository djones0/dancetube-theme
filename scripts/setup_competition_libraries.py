#!/usr/bin/env python3
"""Organize competition media into per-event libraries and lock down non-admin access."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from pathlib import PurePosixPath

DEFAULT_SERVER = "http://192.168.10.96:8096"
COMP_ROOT = "/media/Competition2026"

# Sidebar order for non-admin users (display names).
COMPETITION_LIBS = (
    "In10sity",
    "ID",
    "Starpower",
    "Believe",
    "Believe Nationals",
)

LOCAL_ONLY_LIBRARY_OPTIONS = {
    "Enabled": True,
    "EnableInternetProviders": False,
    "SaveLocalMetadata": True,
    "AutomaticRefreshIntervalDays": 0,
    "TypeOptions": [
        {
            "Type": "Video",
            "MetadataFetchers": [],
            "MetadataFetcherOrder": [],
            "ImageFetchers": ["Screen Grabber", "Embedded Image Extractor"],
            "ImageFetcherOrder": ["Screen Grabber", "Embedded Image Extractor"],
            "DisabledMetadataFetchers": ["TheMovieDb", "The Open Movie Database"],
            "DisabledImageFetchers": ["TheMovieDb", "The Open Movie Database"],
        }
    ],
}


class Client:
    def __init__(self, server: str, api_key: str) -> None:
        self.server = server.rstrip("/")
        self.headers = {
            "Authorization": f'MediaBrowser Token="{api_key}"',
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, body: dict | None = None, *, query: str = "") -> bytes:
        url = f"{self.server}{path}"
        if query:
            url = f"{url}?{query}"
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers=self.headers if data is not None else {k: v for k, v in self.headers.items() if k != "Content-Type"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{method} {path} failed ({exc.code}): {exc.read().decode(errors='replace')}") from exc

    def get_libraries(self) -> list[dict]:
        return json.loads(self._call("GET", "/Library/VirtualFolders"))

    def get_users(self) -> list[dict]:
        return json.loads(self._call("GET", "/Users"))

    def get_videos(self) -> list[dict]:
        raw = json.loads(
            self._call(
                "GET",
                "/Items?Recursive=true&IncludeItemTypes=Video&Fields=Path,Name&Limit=1000",
            )
        )
        return raw.get("Items", [])

    def add_library(self, name: str, path: str) -> None:
        query = urllib.parse.urlencode(
            {
                "name": name,
                "collectionType": "homevideos",
                "refreshLibrary": "true",
            }
        )
        body = {
            "LibraryOptions": {
                **LOCAL_ONLY_LIBRARY_OPTIONS,
                "PathInfos": [{"Path": path}],
            }
        }
        self._call("POST", "/Library/VirtualFolders", body, query=query)

    def update_user_policy(self, user_id: str, policy: dict) -> None:
        self._call("POST", f"/Users/{user_id}/Policy", policy)

    def refresh_library(self, item_id: str) -> None:
        self._call("POST", f"/Items/{item_id}/Refresh", query="Recursive=true&MetadataRefreshMode=FullRefresh")

    def rename_library(self, old_name: str, new_name: str) -> None:
        query = urllib.parse.urlencode({"name": old_name, "newName": new_name, "refreshLibrary": "true"})
        self._call("POST", "/Library/VirtualFolders/Name", query=query)

    def get_user(self, user_id: str) -> dict:
        return json.loads(self._call("GET", f"/Users/{user_id}"))

    def update_user_configuration(self, user_id: str, configuration: dict) -> None:
        self._call("POST", f"/Users/{user_id}/Configuration", configuration)


def classify_competition(path: str, name: str) -> str | None:
    """Return competition bucket or None if not competition / admin-only."""
    if not path.startswith(COMP_ROOT + "/"):
        return None

    rel = path[len(COMP_ROOT) + 1 :]
    lower_name = name.lower()
    lower_rel = rel.lower()
    basename = PurePosixPath(path).name.lower()

    if lower_rel.startswith("believe nationals 2026/"):
        return "Believe Nationals"

    admin_only = (
        lower_rel.startswith("images/")
        or lower_name.startswith("screenrecording")
        or basename.startswith("screenrecording")
        or "artistic edge may 2026" in basename
        or lower_name.startswith("ae_show")
    )
    if admin_only:
        return None

    if lower_name.startswith("starpower") or basename.startswith("starpower"):
        return "Starpower"

    if ("believe" in lower_name or "believe" in basename) and "nationals" not in lower_name:
        return "Believe"

    if "nationals" in lower_name or "nationals" in basename or "2026 nationals" in basename:
        return "Believe Nationals"

    if "in10sity" in lower_name.replace("_", " ") or "in10sity" in basename.replace("_", " "):
        return "In10sity"

    if re.search(r"\b(i2i|mib)\b", lower_name) or re.search(r"\b(i2i|mib)\b", basename):
        return "ID"
    if "i2i" in lower_name.replace(" ", "") or "i2i" in basename.replace(" ", ""):
        return "ID"

    if lower_name.startswith("id -"):
        return "ID"

    # Entry-number / group routines without explicit event tag.
    if any(x in lower_name for x in ("splish", "supercali", "crazy", "conga", "fade", "arabian", "rich girls", "beat it", "le freak", "surf crazy", "awards hudsen")):
        return "In10sity"

    if any(x in lower_name for x in ("223-aedc", "aedc-mib", "a1055", "b1055", "mibproduction")):
        return "ID"

    return "In10sity"


def target_path(path: str, bucket: str) -> str:
    rel = PurePosixPath(path[len(COMP_ROOT) + 1 :])
    filename = rel.name
    if bucket == "Believe Nationals":
        return f"{COMP_ROOT}/Believe Nationals 2026/{filename}"
    return f"{COMP_ROOT}/{bucket}/{filename}"


def plan_moves(videos: list[dict]) -> list[dict]:
    plans: list[dict] = []
    for item in videos:
        path = item.get("Path") or ""
        name = item.get("Name") or ""
        bucket = classify_competition(path, name)
        if bucket is None:
            continue
        dest = target_path(path, bucket)
        if dest == path:
            continue
        plans.append({"name": name, "from": path, "to": dest, "bucket": bucket})
    return plans


def library_ids_by_name(client: Client) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for lib in client.get_libraries():
        item_id = lib.get("ItemId") or lib.get("Id")
        if item_id and lib.get("Name"):
            mapping[lib["Name"]] = item_id
    return mapping


def ensure_libraries(client: Client, *, apply: bool) -> dict[str, str]:
    existing = library_ids_by_name(client)
    if apply and "Believe Nationals 2026" in existing and "Believe Nationals" not in existing:
        print("Renaming library: Believe Nationals 2026 -> Believe Nationals")
        client.rename_library("Believe Nationals 2026", "Believe Nationals")
        existing = library_ids_by_name(client)
    for lib_name in COMPETITION_LIBS:
        if lib_name in existing:
            print(f"Library exists: {lib_name}")
            continue
        if lib_name == "Believe Nationals":
            if "Believe Nationals 2026" in existing:
                print("Will use existing Believe Nationals 2026 library (rename in UI optional)")
                continue
            path = f"{COMP_ROOT}/Believe Nationals 2026"
        else:
            path = f"{COMP_ROOT}/{lib_name}"
        print(f"Would create library: {lib_name} -> {path}")
        if apply:
            client.add_library(lib_name, path)
            print(f"Created library: {lib_name}")
    ids = library_ids_by_name(client)
    # Map display name to id, accepting legacy Believe Nationals 2026 name.
    if "Believe Nationals" not in ids and "Believe Nationals 2026" in ids:
        ids["Believe Nationals"] = ids["Believe Nationals 2026"]
    return ids


def update_non_admin_access(client: Client, lib_ids: dict[str, str], *, apply: bool) -> None:
    allowed = [lib_ids[name] for name in COMPETITION_LIBS if name in lib_ids]
    missing = [name for name in COMPETITION_LIBS if name not in lib_ids]
    if missing:
        if apply:
            raise RuntimeError(f"Missing libraries: {missing}")
        print(f"Note: libraries not created yet: {missing}")
        return

    for user in client.get_users():
        policy = user["Policy"]
        if policy.get("IsAdministrator"):
            continue
        print(f"User {user['Name']}: allow {COMPETITION_LIBS}")
        if apply:
            policy["EnableAllFolders"] = False
            policy["EnabledFolders"] = allowed
            policy["EnableAllChannels"] = False
            policy["EnabledChannels"] = []
            policy["EnablePublicSharing"] = False
            policy["EnableContentDownloading"] = False
            client.update_user_policy(user["Id"], policy)

            full = client.get_user(user["Id"])
            config = full.get("Configuration") or {}
            config["OrderedViews"] = allowed
            config["GroupedFolders"] = []
            config["DisplayCollectionsView"] = False
            # Keep home focused on competition libraries only.
            config["MyMediaExcludes"] = []
            config["LatestItemsExcludes"] = []
            client.update_user_configuration(user["Id"], config)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-moves", action="store_true", help="Only create libraries + user access")
    args = parser.parse_args()

    client = Client(args.server, args.api_key)
    videos = [v for v in client.get_videos() if (v.get("Path") or "").startswith(COMP_ROOT + "/")]
    moves = plan_moves(videos)

    print(f"Competition videos scanned: {len(videos)}")
    print(f"Planned file moves: {len(moves)}\n")
    by_bucket: dict[str, int] = {}
    for m in moves:
        by_bucket[m["bucket"]] = by_bucket.get(m["bucket"], 0) + 1
        print(f"  [{m['bucket']}] {m['name']}")
        print(f"    {m['from']}")
        print(f" -> {m['to']}\n")
    print("Move counts:", by_bucket)

    if not args.skip_moves and moves:
        print("\nFile moves require running on the Jellyfin host (see scripts/competition_move.sh).")
        print("Generating move script...")
        script_path = Path(__file__).resolve().parent / "competition_move.sh"
        lines = ["#!/bin/sh", "set -e"]
        for m in moves:
            src = m["from"]
            dest = m["to"]
            base = PurePosixPath(src).stem
            src_dir = str(PurePosixPath(src).parent)
            dest_dir = str(PurePosixPath(dest).parent)
            lines.append(f"mkdir -p '{dest_dir}'")
            lines.append(f"mv '{src}' '{dest}'")
            lines.append(f"[ -f '{src_dir}/{base}-poster.jpg' ] && mv '{src_dir}/{base}-poster.jpg' '{dest_dir}/{base}-poster.jpg' || true")
            lines.append(f"[ -d '{src_dir}/{base}.trickplay' ] && mv '{src_dir}/{base}.trickplay' '{dest_dir}/{base}.trickplay' || true")
        script_path.write_text("\n".join(lines) + "\n")
        script_path.chmod(0o755)
        print(f"Wrote {script_path}")

    lib_ids = ensure_libraries(client, apply=args.apply)
    if args.apply:
        lib_ids = library_ids_by_name(client)
    update_non_admin_access(client, lib_ids, apply=args.apply)

    if not args.apply:
        print("\nDry run. Re-run with --apply after reviewing moves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
