"use client";

import type { FlowerListing } from "@/lib/api";
import Image from "next/image";
import { useCart } from "./cart-provider";

export function ProductGrid({ flowers, channel }: { flowers: FlowerListing[]; channel: "retail" | "wholesale" }) {
  const cart = useCart();
  return <div className="flower-grid">{flowers.map((flower) => <article className="flower-card" key={flower.id}>
    {flower.photo_url ? <Image src={flower.photo_url} alt="" width={600} height={750} unoptimized /> : <div className="flower-card__placeholder">✿</div>}
    <div className="flower-card__body"><p className="eyebrow">{flower.color || "Seasonal"}</p><h3>{flower.name}</h3><p>{flower.variety}{flower.stem_notes ? ` · ${flower.stem_notes}` : ""}</p><strong>${flower.price} / {flower.unit}</strong>
      {Number(flower.delivery_fee) > 0 && <p>Delivery: ${flower.delivery_fee} {flower.delivery_fee_mode === "per_unit" ? "/ unit" : flower.delivery_fee_mode === "per_order" ? "/ order" : "/ listing"}</p>}
      <p>{flower.quantity_available} {flower.unit} available</p>
      {flower.available ? <button className="button button--dark" disabled={!cart.ready} onClick={() => cart.add(channel, flower)}>Add to {channel} cart<span className="sr-only">: {flower.name}</span></button> : <span className="sold-out">Sold out</span>}
    </div>
  </article>)}</div>;
}

export function RetailShop({ flowers, checkoutStatus = null }: { flowers: FlowerListing[]; checkoutStatus?: "success" | "cancelled" | null; pickupWindow?: string }) {
  return <div className="retail-shop">
    {checkoutStatus && <p className="retail-notice" role="status">{checkoutStatus === "success" ? "Thank you. We are checking payment confirmation; your cart updates only after verified payment." : "Your cart is saved. Resume your existing checkout or cancel the unpaid reservation from retail checkout."}</p>}
    {flowers.length ? <ProductGrid flowers={flowers} channel="retail" /> : <p className="retail-shop__empty">Nothing is listed for online ordering this week. Send a custom request below and we will make something just for you.</p>}
  </div>;
}
