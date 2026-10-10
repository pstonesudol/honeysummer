import Image from "next/image";

import { getGallery } from "@/lib/api";

const featuredPhotos = [
  {
    src: "/images/photography/garden-arrangement.jpg",
    alt: "Colorful garden flowers arranged in a low bowl outdoors",
    caption: "Garden-inspired arrangements",
  },
  {
    src: "/images/photography/gathered-basket-bouquet.jpg",
    alt: "A basket overflowing with pink and white seasonal flowers",
    caption: "Gathered by hand",
  },
  {
    src: "/images/photography/flower-bucket-detail.jpg",
    alt: "A flower bucket filled with orange dahlias and white hydrangeas",
    caption: "The season's best blooms",
  },
  {
    src: "/images/photography/flowers-in-the-meadow.jpg",
    alt: "Flower arrangements displayed on wooden chairs in the meadow",
    caption: "Flowers in the meadow",
  },
  {
    src: "/images/photography/hand-tied-stems.jpg",
    alt: "A hand-tied posy held up against the sky",
    caption: "A little something to carry",
  },
  {
    src: "/images/photography/floral-arrangement-monochrome.jpg",
    alt: "Black-and-white photograph of a woman holding a bowl of flowers",
    caption: "Designed with intention",
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
              style={{ objectPosition: `${image.focal_x ?? 50}% ${image.focal_y ?? 50}%` }}
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
      {featuredPhotos.map((photo) => (
        <figure className="gallery-item" key={photo.src}>
          <Image
            src={photo.src}
            alt={photo.alt}
            width={800}
            height={1000}
            sizes="(max-width: 850px) 100vw, 33vw"
          />
          <figcaption>{photo.caption}</figcaption>
        </figure>
      ))}
    </div>
  );
}
