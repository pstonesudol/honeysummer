import Link from "next/link";
import type { SiteContent } from "@/lib/api";
import { BrandMark } from "./brand-mark";

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
            <Link href="/contact">Contact &amp; FAQ</Link>
            <Link href="/wholesale">Florist wholesale</Link>
             {content.instagram ? <a href={content.instagram} target="_blank" rel="noopener noreferrer">Instagram</a> : <span>Instagram coming soon</span>}
          </div>
        </div>
      </div>
      <div className="site-footer__bottom section-wrap">
        <span>© {new Date().getFullYear()} Honey Summer</span>
        <span>Made with care in Northeast PA</span>
      </div>
    </footer>
  );
}
