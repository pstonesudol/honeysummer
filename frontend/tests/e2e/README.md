# Inquiry layout and accessibility regression tests

Run from the repository root:

```sh
npx playwright install chromium
npm run test:e2e --workspace frontend
```

The suite starts its own local Next.js server on port 3101 with an unreachable
loopback API URL, using the site's fallback content. It never submits a form or
accesses shared staging/provider data; browser API polling is stubbed locally.
Stop any dev server in this checkout first (Next.js shares its dev lock).
Chromium checks actual grid tracks,
control bounds, computed accessible names/descriptions, consent sizing and
keyboard behavior, and closed/open navigation at mobile, tablet, desktop and
breakpoint-adjacent widths. Install Firefox/WebKit and extend the config when
cross-engine coverage is needed.
