# AEDC DanceTube

Jellyfin theme and tooling for the AEDC DanceTube video library at `watch.venjones.com`.

**Project root:** `/Users/djones0/AEDCDancetube`

This repo is code and assets only — not Jellyfin media. Videos stay on the NAS under `/media/...`.

## Jellyfin theme

In Jellyfin → Dashboard → Branding → Custom CSS:

```css
@import url("https://cdn.jsdelivr.net/gh/djones0/dancetube-theme@master/dancetube-theme.css?v=3.9");
```

Bump the `?v=` query when you update the theme so browsers and jsDelivr pick up the new file.

### Brand assets

| Asset | Use |
|-------|-----|
| `assets/aedc-dancetube-banner.png` | Header + login (wide) |
| `assets/aedc-dancetube-icon.png` | Sidebar / drawer (square) |
| `assets/design/` | Logo drafts and source PNGs |

## Scripts

All scripts talk to Jellyfin on the LAN at `http://192.168.10.96:8096`. Pass your API key with `--api-key`.

| Script | Purpose |
|--------|---------|
| `scripts/auto_tag_people.py` | Tag video cast from competition roster + filename hints |
| `scripts/clean_person_metadata.py` | Strip external celebrity metadata from Person items |
| `scripts/lock_libraries_local.py` | Disable remote metadata/image providers on all libraries |
| `scripts/rename_dances_files.py` | Rename known ambiguous files in `/media/dances` via Portainer |

Roster data: `scripts/data/aedc_roster.json` (AEDC 2025–2026 competition dancers and routines).

```bash
# Preview cast tagging
python3 scripts/auto_tag_people.py --api-key YOUR_KEY

# Apply tagging + merge Aubrey/Aubree
python3 scripts/auto_tag_people.py --api-key YOUR_KEY --merge-aubrey --apply

# Lock down person records after tagging
python3 scripts/clean_person_metadata.py --api-key YOUR_KEY --apply
```

## GitHub

Remote: [github.com/djones0/dancetube-theme](https://github.com/djones0/dancetube-theme)
