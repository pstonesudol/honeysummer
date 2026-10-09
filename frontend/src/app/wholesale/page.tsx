import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { BadgeCheck, Flower2, Truck } from "lucide-react";

import { WholesaleShop } from "@/components/inquiry-form";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Florist Wholesale",
  description:
    "Wholesale, locally grown seasonal flowers for florists and event designers across Northeast Pennsylvania. Request an approved Honey Summer wholesale account.",
};

const benefits = [
  {
    icon: Flower2,
    title: "Fresh, local stems",
    body: "Specialty cut flowers harvested close to your studio, often the same morning they are sold.",
  },
  {
    icon: BadgeCheck,
    title: "Approved accounts only",
    body: "We keep a small list of florists so everyone gets personal attention and fair availability.",
  },
  {
    icon: Truck,
    title: "Pickup & delivery",
    body: "Collect from the farm or arrange delivery with a configurable fee across the region.",
  },
];

const steps = [
  {
    title: "Request access",
    body: "Request an account above, tell us about your business, and choose your own password.",
  },
  {
    title: "We review & approve",
    body: "Isabella reviews your request and emails you when your account is approved.",
  },
  {
    title: "Order what is blooming",
    body: "See live availability, order by the stem or bunch, and get confirmation by email.",
  },
];

export default function WholesalePage() {
  return (
    <>
      <section className="page-hero section-wrap" aria-labelledby="wholesale-title">
        <div className="page-hero__copy">
          <p className="eyebrow">Florist wholesale</p>
          <h1 id="wholesale-title">
            Local flowers for your <em>studio.</em>
          </h1>
          <p className="hero__lede">
            Fresh, seasonal stems for floral designers and event teams across{" "}
            {site.serviceArea} Grown nearby, harvested at their peak, and
            available to approved wholesale accounts.
          </p>
        </div>
        <div className="page-hero__art">
          <div className="page-hero__image page-hero__image--round">
            <Image
              src="/images/photography/hand-tied-stems.jpg"
              alt="Freshly gathered flower stems held up in the garden"
              width={800}
              height={1200}
              priority
              sizes="(max-width: 850px) 92vw, 42vw"
            />
          </div>
        </div>
      </section>

      <WholesaleShop />

      <section className="value-grid section-wrap" aria-label="Why florists work with us">
        {benefits.map((benefit) => (
          <article className="value-card" key={benefit.title}>
            <benefit.icon aria-hidden="true" size={22} strokeWidth={1.5} />
            <h3>{benefit.title}</h3>
            <p>{benefit.body}</p>
          </article>
        ))}
      </section>

      <section className="steps section-wrap" aria-label="How wholesale access works">
        {steps.map((step, index) => (
          <article className="step-card" key={step.title}>
            <span className="step-card__number">{String(index + 1).padStart(2, "0")}</span>
            <h2>{step.title}</h2>
            <p>{step.body}</p>
          </article>
        ))}
      </section>

      <section className="section-wrap wholesale-questions" aria-label="Wholesale questions">
        <p>Have a wholesale question before requesting an account? <Link href="/contact#inquiry">Contact us</Link>.</p>
      </section>
    </>
  );
}
