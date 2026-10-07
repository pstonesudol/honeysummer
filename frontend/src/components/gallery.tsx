import Image from "next/image";

import { getGallery } from "@/lib/api";

const placeholders = [
  {
    src: "/images/wedding-placeholder.svg",
    alt: "Illustrated placeholder for garden-inspired ceremony flowers",
    caption: "Ceremony flowers, grown nearby",
  },
  {
    src: "/images/bouquet-placeholder.svg",
    alt: "Illustrated placeholder for a seasonal bridal bouquet",
    caption: "Bouquets gathered by hand",
  },
  {
    src: "/images/studio-placeholder.svg",
    alt: "Illustrated placeholder for a floral design studio worktable",
    caption: "Designed in the studio",
  },
  {
    src: "/images/harvest-placeholder.svg",
    alt: "Illustrated placeholder for a field of cut flowers at harvest",
    caption: "Harvested the morning of your event",
  },
];

export async function Gallery() {
  const images = await getGallery();

  if (images.length > 0) {
    return (
      <div className="gallery-grid">
        {images.map((image) => (
          <figure className="gallery-item" key={image.id}>
            {/* Admin-uploaded media is served by the API, so it is not part of the Next.js image pipeline. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={image.image}
              alt={image.alt_text || image.caption || "Honey Summer floral design"}
              loading="lazy"
              decoding="async"
            />
            {image.caption ? <figcaption>{image.caption}</figcaption> : null}
          </figure>
        ))}
      </div>
    );
  }

  return (
    <div className="gallery-grid">
      {placeholders.map((placeholder) => (
        <figure className="gallery-item" key={placeholder.src}>
          <Image
            src={placeholder.src}
            alt={placeholder.alt}
            width={800}
            height={1000}
            sizes="(max-width: 850px) 100vw, 33vw"
          />
          <figcaption>{placeholder.caption}</figcaption>
        </figure>
      ))}
    </div>
  );
}
