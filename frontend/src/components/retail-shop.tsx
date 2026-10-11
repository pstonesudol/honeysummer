"use client";

import { useId, useState } from "react";
import type { FlowerListing } from "@/lib/api";
import Image from "next/image";
import { useCart } from "./cart-provider";
import { CheckoutNotice } from "./checkout-notice";

export function ProductGrid({ flowers, channel }: { flowers: FlowerListing[]; channel: "retail" | "wholesale" }) {
  return <div className="flower-grid">{flowers.map((flower) => <ProductCard flower={flower} channel={channel} key={flower.id} />)}</div>;
}

export function RetailShop({ flowers, checkoutStatus = null }: { flowers: FlowerListing[]; checkoutStatus?: "success" | "cancelled" | null; pickupWindow?: string }) {
  return <div className="retail-shop">
    {checkoutStatus && <CheckoutNotice channel="retail" checkoutStatus={checkoutStatus} />}
    {flowers.length ? <ProductGrid flowers={flowers} channel="retail" /> : <p className="retail-shop__empty">Nothing is listed for online ordering this week. Send a custom request below and we will make something just for you.</p>}
  </div>;
}

function ProductCard({ flower, channel }: { flower: FlowerListing; channel: "retail" | "wholesale" }) {
  const cart = useCart();
  const inputId = useId();
  const line = cart.carts[channel].items[flower.id];
  const inCart = (line?.quantity ?? 0) > 0;
  // How many to add on the next "Add to cart"; once in the cart the input mirrors the saved quantity.
  const [pending, setPending] = useState(1);
  const max = Math.max(1, Math.min(9999, flower.quantity_available));
  const quantity = inCart ? line.quantity : pending;
  const change = (value: number) => {
    const next = Math.max(0, Math.min(max, Math.floor(value || 0)));
    setPending(next || 1);
    if (inCart) cart.quantity(channel, flower.id, next);
  };
  const remove = () => {
    setPending(Math.max(1, line?.quantity ?? 1));
    cart.quantity(channel, flower.id, 0);
  };
  return <article className="flower-card">
    {flower.photo_url ? <Image src={flower.photo_url} alt="" width={600} height={750} unoptimized /> : <div className="flower-card__placeholder">✿</div>}
    <div className="flower-card__body"><p className="eyebrow">{flower.color || "Seasonal"}</p><h3>{flower.name}</h3><p>{flower.variety}{flower.stem_notes ? ` · ${flower.stem_notes}` : ""}</p><strong>${flower.price} / {flower.unit}</strong>
      {Number(flower.delivery_fee) > 0 && <p>Delivery: ${flower.delivery_fee} {flower.delivery_fee_mode === "per_unit" ? "/ unit" : flower.delivery_fee_mode === "per_order" ? "/ order" : "/ listing"}</p>}
      <p>{flower.quantity_available} {flower.unit} available</p>
      {flower.available ? <>
        <div className="flower-card__quantity">
          <label htmlFor={inputId}>Quantity<span className="sr-only"> for {flower.name}</span></label>
          <input id={inputId} type="number" inputMode="numeric" min={inCart ? 0 : 1} max={max} value={quantity} disabled={!cart.ready} onChange={(event) => change(Number(event.target.value))} />
        </div>
        {inCart
          ? <button type="button" className="button button--quiet" disabled={!cart.ready} onClick={remove}>Remove from {channel} cart<span className="sr-only">: {flower.name}</span></button>
          : <button className="button button--dark" disabled={!cart.ready || pending < 1} onClick={() => cart.add(channel, flower, pending)}>Add to {channel} cart<span className="sr-only">: {flower.name}</span></button>}
      </> : <span className="sold-out">Sold out</span>}
    </div>
  </article>;
}
