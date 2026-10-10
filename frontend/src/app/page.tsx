import Image from "next/image";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { getSiteContent, sitePhoto } from "@/lib/api";

export default async function Home() {
  const content = await getSiteContent();
  return (
    <>
      <section className="hero" aria-labelledby="hero-title">
        <Image
          className="hero__photo"
          src="/images/photography/flowers-in-the-meadow.jpg"
          alt="Seasonal flower arrangements set among the grasses in a meadow"
          fill
          priority
          sizes="100vw"
          {...sitePhoto(content, "home")}
        />
        <div className="hero__copy section-wrap">
          <p className="eyebrow">Mountain Top · Northeast Pennsylvania</p>
          <h1 id="hero-title">
            Flowers grown with the <em>seasons.</em>
          </h1>
          <p className="hero__lede">
             {content.homeIntro || "Locally grown blooms and garden-inspired floral design for the everyday, meaningful gatherings, and the florists who make magic."}
          </p>
          <div className="button-row">
            <Link className="button button--light" href="/order-flowers">
              Order flowers
            </Link>
            <Link className="button button--outline-light" href="/about">
              Our story
              <ArrowRight aria-hidden="true" size={16} strokeWidth={1.8} />
            </Link>
          </div>
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
          <div className="pathway-card__photo">
            <Image
              src="/images/photography/flower-bucket-portrait.jpg"
              alt="A bucket of freshly gathered seasonal flowers"
              fill
              sizes="(max-width: 850px) 92vw, 30vw"
              {...sitePhoto(content, "homeFlowers")}
            />
          </div>
          <div className="pathway-card__body">
            <span className="pathway-card__number">01</span>
            <h2>Flowers for your table</h2>
            <p>Fresh seasonal bouquets and special flower moments, grown nearby.</p>
            <Link href="/order-flowers">
              Order flowers
              <ArrowRight aria-hidden="true" size={14} strokeWidth={1.8} />
            </Link>
          </div>
        </article>
        <article className="pathway-card pathway-card--gold">
          <div className="pathway-card__photo">
            <Image
              src="/images/photography/garden-arrangement-portrait.jpg"
              alt="A garden-style arrangement of dahlias and other blooms"
              fill
              sizes="(max-width: 850px) 92vw, 30vw"
              {...sitePhoto(content, "homeWeddings")}
            />
          </div>
          <div className="pathway-card__body">
            <span className="pathway-card__number">02</span>
            <h2>Flowers for your day</h2>
            <p>Garden-inspired wedding and event florals made just for you.</p>
            <Link href="/weddings">
              Weddings &amp; events
              <ArrowRight aria-hidden="true" size={14} strokeWidth={1.8} />
            </Link>
          </div>
        </article>
        <article className="pathway-card pathway-card--taupe">
          <div className="pathway-card__photo">
            <Image
              src="/images/photography/hand-tied-stems.jpg"
              alt="Freshly cut stems held up in the garden"
              fill
              sizes="(max-width: 850px) 92vw, 30vw"
              {...sitePhoto(content, "homeWholesale")}
            />
          </div>
          <div className="pathway-card__body">
            <span className="pathway-card__number">03</span>
            <h2>Flowers for your work</h2>
            <p>Fresh, local stems for floral designers across Northeast PA.</p>
            <Link href="/wholesale">
              Florist wholesale
              <ArrowRight aria-hidden="true" size={14} strokeWidth={1.8} />
            </Link>
          </div>
        </article>
      </section>

      <section className="home-feature" aria-labelledby="home-feature-title">
        <Image
          src="/images/photography/floral-arrangement-monochrome.jpg"
          alt="Black-and-white portrait of a woman holding an arrangement of garden flowers"
          fill
          sizes="100vw"
        />
        <div className="home-feature__copy section-wrap">
          <p className="eyebrow">Made with the season</p>
          <h2 id="home-feature-title">
            Flowers with a little more <em>feeling.</em>
          </h2>
          <p>
            Gathered close to home and designed for the moments you want to remember.
          </p>
          <Link className="button button--light" href="/weddings">
            Explore weddings &amp; events
            <ArrowRight aria-hidden="true" size={16} strokeWidth={1.8} />
          </Link>
        </div>
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
