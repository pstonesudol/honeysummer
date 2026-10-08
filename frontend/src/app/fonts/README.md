# Self-hosted fonts

This directory holds the webfont binaries loaded through `next/font/local` in
`src/app/layout.tsx`.

| File | Role | CSS variable |
|---|---|---|
| `Gaian-Regular.woff2` | Body copy | `--font-gaian` (maps to `--font-serif`) |
| `SouthCoast-Regular.woff2` | Headings and section titles | `--font-south-coast` (maps to `--font-script`) |

These WOFF2 files were supplied in the seller's `web-fonts` download and are included in the
project so local builds and deployments can load them. The seller confirmed in writing that
both purchases are now covered by a web license at no extra cost, allowing self-hosting and
live text on the website up to 10,000 pageviews per month. Keep the seller's confirmation
message with the purchase records; the seller explicitly stated it serves as confirmation of
the license change.

The original licenses were Standard Desktop Commercial Licenses (1 user), which did not permit
self-hosting the fonts as webfonts; the seller's subsequent written confirmation replaces those
terms for web use. The original font files and license PDFs are retained in `frontend/source-fonts/`
for project records. Use the seller-supplied WOFF2 files as-is.

Both fonts are single-weight (400). Gaian is Latin; South Coast carries the `an`, `and`, `ch`,
`ee`, `ll`, `oo`, `rr`, `ss`, and `tt` ligatures used by the script headings.
