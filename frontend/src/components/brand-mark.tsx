import Image from "next/image";
import Link from "next/link";

export function BrandMark({
  variant = "default",
}: {
  variant?: "default" | "light";
}) {
  const src =
    variant === "light"
      ? "/brand/honey-summer-logo-light.png"
      : "/brand/honey-summer-logo.png";

  return (
    <Link className="brand-mark" href="/" aria-label="Honey Summer home">
      <Image
        className="brand-mark__logo"
        src={src}
        alt=""
        width={900}
        height={601}
        priority={variant === "default"}
      />
      <span className="brand-mark__tagline">Flower Farm &amp; Floral Design</span>
    </Link>
  );
}
