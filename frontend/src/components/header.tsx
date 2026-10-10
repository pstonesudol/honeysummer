import Link from "next/link";
import { Menu } from "lucide-react";
import { AnnouncementBanner } from "./announcement-banner";
import { BrandMark } from "./brand-mark";
import { CartButton } from "./cart-panel";

const navigation = [
  { href: "/about", label: "About" },
  { href: "/order-flowers", label: "Order Flowers" },
  { href: "/weddings", label: "Weddings & Events" },
  { href: "/wholesale", label: "Wholesale" },
  { href: "/contact", label: "Contact" },
];

export function Header() {
  return (
    <>
      <AnnouncementBanner />
      <header className="site-header section-wrap">
        <BrandMark />
        <nav className="desktop-nav" aria-label="Main navigation">
          {navigation.map((item) => (
            <Link href={item.href} key={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="header-actions"><CartButton /><details className="mobile-nav">
          <summary aria-label="Open navigation">
            <Menu aria-hidden="true" size={16} strokeWidth={1.8} />
            <span>Menu</span>
          </summary>
          <nav aria-label="Mobile navigation">
            {navigation.map((item) => (
              <Link href={item.href} key={item.href}>
                {item.label}
              </Link>
            ))}
          </nav>
        </details></div>
      </header>
    </>
  );
}
