#!/usr/bin/env python3
"""Configure competition collections, home screen sections, and family user access."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Reuse competition bucket logic from library setup script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_competition_libraries import COMP_ROOT, classify_competition  # noqa: E402

DEFAULT_SERVER = "http://192.168.10.96:8096"
COMPETITION_ROOT = "/media/Competition2026"

# Newest competition first on home (Believe Nationals → … → In10sity).
COMPETITION_COLLECTIONS = (
    ("Believe Nationals 2026", "BelieveNationals2026"),
    ("Believe 2026", "Believe2026"),
    ("Starpower 2026", "Starpower2026"),
    ("ID 2026", "ID2026"),
    ("In10sity 2026", "In10sity2026"),
)

HSS_PLUGIN_ID = "b8298e012697407ab44daa8dc795e850"
COLLECTION_SECTIONS_PLUGIN_ID = "043b2c48-b3e0-4610-b398-8217b146d1a4"

FAMILY_LIBRARY_NAMES = (
    "Competition 2026",
    "In10sity",
    "ID",
    "Starpower",
    "Believe",
    "Believe Nationals",
    "People",
    "Collections",
)


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

    def get_user(self, user_id: str) -> dict:
        return json.loads(self._call("GET", f"/Users/{user_id}"))

    def get_videos(self) -> list[dict]:
        raw = json.loads(
            self._call(
                "GET",
                "/Items?Recursive=true&IncludeItemTypes=Video&Fields=Path,Name&Limit=1000",
            )
        )
        return raw.get("Items", [])

    def get_collections(self) -> dict[str, str]:
        raw = json.loads(
            self._call("GET", "/Items?IncludeItemTypes=BoxSet&Recursive=true&Fields=Path,Name&Limit=500")
        )
        return {item["Name"]: item["Id"] for item in raw.get("Items", [])}

    def create_collection(self, name: str, item_ids: list[str]) -> str:
        params = {"name": name}
        if item_ids:
            params["ids"] = ",".join(item_ids)
        query = urllib.parse.urlencode(params)
        raw = json.loads(self._call("POST", "/Collections", query=query))
        return raw["Id"]

    def add_to_collection(self, collection_id: str, item_ids: list[str]) -> None:
        if not item_ids:
            return
        query = urllib.parse.urlencode({"ids": ",".join(item_ids)})
        self._call("POST", f"/Collections/{collection_id}/Items", query=query)

    def get_plugin_config(self, plugin_id: str) -> dict:
        return json.loads(self._call("GET", f"/Plugins/{plugin_id}/Configuration"))

    def set_plugin_config(self, plugin_id: str, config: dict) -> None:
        self._call("POST", f"/Plugins/{plugin_id}/Configuration", config)

    def update_user_policy(self, user_id: str, policy: dict) -> None:
        self._call("POST", f"/Users/{user_id}/Policy", policy)

    def update_user_configuration(self, user_id: str, configuration: dict) -> None:
        self._call("POST", f"/Users/{user_id}/Configuration", configuration)

    def bust_hss_cache(self) -> None:
        self._call("POST", "/HomeScreen/BustCache")


def bucket_videos(videos: list[dict]) -> dict[str, list[dict]]:
    bucket_to_collection = {
        "In10sity": "In10sity 2026",
        "ID": "ID 2026",
        "Starpower": "Starpower 2026",
        "Believe": "Believe 2026",
        "Believe Nationals": "Believe Nationals 2026",
    }
    buckets: dict[str, list[dict]] = {name: [] for name, _ in COMPETITION_COLLECTIONS}
    for item in videos:
        path = item.get("Path") or ""
        if not path.startswith(COMPETITION_ROOT + "/"):
            continue
        bucket = classify_competition(path, item.get("Name") or "")
        collection_name = bucket_to_collection.get(bucket or "")
        if collection_name:
            buckets[collection_name].append(item)
    return buckets


def ensure_collections(client: Client, buckets: dict[str, list[dict]], *, apply: bool) -> dict[str, str]:
    existing = client.get_collections()
    ids: dict[str, str] = {}
    for collection_name, _ in COMPETITION_COLLECTIONS:
        item_ids = [v["Id"] for v in buckets.get(collection_name, [])]
        if collection_name in existing:
            coll_id = existing[collection_name]
            print(f"Collection exists: {collection_name} ({len(item_ids)} videos planned)")
            if apply and item_ids:
                client.add_to_collection(coll_id, item_ids)
                print(f"  Added/linked {len(item_ids)} videos")
            ids[collection_name] = coll_id
            continue
        print(f"Would create collection: {collection_name} ({len(item_ids)} videos)")
        if apply:
            coll_id = client.create_collection(collection_name, item_ids)
            print(f"  Created {collection_name} id={coll_id}")
            ids[collection_name] = coll_id
    return ids


def configure_collection_sections(client: Client, *, apply: bool) -> None:
    labels = {
        "In10sity 2026": "In10sity",
        "ID 2026": "ID",
        "Starpower 2026": "Starpower",
        "Believe 2026": "Believe",
        "Believe Nationals 2026": "Believe Nationals",
    }
    sections = [
        {
            "UniqueId": section_id,
            "DisplayText": labels[collection_name],
            "CollectionName": collection_name,
            "SectionType": 0,
        }
        for collection_name, section_id in COMPETITION_COLLECTIONS
    ]
    print("\nCollection Sections plugin:")
    for s in sections:
        print(f"  {s['DisplayText']} -> {s['CollectionName']}")
    if apply:
        client.set_plugin_config(COLLECTION_SECTIONS_PLUGIN_ID, {"Sections": sections})
        print("  Saved Collection Sections config")


def configure_home_screen_sections(client: Client, *, apply: bool) -> None:
    config = client.get_plugin_config(HSS_PLUGIN_ID)

    # Replace stale/duplicate registrations with a clean set only.
    section_settings: list[dict] = []

    def add(section_id: str, *, order: int, view_mode: str = "Landscape", enabled: bool = True) -> None:
        section_settings.append(
            {
                "SectionId": section_id,
                "Enabled": enabled,
                "AllowUserOverride": False,
                "LowerLimit": 1,
                "UpperLimit": 1,
                "OrderIndex": order,
                "ViewMode": view_mode,
                "HideWatchedItems": False,
            }
        )

    # Library tiles row — always works even when collections need rebuilding.
    add("MyMedia", order=5, view_mode="Landscape")
    # Competition rows: newest event highest on page (lower OrderIndex = higher).
    for index, (_, section_id) in enumerate(COMPETITION_COLLECTIONS):
        add(section_id, order=10 + index, view_mode="Landscape")
    add("dancers", order=20, view_mode="Portrait")
    add("ContinueWatching", order=30)

    config["SectionSettings"] = section_settings
    config["Enabled"] = True
    config["AllowUserOverride"] = False

    print("\nHome Screen Sections:")
    for entry in section_settings:
        if entry.get("Enabled"):
            print(f"  [{entry.get('OrderIndex'):>2}] {entry.get('SectionId')} ({entry.get('ViewMode')})")

    if apply:
        client.set_plugin_config(HSS_PLUGIN_ID, config)
        client.bust_hss_cache()
        print("  Saved Home Screen Sections config and busted cache")


def enable_modular_home(client: Client, *, apply: bool) -> None:
    print("\nModular Home (useModularHome) for all users:")
    for user in client.get_users():
        print(f"  {user['Name']}")
        if not apply:
            continue
        query = urllib.parse.urlencode({"userId": user["Id"], "client": "emby"})
        prefs = json.loads(client._call("GET", f"/DisplayPreferences/usersettings?{query}"))
        prefs.setdefault("CustomPrefs", {})["useModularHome"] = "true"
        client._call("POST", f"/DisplayPreferences/usersettings?{query}", prefs)


def update_family_users(client: Client, *, apply: bool) -> None:
    libs = {lib["Name"]: lib["ItemId"] for lib in client.get_libraries() if lib.get("ItemId")}
    allowed = [libs[name] for name in FAMILY_LIBRARY_NAMES if name in libs]
    missing = [name for name in FAMILY_LIBRARY_NAMES if name not in libs]
    if missing:
        print(f"Warning: missing libraries for family access: {missing}")

    my_media_excludes = [libs[n] for n in ("People", "Collections", "Competition 2026") if n in libs]

    print("\nFamily users -> libraries:", FAMILY_LIBRARY_NAMES)
    print("My Media excludes (sidebar libs only on home row): People, Collections")

    for user in client.get_users():
        if user["Policy"].get("IsAdministrator"):
            continue
        print(f"  {user['Name']}")
        if not apply:
            continue
        policy = user["Policy"]
        policy["EnableAllFolders"] = False
        policy["EnabledFolders"] = allowed
        policy["EnableAllChannels"] = False
        policy["EnabledChannels"] = []
        client.update_user_policy(user["Id"], policy)

        full = client.get_user(user["Id"])
        config = full.get("Configuration") or {}
        comp_ids = [libs[n] for n in (
            "Believe Nationals",
            "Believe",
            "Starpower",
            "ID",
            "In10sity",
        ) if n in libs]
        config["OrderedViews"] = comp_ids + [libs["People"]] if "People" in libs else comp_ids
        config["GroupedFolders"] = []
        config["DisplayCollectionsView"] = False
        config["MyMediaExcludes"] = my_media_excludes
        config["LatestItemsExcludes"] = my_media_excludes
        client.update_user_configuration(user["Id"], config)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    client = Client(args.server, args.api_key)
    videos = client.get_videos()
    buckets = bucket_videos(videos)

    print("Competition videos by collection:")
    for name, _ in COMPETITION_COLLECTIONS:
        print(f"  {name}: {len(buckets.get(name, []))}")

    ensure_collections(client, buckets, apply=args.apply)
    configure_collection_sections(client, apply=args.apply)
    configure_home_screen_sections(client, apply=args.apply)
    enable_modular_home(client, apply=args.apply)
    update_family_users(client, apply=args.apply)

    if not args.apply:
        print("\nDry run. Re-run with --apply to push changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
