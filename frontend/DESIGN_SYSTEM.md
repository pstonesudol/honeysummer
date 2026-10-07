# Honey Summer design system

## Status

The Phase 1 UI foundation is complete. Tokens and component conventions below are the implementation baseline. Client photography, final copy, social links, and the licensed Blastine font remain launch assets rather than engineering blockers.

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

- **Fraunces:** display headings and editorial body copy.
- **Geist:** navigation, labels, forms, buttons, and utility copy.
- **Blastine:** wordmark and rare handwritten accents only. Until licensed files are supplied, the stack intentionally falls back to system script fonts.

## Icons

Use `lucide-react` outline icons with rounded strokes. Default to `1.8` stroke width for controls and `1.5` for decorative marks. Icons accompanying visible text are decorative and must use `aria-hidden="true"`; standalone controls require an accessible label.

## Layout and components

- Content width: `1200px` maximum with responsive side gutters.
- Controls: pill-shaped with a minimum 48px target height.
- Cards: generously rounded, cream/taupe/pink surfaces, and restrained cocoa shadows.
- Motion: subtle and optional; always respect `prefers-reduced-motion`.
- Photography: warm, film-inspired treatment with descriptive alternative text.
