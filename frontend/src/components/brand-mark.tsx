import Link from "next/link";

export function BrandMark() {
  return (
    <Link className="brand-mark" href="/" aria-label="Honey Summer home">
      <span className="brand-mark__name">Honey Summer</span>
      <span className="brand-mark__tagline">Flower Farm &amp; Floral Design</span>
    </Link>
  );
}
