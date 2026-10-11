/**
 * The Instagram brand glyph.
 *
 * lucide-react ships only generic outline icons, not brand marks, so the
 * Instagram logo is drawn inline here. It follows the design system's icon
 * rules: an outline glyph at the given stroke width, decorative when paired
 * with visible text (`aria-hidden`), and labelled by its parent when standalone.
 */
export function InstagramIcon({
  size = 16,
  strokeWidth = 1.8,
  className,
}: {
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="2" y="2" width="20" height="20" rx="5.5" />
      <circle cx="12" cy="12" r="4.2" />
      <circle cx="17.4" cy="6.6" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  );
}
