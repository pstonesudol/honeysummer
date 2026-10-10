import type { Metadata } from "next";
import Image from "next/image";
import { Flower2, Gift, Sparkles } from "lucide-react";

import { Gallery } from "@/components/gallery";
import { getSiteContent } from "@/lib/api";
import { InquiryForm } from "@/components/inquiry-form";
import { inquiryIntros } from "@/lib/inquiry-fields";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Weddings & Events",
  description:
    "Garden-inspired wedding and event florals grown and designed by Honey Summer in Mountain Top, PA. Bouquets, ceremony flowers, centerpieces, bouquet bars, and DIY flower buckets.",
};

const offerings = [
  {
    icon: Flower2,
    title: "Personal flowers",
    items: [
      "Bridal and bridesmaid bouquets",
      "Boutonnieres and corsages",
      "Flower crowns and hair blooms",
    ],
  },
  {
    icon: Sparkles,
    title: "Ceremony & reception",
    items: [
      "Ceremony arrangements and aisle flowers",
      "Centerpieces and bud vases",
      "Loose table florals",
    ],
  },
  {
    icon: Gift,
    title: "Gatherings & DIY",
    items: [
      "Bouquet bars",
      "DIY flower buckets",
      "Honey Pot arrangements",
    ],
  },
];

export default async function WeddingsPage() {
  const content = await getSiteContent();
  return (
    <>
      <section className="page-hero section-wrap" aria-labelledby="weddings-title">
        <div className="page-hero__copy">
          <p className="eyebrow">Weddings &amp; events</p>
          <h1 id="weddings-title">
            Flowers for the day you will <em>remember.</em>
          </h1>
          <p className="hero__lede">
             {content.weddingsIntro || "Garden-inspired florals, grown close to home and designed around your colors, your season, and the feeling you want your day to have."}
          </p>
        </div>
        <div className="page-hero__art">
          <div className="page-hero__image page-hero__image--round">
            <Image
              src="/images/photography/floral-arrangement-portrait.jpg"
              alt="Garden-style arrangement with white dahlias and bright seasonal blooms"
              width={800}
              height={1200}
              priority
              sizes="(max-width: 850px) 92vw, 42vw"
            />
          </div>
        </div>
      </section>

      <section className="offerings section-wrap" aria-label="What we design">
        {offerings.map((offering) => (
          <article className="offering-card" key={offering.title}>
            <offering.icon aria-hidden="true" size={22} strokeWidth={1.5} />
            <h2>{offering.title}</h2>
            <ul>
              {offering.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        ))}
      </section>

      <section className="gallery-section section-wrap" aria-labelledby="gallery-title">
        <div className="gallery-section__intro">
          <p className="eyebrow">Recent work</p>
          <h2 id="gallery-title">A little inspiration from the garden.</h2>
          <p>
            A few glimpses of the flowers we grow and the garden-inspired
            arrangements we create. Wedding portfolio photography is on its way.
          </p>
        </div>
        <Gallery />
      </section>

      <section className="season-note section-wrap" aria-labelledby="area-title">
        <div>
          <p className="eyebrow">Where we travel</p>
           <h2 id="area-title">Based in {content.location || site.location}, designing nearby.</h2>
        </div>
        <p>
           We serve {content.serviceArea || site.serviceArea} Travel beyond that is considered case by
          case — just ask. Custom quotes are always welcome.
        </p>
      </section>

      <section className="form-section section-wrap" id="inquiry" aria-labelledby="wedding-inquiry-title">
        <div className="form-section__intro">
          <p className="eyebrow">Wedding &amp; event inquiry</p>
          <h2 id="wedding-inquiry-title">Tell us about your day.</h2>
          <p>{inquiryIntros.wedding}</p>
          <ul className="form-section__list">
            <li>Seasonal, locally grown blooms</li>
            <li>Designs tailored to your palette</li>
            <li>A custom quote after we talk</li>
          </ul>
        </div>
        <InquiryForm kind="wedding" submitLabel="Send inquiry" />
      </section>
    </>
  );
}
