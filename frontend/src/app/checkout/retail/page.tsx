import { ChannelCheckout } from "@/components/cart-panel";

export const metadata = { title: "Retail checkout", robots: { index: false, follow: false } };
export default function RetailCheckoutPage() {
  return <section className="section-wrap checkout-page"><p className="eyebrow">Your flowers</p><h1>Retail checkout</h1><ChannelCheckout channel="retail" /></section>;
}
