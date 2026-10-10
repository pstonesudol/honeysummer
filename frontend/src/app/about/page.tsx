import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { Heart, Leaf, Scissors } from "lucide-react";

import { site } from "@/lib/site";
import { getSiteContent, sitePhoto } from "@/lib/api";

export const metadata: Metadata = {
  title: "Our Story",
  description:
    "Honey Summer is a seasonal flower farm and floral design studio in Mountain Top, Pennsylvania, growing specialty cut flowers for everyday moments, weddings, and local florists.",
};

const values = [
  {
    icon: Leaf,
    title: "Grown right here",
    body: "Every stem is planted, tended, and cut by hand on our small farm in Mountain Top. Nothing travels far to reach you.",
  },
  {
    icon: Heart,
    title: "Led by the season",
    body: "We design with what the garden is offering that week. The palette shifts from spring ranunculus to the last dahlias of fall.",
  },
  {
    icon: Scissors,
    title: "Gathered with intention",
    body: "Loose, romantic, garden-inspired arrangements that feel like they were just carried in from the field.",
  },
];

export default async function AboutPage() {
  const content = await getSiteContent();
  return (
    <>
      <section className="page-hero section-wrap" aria-labelledby="about-title">
        <div className="page-hero__copy">
          <p className="eyebrow">Our story</p>
          <h1 id="about-title">
            Grown slowly, gathered with <em>care.</em>
          </h1>
          <p className="hero__lede">
             {content.aboutIntro || <>Honey Summer is a one-woman flower farm and design studio. We grow specialty cut flowers in {content.location || site.location} and shape them into loose, romantic designs for the people and celebrations around us.</>}
          </p>
        </div>
        <div className="page-hero__art">
          <Image
            src="/images/photography/founder-in-garden.jpg"
            alt="Isabella standing in the garden with a basket of flowers"
            width={800}
            height={1200}
            priority
            sizes="(max-width: 850px) 92vw, 42vw"
            {...sitePhoto(content, "about")}
          />
        </div>
      </section>

      <section className="story section-wrap" aria-labelledby="story-title">
        <div className="story__copy">
          <p className="eyebrow">How it started</p>
          <h2 id="story-title">It began with a cutting garden that kept growing.</h2>
          <p>
            What started as a few rows of flowers for the kitchen table turned
            into a field full of color and a reason to share it. Honey Summer
            grew out of that first season — the joy of watching something small
            become a bouquet in someone&rsquo;s hands.
          </p>
          <p>
            Today Isabella grows, cuts, and designs every arrangement, working
            with the weather, the pollinators, and the slow rhythm of the
            garden. When a flower is not ready, we wait for it or reach for
            another local grower — never for a shipped-in substitute.
          </p>
        </div>
        <div className="story__art">
          <Image
            src="/images/photography/cutting-dahlias-monochrome.jpg"
            alt="Hands cutting a dahlia stem in the garden"
            width={800}
            height={1200}
            sizes="(max-width: 850px) 92vw, 42vw"
          />
        </div>
      </section>

      <section className="value-grid section-wrap" aria-label="What guides our work">
        {values.map((value) => (
          <article className="value-card" key={value.title}>
            <value.icon aria-hidden="true" size={22} strokeWidth={1.5} />
            <h3>{value.title}</h3>
            <p>{value.body}</p>
          </article>
        ))}
      </section>

      <section className="cta-band section-wrap">
        <div>
          <p className="eyebrow">Come say hello</p>
          <h2>There is usually something blooming.</h2>
        </div>
        <div className="button-row">
          <Link className="button button--primary" href="/order-flowers">
            Order flowers
          </Link>
          <Link className="button button--quiet" href="/weddings">
            Weddings &amp; events
          </Link>
        </div>
      </section>
    </>
  );
}
