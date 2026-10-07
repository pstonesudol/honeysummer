import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Heart } from "lucide-react";

export default function Home() {
  return (
    <>
      <section className="hero section-wrap" aria-labelledby="hero-title">
        <div className="hero__copy">
          <p className="eyebrow">Mountain Top · Northeast Pennsylvania</p>
          <h1 id="hero-title">
            Flowers grown with the <em>seasons.</em>
          </h1>
          <p className="hero__lede">
            Locally grown blooms and garden-inspired floral design for the
            everyday, meaningful gatherings, and the florists who make magic.
          </p>
          <div className="button-row">
            <Link className="button button--primary" href="/order-flowers">
              Order flowers
            </Link>
            <Link className="button button--quiet" href="/about">
              Our story
              <ArrowRight aria-hidden="true" size={16} strokeWidth={1.8} />
            </Link>
          </div>
        </div>
        <div className="hero__art">
          <div className="hero__image-wrap">
            <Image
              src="/images/flower-field-placeholder.svg"
              alt="Illustrated placeholder for a field of locally grown flowers"
              fill
              priority
              sizes="(max-width: 768px) 92vw, 48vw"
            />
          </div>
          <p className="handwritten-note" aria-hidden="true">
            grown right here <Heart size={22} strokeWidth={1.5} />
          </p>
        </div>
      </section>

      <section className="intro section-wrap">
        <p className="eyebrow">From our little flower farm</p>
        <h2>Seasonal beauty, thoughtfully gathered.</h2>
        <p>
          Honey Summer grows specialty cut flowers and creates loose, romantic
          designs that celebrate what is blooming now.
        </p>
      </section>

      <section className="pathways section-wrap" aria-label="Ways to shop">
        <article className="pathway-card pathway-card--pink">
          <span className="pathway-card__number">01</span>
          <h2>Flowers for your table</h2>
          <p>Fresh seasonal bouquets and special flower moments, grown nearby.</p>
          <Link href="/order-flowers">
            Order flowers
            <ArrowRight aria-hidden="true" size={14} strokeWidth={1.8} />
          </Link>
        </article>
        <article className="pathway-card pathway-card--gold">
          <span className="pathway-card__number">02</span>
          <h2>Flowers for your day</h2>
          <p>Garden-inspired wedding and event florals made just for you.</p>
          <Link href="/weddings">
            Weddings &amp; events
            <ArrowRight aria-hidden="true" size={14} strokeWidth={1.8} />
          </Link>
        </article>
        <article className="pathway-card pathway-card--taupe">
          <span className="pathway-card__number">03</span>
          <h2>Flowers for your work</h2>
          <p>Fresh, local stems for floral designers across Northeast PA.</p>
          <Link href="/wholesale">
            Florist wholesale
            <ArrowRight aria-hidden="true" size={14} strokeWidth={1.8} />
          </Link>
        </article>
      </section>

      <section className="season-note section-wrap">
        <div>
          <p className="eyebrow">Rooted in season</p>
          <h2>No two weeks in the garden look quite the same.</h2>
        </div>
        <p>
          Our offerings shift with the weather and the garden—from spring
          ranunculus to the last dahlias of fall. That natural rhythm is part of
          what makes locally grown flowers so special.
        </p>
      </section>
    </>
  );
}
