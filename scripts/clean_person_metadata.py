#!/usr/bin/env python3
"""Strip external celebrity metadata from local dancer Person items and lock them."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_SERVER = "http://192.168.10.96:8096"
KEEP_LOCAL_PHOTOS = {"Dawson", "Hudsen Jones"}  # user-uploaded photos to preserve

PERSON_FIELDS = (
    "Overview,PremiereDate,ProductionYear,ProviderIds,Tags,LockData,LockedFields,"
    "Genres,Studios,CommunityRating,CriticRating,OfficialRating,CustomRating,EndDate,"
    "OriginalTitle,SortName,Taglines"
)


class Client:
    def __init__(self, server: str, api_key: str) -> None:
        self.server = server.rstrip("/")
        self.headers = {
            "Authorization": f'MediaBrowser Token="{api_key}"',
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, body: dict | None = None) -> tuple[int, bytes]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.server}{path}",
            data=data,
            headers=self.headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def get_persons(self) -> list[dict]:
        status, raw = self._call("GET", "/Persons?Limit=500")
        if status != 200:
            raise RuntimeError(f"GET /Persons failed ({status})")
        return json.loads(raw)["Items"]

    def get_item(self, item_id: str) -> dict:
        status, raw = self._call("GET", f"/Items?Ids={item_id}&Fields={PERSON_FIELDS}")
        if status != 200:
            raise RuntimeError(f"GET item {item_id} failed ({status})")
        return json.loads(raw)["Items"][0]

    def clean_person(self, item: dict, *, keep_photo: bool) -> None:
        item_id = item["Id"]
        if not keep_photo and item.get("ImageTags"):
            status, _ = self._call("DELETE", f"/Items/{item_id}/Images/Primary")
            if status not in (200, 204):
                print(f"  warn: could not delete image for {item['Name']} ({status})")

        for key in (
            "Overview",
            "PremiereDate",
            "ProductionYear",
            "EndDate",
            "CommunityRating",
            "CriticRating",
            "OfficialRating",
            "CustomRating",
            "OriginalTitle",
            "Taglines",
        ):
            item[key] = None if key != "Overview" else ""
        item["ProviderIds"] = {}
        item["Tags"] = []
        item["Genres"] = []
        item["Studios"] = []
        item["LockData"] = True
        item["LockedFields"] = ["Name", "Overview", "Cast", "Tags"]

        status, body = self._call("POST", f"/Items/{item_id}", item)
        if status != 204:
            raise RuntimeError(
                f"POST /Items/{item_id} for {item['Name']} failed ({status}): {body.decode(errors='replace')}"
            )

    def delete_person(self, item_id: str) -> None:
        status, body = self._call("DELETE", f"/Items/{item_id}")
        if status not in (200, 204):
            raise RuntimeError(
                f"DELETE person {item_id} failed ({status}): {body.decode(errors='replace')}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    client = Client(args.server, args.api_key)
    persons = client.get_persons()
    print(f"Found {len(persons)} person records")

    for summary in persons:
        name = summary["Name"]
        if name == "Marley":
            print(f"- {name}: duplicate celebrity record -> delete")
            continue
        keep_photo = name in KEEP_LOCAL_PHOTOS
        print(f"- {name}: strip external metadata, lock, photo={'keep' if keep_photo else 'remove'}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write changes.")
        return 0

    for summary in persons:
        name = summary["Name"]
        item_id = summary["Id"]
        if name == "Marley":
            client.delete_person(item_id)
            print(f"Deleted duplicate person: {name}")
            continue
        item = client.get_item(item_id)
        client.clean_person(item, keep_photo=name in KEEP_LOCAL_PHOTOS)
        print(f"Cleaned and locked: {name}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
