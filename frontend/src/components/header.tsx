import Link from "next/link";
import { Menu } from "lucide-react";
import { BrandMark } from "./brand-mark";

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
      <div className="announcement">
        <p>Our growing season is waking up — spring flowers coming soon</p>
      </div>
      <header className="site-header section-wrap">
        <BrandMark />
        <nav className="desktop-nav" aria-label="Main navigation">
          {navigation.map((item) => (
            <Link href={item.href} key={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
        <details className="mobile-nav">
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
        </details>
      </header>
    </>
  );
}
