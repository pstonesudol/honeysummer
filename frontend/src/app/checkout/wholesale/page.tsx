import { ChannelCheckout } from "@/components/cart-panel";

export const metadata = { title: "Wholesale checkout", robots: { index: false, follow: false } };
export default function WholesaleCheckoutPage() {
  return <section className="section-wrap checkout-page"><p className="eyebrow">For your studio</p><h1>Wholesale checkout</h1><ChannelCheckout channel="wholesale" /></section>;
}
