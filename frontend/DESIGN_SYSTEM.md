# Honey Summer design system

## Status

The Phase 1 UI foundation is complete. Tokens and component conventions below are the implementation baseline. Client photography, final copy, social links, and webfont licenses remain launch assets rather than engineering blockers.

Phase 2 adds the marketing pages (Home, About, Order Flowers, Weddings & Events, Contact/FAQ, and a wholesale access request), live announcements and gallery content from the admin, and the inquiry forms.

## Color

| Token | Value | Use |
|---|---|---|
| Cream | `#F6F2EA` | Primary background |
| Dusty pink | `#D7B3B6` | Accent and seasonal emphasis |
| Soft taupe | `#C8B6A6` | Secondary surfaces |
| Champagne gold | `#E6CFAE` | Highlights |
| Cocoa | `#6A4E42` | Primary text and controls |
| Dark cocoa | `#49362E` | High-emphasis text and footer |

The CSS custom properties live in `src/app/globals.css` and are exposed to Tailwind through `@theme`.

## Typography

- **South Coast:** expressive headings and section titles. A single-weight (400) signature script with `an`/`and`/`ee`/`ll`/`oo`/`rr`/`ss`/`tt` ligatures, so it must keep `font-feature-settings: "liga" 1, "calt" 1`; its tracking is reset to `0` and line-height loosened to `1.12`. Loaded as a self-hosted local font (`src/app/fonts/`).
- **Georgia:** long-form body copy, chosen for stronger strokes and easier reading at everyday text sizes.
- **Gaian:** navigation links, card titles (including steps, values, pathways, and offerings), product names, checkout headings, and the `<em>` emphasis inside display headings. A single-weight (400) serif loaded as a self-hosted local font (`src/app/fonts/`); use a larger size for functional text to preserve legibility.
- **Geist:** labels, forms, buttons, and utility copy — including the label-style headings `.contact-card h2` and `.site-footer__links h2`, which are intentionally not set in South Coast. The Honey Summer wordmark uses the client logo lockup (`public/brand/`) rather than a font.

Both Gaian and South Coast were purchased with a desktop commercial license and require a webfont license before the `.woff2` files are committed or deployed; see `src/app/fonts/README.md`.

## Icons

Use `lucide-react` outline icons with rounded strokes. Default to `1.8` stroke width for controls and `1.5` for decorative marks. Icons accompanying visible text are decorative and must use `aria-hidden="true"`; standalone controls require an accessible label.

## Layout and components

- Content width: `1200px` maximum with responsive side gutters.
- Controls: pill-shaped with a minimum 48px target height.
- Cards: generously rounded, cream/taupe/pink surfaces, and restrained cocoa shadows.
- Motion: subtle and optional; always respect `prefers-reduced-motion`.
- Photography: warm, film-inspired treatment with descriptive alternative text.

## Forms

- Every field has a visible `<label>` bound with `for`/`id`; required fields add an asterisk and rely on native validation.
- Inputs are cream-on-cream with a `0.9rem` radius, a `48px`-ish touch target, and a `2px` dusty-pink focus ring.
- Errors render inline in a `role="alert"` region above the submit button, never as a browser alert.
- Submit buttons show a spinner and disable while the server action is pending.
- A visually hidden honeypot field screens bots without affecting assistive technology.
- Inquiry forms are defined once in `src/lib/inquiry-fields.ts` and rendered by the shared `InquiryForm` client component, so the bouquet, wedding, contact, and wholesale forms stay consistent.
