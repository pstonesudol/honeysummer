# Self-hosted fonts

This directory holds the webfont binaries the app loads through `next/font/local`
(configured in `src/app/layout.tsx`).

| File | Role | CSS variable |
|---|---|---|
| `Gaian-Regular.woff2` | Body copy, and `<em>` emphasis inside headings | `--font-gaian` (maps to `--font-serif`) |
| `SouthCoast-Regular.woff2` | Headings and section titles | `--font-south-coast` (maps to `--font-script`) |

**The `.woff2` files are git-ignored on purpose** (see `frontend/.gitignore`), because the
current desktop licenses do not permit webfont embedding. They must be present locally for
`next dev` / `next build` to succeed; a fresh clone or CI run will fail until either the files
are restored or a webfont license is purchased and the ignore rules are removed.

## Licensing status — read before deploying

Both fonts are by **GafaroffStudio** and were purchased with a **Standard Desktop Commercial
License (1 user)**. Neither license permits self-hosting the files as webfonts:

- Gaian: "You MAY NOT … upload the font files (OTF/TTF/WOFF/WOFF2)."
- South Coast: "You MAY NOT … convert the font to other formats (WOFF/WOFF2/EOT/SVG, etc.)
  and redistribute the converted files."

Serving these `.woff2` files from a public site is webfont embedding. **Purchase a webfont/web
license before deploying**, then remove the ignore lines above to commit the binaries. Keep the
purchase records (the license PDFs live in the git-ignored `frontend/source-fonts/`).

## Regenerating the `.woff2` files

From the original `.otf` files (kept in `frontend/source-fonts/`, also git-ignored):

```bash
cd frontend/source-fonts

uv run --with fonttools --with brotli fonttools ttLib.woff2 compress \
  -o ../src/app/fonts/Gaian-Regular.woff2 GaianRegular.otf

uv run --with fonttools --with brotli fonttools ttLib.woff2 compress \
  -o ../src/app/fonts/SouthCoast-Regular.woff2 SouthCoast-Regular.otf
```

Both fonts are single-weight (400). Gaian is Latin; South Coast carries the `an`, `and`, `ch`,
`ee`, `ll`, `oo`, `rr`, `ss`, `tt` ligatures used by the script accents.
