import type { Metadata } from "next";
import { Geist } from "next/font/google";
import localFont from "next/font/local";
import { Footer } from "@/components/footer";
import { Header } from "@/components/header";
import { CartProvider } from "@/components/cart-provider";
import { CartPanel } from "@/components/cart-panel";
import { getSiteContent } from "@/lib/api";
import "./globals.css";

const gaian = localFont({
  src: "./fonts/Gaian-Regular.woff2",
  weight: "400",
  style: "normal",
  variable: "--font-gaian",
  display: "swap",
  fallback: ["Georgia", "serif"],
});

const southCoast = localFont({
  src: "./fonts/SouthCoast-Regular.woff2",
  weight: "400",
  style: "normal",
  variable: "--font-south-coast",
  display: "swap",
  preload: false,
  adjustFontFallback: false,
  // The script's glyphs sit small on the em; scale them up optically so headings
  // read at their intended size without inflating every font-size declaration.
  declarations: [{ prop: "size-adjust", value: "145%" }],
  fallback: ["cursive"],
});

const geist = Geist({
  variable: "--font-geist",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://hellohoneysummer.com"),
  title: {
    default: "Honey Summer | Locally Grown Flowers in NEPA",
    template: "%s | Honey Summer",
  },
  description:
    "Seasonal flowers, garden-inspired floral design, and florist wholesale in Mountain Top and Northeast Pennsylvania.",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const content = await getSiteContent();
  return (
    <html
      lang="en"
      className={`${gaian.variable} ${southCoast.variable} ${geist.variable}`}
      data-scroll-behavior="smooth"
    >
      <body>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        <CartProvider><div className="site-shell">
          <Header />
          <main id="main-content">{children}</main>
           <Footer content={content} />
        </div><CartPanel /></CartProvider>
      </body>
    </html>
  );
}
