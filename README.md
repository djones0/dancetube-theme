# AEDC Tube Jellyfin Theme

Custom Jellyfin CSS for the AEDC DanceTube brand — black background, red accents, graffiti-style logo.

## Usage

In Jellyfin → Dashboard → Branding → Custom CSS, paste:

```css
@import url("https://cdn.jsdelivr.net/gh/djones0/dancetube-theme@master/dancetube-theme.css?v=3.6");
```

Bump the `?v=` query when you update the theme so browsers and jsDelivr pick up the new file.

## Brand assets

| Asset | Use |
|-------|-----|
| `assets/aedc-dancetube-banner.png` | Header + login (wide) |
| `assets/aedc-dancetube-icon.png` | Sidebar / drawer (square) |
