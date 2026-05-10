# Branding Assets

## Contents

- `sigil.svg` — Hexagonal "E" sigil. Currently a placeholder geometric reproduction pending the official export. All downstream icons are generated from this file.
- `colors.json` — Brand token source of truth: navy, teal, cream, and appBackground hex values.

## Swapping the sigil

Replace `sigil.svg` with the official SVG export (preserve the `viewBox="0 0 240 240"` attribute or update the generation scripts if the dimensions differ), then regenerate:

```bash
npm run icons:generate
npm run icons:splash
```

Commit the updated PNGs in `public/icons/` and `public/splash/`.

## Updating colors

Edit `colors.json`, then regenerate icons and splash screens with the commands above. The generation scripts read brand colors directly and embed them as background fills.
