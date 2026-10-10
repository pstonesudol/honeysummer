import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { CalendarHeart, Flower2, PackageCheck } from "lucide-react";

import { InquiryForm } from "@/components/inquiry-form";
import { RetailShop } from "@/components/retail-shop";
import { getRetailFlowers, getSiteContent, sitePhoto } from "@/lib/api";
import { inquiryIntros } from "@/lib/inquiry-fields";
import { pickup, site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Order Flowers",
  description:
    "Order a seasonal bouquet from Honey Summer or request a custom arrangement, grown in Mountain Top, PA and available for pickup or delivery across Northeast Pennsylvania.",
};

const steps = [
  {
    icon: Flower2,
    title: "Share what you have in mind",
    body: "Tell us the occasion, colors, and budget. There are no wrong answers — we love a loose idea.",
  },
  {
    icon: CalendarHeart,
    title: "We confirm what is blooming",
    body: "Isabella replies with what the garden is offering that week and a price for your arrangement.",
  },
  {
    icon: PackageCheck,
    title: "Pick up or have it delivered",
    body: `Collect your flowers from the farm, or arrange delivery across ${site.serviceArea}`,
  },
];

export default async function OrderFlowersPage({
  searchParams,
}: {
  searchParams: Promise<{ checkout?: string }>;
}) {
  const [{ checkout }, flowers, content] = await Promise.all([
    searchParams,
    getRetailFlowers(),
    getSiteContent(),
  ]);
  const checkoutStatus =
    checkout === "success" || checkout === "cancelled" ? checkout : null;

  return (
    <>
      <section className="page-hero section-wrap" aria-labelledby="order-title">
        <div className="page-hero__copy">
          <p className="eyebrow">Fresh from the garden</p>
          <h1 id="order-title">
            Flowers for your <em>table.</em>
          </h1>
          <p className="hero__lede">
             {content.orderIntro || "Bouquets and arrangements gathered from whatever is at its peak this week — locally grown, thoughtfully designed, and ready to brighten an ordinary day."}
          </p>
          <div className="button-row">
            <Link className="button button--primary" href="#shop">
              Shop what is ready
            </Link>
            <Link className="button button--quiet" href="/weddings">
              Planning a wedding?
            </Link>
          </div>
        </div>
        <div className="page-hero__art">
          <div className="page-hero__image page-hero__image--round">
            <Image
              src="/images/photography/flower-bucket-portrait.jpg"
              alt="A bucket overflowing with orange dahlias and white hydrangeas"
              width={800}
              height={1200}
              priority
              sizes="(max-width: 850px) 92vw, 42vw"
              {...sitePhoto(content, "order")}
            />
          </div>
        </div>
      </section>

      <section className="section-wrap" id="shop" aria-labelledby="offerings-title">
        <div className="section-intro">
          <p className="eyebrow">Available this week</p>
          <h2 id="offerings-title">Ready-to-order flowers.</h2>
          <p>
            Standard bouquets and arrangements appear here as the season allows.
            Reserve one for pickup or delivery and check out in a moment.
            Because everything is grown outdoors, availability follows the
            weather and changes week to week.
          </p>
        </div>
         <RetailShop flowers={flowers} checkoutStatus={checkoutStatus} pickupWindow={content.pickupWindow || pickup.window} />
      </section>

      <section className="steps section-wrap" aria-label="How custom orders work">
        {steps.map((step, index) => (
          <article className="step-card" key={step.title}>
            <span className="step-card__number">{String(index + 1).padStart(2, "0")}</span>
            <step.icon aria-hidden="true" size={22} strokeWidth={1.5} />
            <h2>{step.title}</h2>
            <p>{step.body}</p>
          </article>
        ))}
      </section>

      <section className="form-section section-wrap" id="inquiry" aria-labelledby="inquiry-title">
        <div className="form-section__intro">
          <p className="eyebrow">Custom request</p>
          <h2 id="inquiry-title">Tell us what you are dreaming of.</h2>
          <p>{inquiryIntros.bouquet}</p>
          <ul className="form-section__list">
            <li>Pickup at the farm or delivery nearby</li>
            <li>Seasonal stems chosen at their peak</li>
            <li>A reply within a few days</li>
          </ul>
        </div>
        <InquiryForm kind="bouquet" submitLabel="Send request" />
      </section>

      <section className="cta-band section-wrap">
        <div>
          <p className="eyebrow">Good to know</p>
           <h2>Pickup happens at the farm in {(content.location || site.location).split(",")[0]}.</h2>
        </div>
        <p className="cta-band__note">
           {content.pickupWindow || pickup.window} {content.pickupNote || pickup.note}
        </p>
      </section>
    </>
  );
}
