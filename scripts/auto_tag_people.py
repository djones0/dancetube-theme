#!/usr/bin/env python3
"""Auto-tag Jellyfin videos using AEDC competition roster + filename hints."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_SERVER = "http://192.168.10.96:8096"
DEFAULT_ROSTER = Path(__file__).resolve().parent / "data" / "aedc_roster.json"

# First-name / spelling variants -> canonical Jellyfin person name.
# Aubrey stays first-name only (user: Aubrey == Aubree == Aubrie Childers).
CANONICAL_NAMES: dict[str, str] = {
    "hudsen": "Hudsen Jones",
    "aubrey": "Aubrey",
    "aubree": "Aubrey",
    "aubrie": "Aubrey",
    "dawson": "Dawson Brown",
    "marley": "Marlee Martin",
    "marlee": "Marlee Martin",
    "melania": "Milania Baron",
    "milania": "Milania Baron",
    "paislee": "Paislee Bledsoe",
    "rosie": "Rosalie Van Beek",
    "rosalie": "Rosalie Van Beek",
}

# Legacy short person names still present in Jellyfin cast lists.
LEGACY_PERSON_RENAMES: dict[str, str] = {
    "Dawson": "Dawson Brown",
    "Marlee": "Marlee Martin",
    "Melania": "Milania Baron",
    "Paislee": "Paislee Bledsoe",
    "Rosie": "Rosalie Van Beek",
    "Aubree": "Aubrey",
    "Aubrie": "Aubrey",
    "Marley": "Marlee Martin",
}

ITEM_FIELDS = (
    "People,Tags,ProviderIds,Genres,Studios,Overview,OriginalTitle,SortName,"
    "CommunityRating,CriticRating,OfficialRating,CustomRating,ProductionYear,"
    "PremiereDate,EndDate,Taglines,LockedFields,LockData,Path"
)


@dataclass
class Person:
    name: str
    id: str


class JellyfinClient:
    def __init__(self, server: str, api_key: str) -> None:
        self.server = server.rstrip("/")
        self.headers = {
            "Authorization": f'MediaBrowser Token="{api_key}"',
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, body: dict | None = None) -> bytes:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.server}{path}",
            data=data,
            headers={
                **self.headers,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail}") from exc

    def get_persons(self) -> dict[str, Person]:
        raw = json.loads(self._request("GET", "/Persons?Limit=1000"))
        return {item["Name"]: Person(name=item["Name"], id=item["Id"]) for item in raw.get("Items", [])}

    def get_videos(self) -> list[dict]:
        raw = json.loads(
            self._request(
                "GET",
                f"/Items?Recursive=true&IncludeItemTypes=Video&Fields={ITEM_FIELDS}&Limit=1000",
            )
        )
        return raw.get("Items", [])

    def get_item(self, item_id: str) -> dict:
        raw = json.loads(self._request("GET", f"/Items?Ids={item_id}&Fields={ITEM_FIELDS}"))
        return raw["Items"][0]

    def update_item(self, item: dict) -> None:
        item_id = item["Id"]
        if item.get("Tags") is None:
            item["Tags"] = []
        if item.get("ProviderIds") is None:
            item["ProviderIds"] = {}
        if item.get("Genres") is None:
            item["Genres"] = []
        if item.get("Studios") is None:
            item["Studios"] = []
        self._request("POST", f"/Items/{item_id}", item)

    def delete_person(self, item_id: str) -> None:
        self._request("DELETE", f"/Items/{item_id}")


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def canonical_person_name(full_name: str) -> str:
    if full_name in LEGACY_PERSON_RENAMES:
        return LEGACY_PERSON_RENAMES[full_name]
    first = full_name.split()[0].lower()
    if first in CANONICAL_NAMES:
        return CANONICAL_NAMES[first]
    if full_name in CANONICAL_NAMES.values():
        return full_name
    return full_name


def migrate_legacy_cast(client: JellyfinClient, persons: dict[str, Person]) -> int:
    """Rewrite short cast names to full roster names and drop orphan person records."""
    changed = 0
    for item in client.get_videos():
        people = item.get("People") or []
        if not people:
            continue
        new_names = [canonical_person_name(p["Name"]) for p in people]
        if new_names == [p["Name"] for p in people] and len(set(new_names)) == len(new_names):
            continue
        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for name in new_names:
            if name in seen:
                continue
            seen.add(name)
            deduped.append(name)
        full = client.get_item(item["Id"])
        full["People"] = people_for_names(deduped, persons)
        client.update_item(full)
        changed += 1
        print(f"Renamed cast on: {item.get('Name')}")

    # Delete leftover short person records once unused
    persons = client.get_persons()
    for old_name in list(LEGACY_PERSON_RENAMES):
        if old_name in persons and LEGACY_PERSON_RENAMES[old_name] != old_name:
            client.delete_person(persons[old_name].id)
            print(f"Deleted legacy person: {old_name}")
    return changed


def load_routine_cast(roster_path: Path) -> dict[str, set[str]]:
    data = json.loads(roster_path.read_text())
    routine_cast: dict[str, set[str]] = {}
    for routine in data.get("routines", []):
        key = normalize(routine["routine_name"])
        names = {canonical_person_name(d) for d in routine.get("dancers", [])}
        routine_cast[key] = names
    return routine_cast


def build_routine_matchers(routine_cast: dict[str, set[str]]) -> list[tuple[str, str]]:
    """Return (normalized needle, routine_key) sorted longest needle first."""
    matchers: list[tuple[str, str]] = []
    for routine_key in routine_cast:
        matchers.append((routine_key, routine_key))
    # Common filename variants
    extras = {
        "super cali": "supercali",
        "supercali": "supercali",
        "splishsplash": "splish splash",
        "le freak": "le freak",
        "beat it": "beat it",
        "surf crazy": "surf crazy",
        "rich girls": "rich girls",
        "arabian nights": "arabian nights",
        "stand up for love": "stand up for love",
        "smooth criminal": "smooth criminal",
    }
    for needle, routine_key in extras.items():
        if routine_key in routine_cast:
            matchers.append((needle, routine_key))
    matchers.sort(key=lambda pair: len(pair[0]), reverse=True)
    return matchers


def match_routine(title: str, path: str, matchers: list[tuple[str, str]]) -> str | None:
    haystack = normalize(f"{title} {Path(path).name}")
    haystack = re.sub(r"\bin10sity\b", " ", haystack)
    haystack = re.sub(r"\b(nationals|believe|starpower|aedc)\b", " ", haystack)
    haystack = re.sub(r"\b20\d{2}\b", " ", haystack)
    haystack = re.sub(r"\s+", " ", haystack).strip()

    if re.search(r"\bpaislee\b", haystack) and "solo" in haystack:
        return None
    if re.search(r"\bhudsen\b", haystack) and "solo" in haystack:
        return None
    if re.search(r"\bhudsen\b", haystack) and "improv" in haystack:
        return None

    if re.search(r"\bi2i\b", haystack) or haystack in {"id i2i", "b325 i2i"}:
        return "i2i"
    if "mib" in haystack.replace(" ", ""):
        return "mib"

    for needle, routine_key in matchers:
        if needle and needle in haystack:
            return routine_key
    return None


def infer_people(
    name: str, path: str, routine_cast: dict[str, set[str]], matchers: list[tuple[str, str]]
) -> set[str] | None:
    haystack = normalize(f"{name} {Path(path).name}")

    solo_match = re.search(r"\b(\w+)\s+solo\b", haystack)
    if solo_match:
        alias = solo_match.group(1)
        if alias in CANONICAL_NAMES:
            return {CANONICAL_NAMES[alias]}

    found: set[str] = set()
    for alias, canonical in CANONICAL_NAMES.items():
        if re.search(rf"\b{re.escape(alias)}\b", haystack):
            found.add(canonical)

    if len(found) == 1:
        return found

    routine_key = match_routine(name, path, matchers)
    if routine_key and routine_key in routine_cast:
        return set(routine_cast[routine_key])

    if found:
        return found
    return None


def person_entry(name: str, persons: dict[str, Person]) -> dict:
    if name in persons:
        person = persons[name]
        return {"Name": person.name, "Id": person.id, "Role": "", "Type": "Actor"}
    return {"Name": name, "Role": "", "Type": "Actor"}


def people_for_names(names: Iterable[str], persons: dict[str, Person]) -> list[dict]:
    return sorted(
        [person_entry(name, persons) for name in names],
        key=lambda p: p["Name"].lower(),
    )


def existing_names(item: dict) -> set[str]:
    names: set[str] = set()
    for person in item.get("People", []):
        name = person["Name"]
        names.add(canonical_person_name(name))
    return names


def normalize_people_list(people: list[dict], persons: dict[str, Person]) -> list[dict]:
    merged: dict[str, dict] = {}
    for person in people:
        name = canonical_person_name(person["Name"])
        merged[name] = person_entry(name, persons)
    return sorted(merged.values(), key=lambda p: p["Name"].lower())


def merge_aubree_into_aubrey(client: JellyfinClient, persons: dict[str, Person]) -> int:
    if "Aubree" not in persons or "Aubrey" not in persons:
        return 0
    changed = 0
    for item in client.get_videos():
        people = item.get("People") or []
        if not any(p["Name"] in {"Aubree", "Aubrey"} for p in people):
            continue
        new_people = []
        seen: set[str] = set()
        for person in people:
            name = canonical_person_name(person["Name"])
            if name in seen:
                continue
            seen.add(name)
            new_people.append(person_entry(name, persons))
        if normalize_people_list(people, persons) == new_people:
            continue
        full = client.get_item(item["Id"])
        full["People"] = new_people
        client.update_item(full)
        changed += 1
        print(f"Merged Aubree->Aubrey on: {item.get('Name')}")
    client.delete_person(persons["Aubree"].id)
    print("Deleted duplicate person: Aubree")
    return changed + 1


def plan_updates(
    videos: list[dict], persons: dict[str, Person], routine_cast: dict[str, set[str]], matchers
) -> list[dict]:
    plans: list[dict] = []
    for item in videos:
        inferred = infer_people(item.get("Name", ""), item.get("Path", ""), routine_cast, matchers)
        current = existing_names(item)

        if inferred is None:
            continue

        new_people = people_for_names(inferred, persons)
        new_names = {p["Name"] for p in new_people}
        if new_names == current:
            continue

        plans.append(
            {
                "name": item.get("Name"),
                "before": sorted(current),
                "after": sorted(new_names),
                "source": "roster",
                "item": item,
                "people": new_people,
            }
        )
    return plans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--merge-aubrey", action="store_true", help="Merge Aubree person into Aubrey")
    parser.add_argument(
        "--expand-names",
        action="store_true",
        help="Rewrite short cast names (Dawson, Melania, …) to full roster names",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.roster.exists():
        print(f"Roster not found: {args.roster}", file=sys.stderr)
        return 1

    client = JellyfinClient(args.server, args.api_key)
    routine_cast = load_routine_cast(args.roster)
    matchers = build_routine_matchers(routine_cast)

    if args.apply and args.merge_aubrey:
        persons = client.get_persons()
        merge_aubree_into_aubrey(client, persons)

    if args.apply and args.expand_names:
        persons = client.get_persons()
        migrate_legacy_cast(client, persons)

    persons = client.get_persons()
    videos = client.get_videos()
    plans = plan_updates(videos, persons, routine_cast, matchers)

    print(f"Roster routines: {len(routine_cast)}")
    print(f"Videos scanned: {len(videos)}")
    print(f"Persons in Jellyfin: {len(persons)}")
    print(f"Planned updates: {len(plans)}\n")

    for plan in plans:
        print(f"- {plan['name']} [{plan['source']}]")
        print(f"  before: {plan['before'] or '[]'}")
        print(f"  after:  {plan['after']} ({len(plan['after'])})\n")

    if not args.apply:
        print("Dry run. Re-run with --apply [--expand-names] [--merge-aubrey] to write changes.")
        return 0

    ok = 0
    for plan in plans:
        item = client.get_item(plan["item"]["Id"])
        item["People"] = plan["people"]
        client.update_item(item)
        ok += 1
        print(f"Updated: {plan['name']}")

    print(f"\nApplied {ok} update(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
