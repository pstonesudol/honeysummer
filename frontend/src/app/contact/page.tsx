import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { Camera, Mail, MapPin } from "lucide-react";

import { InquiryForm } from "@/components/inquiry-form";
import { getSiteContent, sitePhoto } from "@/lib/api";
import { inquiryIntros } from "@/lib/inquiry-fields";
import { pickup, site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Contact & FAQ",
  description:
    "Get in touch with Honey Summer in Mountain Top, PA, and find answers about seasonal availability, pickup and delivery, custom requests, weddings, and wholesale.",
};

const faqs = [
  {
    question: "Where is Honey Summer located?",
    answer: (
      <>
        We are in {site.location}. Our growing space is not open to the public
        unless we announce an open day, but pickup can be arranged at the farm.
      </>
    ),
  },
  {
    question: "When are flowers available?",
    answer: (
      <>
        Our season runs roughly from spring through the first frost, and what is
        blooming changes week to week. The best way to know what is ready is to{" "}
        <Link href="/order-flowers">send a request</Link>.
      </>
    ),
  },
  {
    question: "Do you offer pickup or delivery?",
    answer: (
      <>
        Both. Pickup happens at the farm, and delivery is available across{" "}
        {site.serviceArea} for a fee. Tell us your preference in the{" "}
        <Link href="/order-flowers">order form</Link>.
      </>
    ),
  },
  {
    question: "Can I request something custom?",
    answer: (
      <>
        Absolutely. Share the occasion, colors, and budget in the{" "}
        <Link href="/order-flowers">custom request form</Link> and we will
        design around what is at its peak.
      </>
    ),
  },
  {
    question: "How much lead time do you need?",
    answer: (
      <>
        A few days is usually plenty for a bouquet. Weddings and larger events
        book months ahead, especially for peak spring and fall dates —{" "}
        <Link href="/weddings">start an inquiry</Link> as early as you can.
      </>
    ),
  },
  {
    question: "Do you design weddings and events?",
    answer: (
      <>
        Yes — garden-inspired florals for ceremonies, receptions, and
        celebrations of every size. See{" "}
        <Link href="/weddings">Weddings &amp; Events</Link> for offerings and
        the inquiry form.
      </>
    ),
  },
  {
    question: "What are DIY flower buckets and the Honey Pot?",
    answer: (
      <>
        DIY buckets are loose, seasonal stems for hosts who want to arrange
        their own flowers. The Honey Pot is a gathered arrangement in a
        keepsake vessel. Both can be requested through the{" "}
        <Link href="/order-flowers">order form</Link>.
      </>
    ),
  },
  {
    question: "How do florists get wholesale access?",
    answer: (
      <>
        Florists can request an account on the{" "}
        <Link href="/wholesale">wholesale page</Link>. Once approved, they can
        sign in with the password they chose to see live availability and pricing.
      </>
    ),
  },
];

export default async function ContactPage() {
  const content = await getSiteContent();
  return (
    <>
      <section className="page-hero section-wrap" aria-labelledby="contact-title">
        <div className="page-hero__copy">
          <p className="eyebrow">Say hello</p>
          <h1 id="contact-title">
            We would love to <em>hear from you.</em>
          </h1>
          <p className="hero__lede">
             {content.contactIntro || "Questions about flowers, weddings, or wholesale? Send a note and Isabella will reply within a few days."}
          </p>
        </div>
        <div className="page-hero__art">
          <div className="page-hero__image page-hero__image--round">
            <Image
              src="/images/photography/walking-through-garden.jpg"
              alt="Isabella walking through the garden with flowers in hand"
              width={800}
              height={1200}
              priority
              sizes="(max-width: 850px) 92vw, 42vw"
              {...sitePhoto(content, "contact")}
            />
          </div>
        </div>
      </section>

      <section className="contact-grid section-wrap" aria-label="Contact details">
        <article className="contact-card">
          <Mail aria-hidden="true" size={20} strokeWidth={1.5} />
          <h2>Email</h2>
           <a href={`mailto:${content.email || site.email}`}>{content.email || site.email}</a>
        </article>
        <article className="contact-card">
          <MapPin aria-hidden="true" size={20} strokeWidth={1.5} />
          <h2>Where we grow</h2>
           <p>{content.pickupLocation || pickup.location}</p>
        </article>
        <article className="contact-card">
          <Camera aria-hidden="true" size={20} strokeWidth={1.5} />
          <h2>Follow along</h2>
           <p>{content.instagram ? <a href={content.instagram} target="_blank" rel="noopener noreferrer">Instagram</a> : "Instagram coming soon — we will link it here."}</p>
        </article>
      </section>

      <section className="form-section section-wrap" id="inquiry" aria-labelledby="contact-form-title">
        <div className="form-section__intro">
          <p className="eyebrow">Send a note</p>
          <h2 id="contact-form-title">How can we help?</h2>
          <p>{inquiryIntros.contact}</p>
        </div>
        <InquiryForm kind="contact" submitLabel="Send message" />
      </section>

      <section className="faq-section section-wrap" aria-labelledby="faq-title">
        <div className="faq-section__intro">
          <p className="eyebrow">Questions</p>
          <h2 id="faq-title">Frequently asked.</h2>
        </div>
        <div className="faq-list">
           {(content.faq?.length ? content.faq : faqs).map((faq) => (
            <details className="faq-item" key={faq.question}>
              <summary>{faq.question}</summary>
              <p>{faq.answer}</p>
            </details>
          ))}
        </div>
      </section>
    </>
  );
}
