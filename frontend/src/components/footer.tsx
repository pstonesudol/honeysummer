import Link from "next/link";
import type { SiteContent } from "@/lib/api";
import { site } from "@/lib/site";
import { BrandMark } from "./brand-mark";
import { InstagramIcon } from "./instagram-icon";

export function Footer({ content = {} }: { content?: SiteContent }) {
  return (
    <footer className="site-footer" id="site-footer">
      <div className="site-footer__inner section-wrap">
        <div className="site-footer__brand">
          <BrandMark variant="light" />
          <p>Seasonal flowers, grown and gathered in Mountain Top, PA.</p>
        </div>
        <div className="site-footer__links">
          <div>
            <h2>Explore</h2>
            <Link href="/about">Our story</Link>
            <Link href="/order-flowers">Order flowers</Link>
            <Link href="/weddings">Weddings &amp; events</Link>
          </div>
          <div>
            <h2>Connect</h2>
            <Link href="/contact#faq">Contact &amp; FAQ</Link>
            <Link href="/wholesale">Florist wholesale</Link>
          </div>
        </div>
      </div>
      <div className="site-footer__bottom section-wrap">
        <span>© {new Date().getFullYear()} Honey Summer</span>
        {(content.instagram || site.instagram) ? (
          <a
            className="site-footer__instagram"
            href={content.instagram || site.instagram}
            target="_blank"
            rel="noopener noreferrer"
          >
            <InstagramIcon size={16} strokeWidth={1.6} />
            Follow on Instagram
          </a>
        ) : (
          <span>Instagram coming soon</span>
        )}
        <span>Made with care in Northeast PA</span>
      </div>
    </footer>
  );
}
