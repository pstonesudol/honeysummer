import type { Metadata } from "next";
import Link from "next/link";
import { Check, Heart } from "lucide-react";

export const metadata: Metadata = {
  title: "Thank you",
  description: "Your note has reached Honey Summer.",
  robots: { index: false },
};

type ThankYouCopy = {
  heading: string;
  body: string;
};

const messages: Record<string, ThankYouCopy> = {
  bouquet: {
    heading: "Your flower request is on its way to the garden.",
    body: "Isabella will reply within a few days to confirm what is blooming and arrange pickup or delivery.",
  },
  wedding: {
    heading: "Thank you for sharing your day with us.",
    body: "We will follow up with availability, ideas, and a custom quote. In the meantime, feel free to send any inspiration photos along.",
  },
  contact: {
    heading: "Your message has arrived.",
    body: "We read every note personally and will get back to you within a few days.",
  },
  wholesale: {
    heading: "Thank you for your interest in wholesale.",
    body: "We will review your request and follow up with account details once you are approved.",
  },
};

const fallback: ThankYouCopy = {
  heading: "Thank you for reaching out.",
  body: "Your message has arrived safely and we will be in touch soon.",
};

export default async function ThankYouPage({
  searchParams,
}: {
  searchParams: Promise<{ type?: string }>;
}) {
  const { type } = await searchParams;
  const copy = (type && messages[type]) || fallback;

  return (
    <section className="thank-you section-wrap" aria-labelledby="thank-you-title">
      <span className="thank-you__badge" aria-hidden="true">
        <Check size={26} strokeWidth={1.8} />
      </span>
      <p className="eyebrow">Message received</p>
      <h1 id="thank-you-title">{copy.heading}</h1>
      <p className="thank-you__body">{copy.body}</p>
      <div className="button-row">
        <Link className="button button--primary" href="/">
          Back to the garden
        </Link>
        <Link className="button button--quiet" href="/order-flowers">
          Order more flowers
          <Heart aria-hidden="true" size={16} strokeWidth={1.8} />
        </Link>
      </div>
    </section>
  );
}
