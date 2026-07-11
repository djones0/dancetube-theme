#!/usr/bin/env python3
"""Disable remote metadata/image fetchers for amateur home-video libraries."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import urllib.error
import urllib.request

DEFAULT_SERVER = "http://192.168.10.96:8096"

LOCAL_IMAGE_FETCHERS = ["Screen Grabber", "Embedded Image Extractor"]
BLOCKED_FETCHERS = [
    "TheMovieDb",
    "The Open Movie Database",
    "OMDb",
    "Tmdb",
    "MusicBrainz",
    "AudioDb",
]


class Client:
    def __init__(self, server: str, api_key: str) -> None:
        self.server = server.rstrip("/")
        self.headers = {
            "Authorization": f'MediaBrowser Token="{api_key}"',
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def get_libraries(self) -> list[dict]:
        req = urllib.request.Request(f"{self.server}/Library/VirtualFolders", headers=self.headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())

    def update_library(self, library_id: str, options: dict) -> None:
        body = {"Id": library_id, "LibraryOptions": options}
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.server}/Library/VirtualFolders/LibraryOptions",
            data=data,
            headers=self.headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                if resp.status != 204:
                    raise RuntimeError(f"Unexpected status {resp.status}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(exc.read().decode(errors="replace")) from exc


def strip_remote_fetchers(options: dict) -> dict:
    updated = copy.deepcopy(options)
    updated["EnableInternetProviders"] = False
    updated["AutomaticRefreshIntervalDays"] = 0
    updated["SaveLocalMetadata"] = True

    type_options = updated.get("TypeOptions") or []
    if not type_options:
        return updated

    new_type_options = []
    for entry in type_options:
        entry = copy.deepcopy(entry)
        entry["MetadataFetchers"] = []
        entry["MetadataFetcherOrder"] = []
        entry["ImageFetchers"] = [
            f for f in (entry.get("ImageFetchers") or []) if f in LOCAL_IMAGE_FETCHERS
        ] or LOCAL_IMAGE_FETCHERS.copy()
        entry["ImageFetcherOrder"] = [
            f
            for f in (entry.get("ImageFetcherOrder") or [])
            if f in LOCAL_IMAGE_FETCHERS
        ] or LOCAL_IMAGE_FETCHERS.copy()
        entry["DisabledMetadataFetchers"] = BLOCKED_FETCHERS.copy()
        entry["DisabledImageFetchers"] = BLOCKED_FETCHERS.copy()
        new_type_options.append(entry)
    updated["TypeOptions"] = new_type_options
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    client = Client(args.server, args.api_key)
    libraries = client.get_libraries()

    for lib in libraries:
        name = lib["Name"]
        opts = lib["LibraryOptions"]
        remote_on = opts.get("EnableInternetProviders", False)
        fetchers = []
        for t in opts.get("TypeOptions") or []:
            fetchers.extend(t.get("MetadataFetcherOrder") or [])
            fetchers.extend(t.get("ImageFetcherOrder") or [])
        blocked = [f for f in fetchers if f in BLOCKED_FETCHERS]
        if remote_on or blocked:
            print(f"- {name}: disable remote providers ({', '.join(blocked) or 'internet flag'})")
        else:
            print(f"- {name}: already local-only")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write changes.")
        return 0

    for lib in libraries:
        client.update_library(lib["ItemId"], strip_remote_fetchers(lib["LibraryOptions"]))
        print(f"Updated: {lib['Name']}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
