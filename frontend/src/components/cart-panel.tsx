"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { ShoppingBag, X, Trash2 } from "lucide-react";
import Image from "next/image";
import { useCart } from "./cart-provider";
import { cartIssues, type Channel } from "@/lib/cart";
import { estimateDeliveryFee } from "@/lib/delivery-fee";

export function CartButton() {
  const cart = useCart();
  const count = (channel: Channel) => Object.values(cart.carts[channel].items).reduce((sum, line) => sum + line.quantity, 0);
  const retail = count("retail"), wholesale = cart.account.approved ? count("wholesale") : 0;
  return <button type="button" className="cart-trigger" disabled={!cart.ready} onClick={() => cart.show()}
    aria-haspopup="dialog" aria-label={cart.account.approved ? `Shopping cart: ${retail} retail items and ${wholesale} wholesale items` : `Your cart: ${retail} items`}>
    <ShoppingBag aria-hidden="true" size={23} />{retail + wholesale > 0 && <span className="cart-badge" aria-hidden="true">{retail + wholesale}</span>}
  </button>;
}

export function CartLines({ channel }: { channel: Channel }) {
  const cart = useCart();
  const items = Object.entries(cart.carts[channel].items).filter(([, line]) => line.quantity > 0);
  const flowers = cart.catalogues[channel];
  const subtotal = items.reduce((total, [id, line]) => total + Math.round(Number(flowers.find((f) => f.id === Number(id))?.price ?? 0) * 100) * line.quantity, 0) / 100;
  if (!items.length) return <div className="cart-empty"><ShoppingBag aria-hidden="true" /><h3>Your {channel} cart is empty.</h3><p>Find something lovely in this week’s flowers.</p><Link className="text-link" href={channel === "retail" ? "/order-flowers" : "/wholesale"} onClick={() => cart.setOpen(false)}>Browse flowers</Link></div>;
  return <><ul className="cart-lines">{items.map(([id, line]) => {
    const flower = flowers.find((f) => f.id === Number(id));
    return <li key={id}>
      {flower?.photo_url ? <Image src={flower.photo_url} alt="" width={72} height={90} unoptimized /> : <span className="cart-thumbnail" aria-hidden="true">✿</span>}
      <div><h3>{flower?.name ?? `Item #${id}`}</h3><p>{flower ? `$${flower.price} / ${flower.unit}` : "Unavailable — remove this item"}</p>
        <label className="cart-quantity">Quantity for {flower?.name ?? `item ${id}`}<input aria-label={`Quantity for ${flower?.name ?? `item ${id}`}`} type="number" min="0" max="9999" value={line.quantity} onChange={(event) => cart.quantity(channel, Number(id), Number(event.target.value))} /></label>
      </div>
      <button className="cart-remove" aria-label={`Remove ${flower?.name ?? `item ${id}`}`} onClick={() => cart.quantity(channel, Number(id), 0)}><Trash2 size={18} aria-hidden="true" /></button>
    </li>;
  })}</ul><p className="cart-subtotal"><span>Subtotal</span><strong>${subtotal.toFixed(2)}</strong></p>
  {cartIssues(cart.carts[channel].items, flowers).map((issue) => <p className="form-status--error" key={issue}>{issue}</p>)}</>;
}

export function CartPanel() {
  const cart = useCart();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!cart.open) return;
    const node = dialog.current;
    const opener = document.activeElement as HTMLElement | null;
    node?.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { node?.close(); document.body.style.overflow = overflow; opener?.focus(); };
  }, [cart.open]);
  const count = (channel: Channel) => Object.values(cart.carts[channel].items).reduce((sum, line) => sum + line.quantity, 0);
  return <><div className="sr-only" role="status" aria-live="polite">{cart.message}</div><dialog ref={dialog} className="cart-panel" aria-labelledby="cart-title" onCancel={() => cart.setOpen(false)} onClick={(event) => { if (event.target === dialog.current) cart.setOpen(false); }} onKeyDown={(event) => {
    if (event.key !== "Tab") return;
    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), [tabindex="0"]')).filter((node) => node.getClientRects().length);
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }}>
    <div className="cart-panel__inner"><div className="cart-panel__heading"><h2 id="cart-title">Your cart</h2><button autoFocus className="cart-remove" aria-label="Close cart" onClick={() => cart.setOpen(false)}><X aria-hidden="true" /></button></div>
      {cart.account.approved ? <><div className="cart-tabs" role="group" aria-label="Choose a separate cart">{(["retail", "wholesale"] as Channel[]).map((channel) => <button key={channel} aria-pressed={cart.selected === channel} onClick={() => cart.show(channel)}>{channel === "retail" ? "Retail" : "Wholesale"} ({count(channel)})</button>)}</div><p className="cart-explanation">Retail and wholesale orders are checked out separately. Your other cart will be saved.</p></> : <p className="cart-explanation"><Link href="/wholesale" onClick={() => cart.setOpen(false)}>Wholesale sign-in / request access</Link></p>}
      <CartLines channel={cart.selected} />
      {cart.message && <p role="status" className="cart-message">{cart.message}</p>}
      {count(cart.selected) > 0 && <Link className="button button--dark cart-checkout" href={`/checkout/${cart.selected}`} onClick={() => cart.setOpen(false)}>Checkout {cart.selected} order</Link>}
      <p className="cart-explanation">Flowers are only reserved when checkout starts. Delivery is calculated for each order separately.</p>
    </div>
  </dialog></>;
}

export function ChannelCheckout({ channel }: { channel: Channel }) {
  const cart = useCart();
  const { validate } = cart;
  const fulfillment = cart.details[channel].fulfillment;
  const field = (name: string) => ({ name, value: cart.details[channel][name] ?? "", onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => cart.updateDetails(channel, name, event.target.value) });
  useEffect(() => { void validate(channel).catch(() => undefined); }, [channel, validate]);
  if (!cart.ready) return <p role="status">Loading your cart…</p>;
  if (channel === "wholesale" && !cart.account.approved) return <p>Wholesale checkout requires an approved account. <Link href="/wholesale">Sign in or request access</Link>.</p>;
  const lines = Object.entries(cart.carts[channel].items).flatMap(([id, line]) => {
    const flower = cart.catalogues[channel].find((f) => f.id === Number(id));
    return flower && line.quantity > 0 ? [{ flower, quantity: line.quantity }] : [];
  });
  const delivery = fulfillment === "delivery" ? estimateDeliveryFee(lines) : 0;
  const subtotal = lines.reduce((sum, line) => sum + Math.round(Number(line.flower.price) * 100) * line.quantity, 0) / 100;
  const pending = cart.carts[channel].attempt;
  return <div className="checkout-layout"><section aria-label={`${channel} order review`}><CartLines channel={channel} /><p>Retail and wholesale orders are checked out separately. Your other cart will be saved.</p></section>
    <form className="inquiry-form" onSubmit={(event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget).entries()) as Record<string, string>; void cart.checkout(channel, { ...data, fulfillment }); }}>
      <h2>Pickup or delivery</h2><div className="form-grid">
        {channel === "retail" && <><div className="form-field"><label htmlFor="checkout-name">Name</label><input id="checkout-name" {...field("name")} autoComplete="name" maxLength={200} required={!pending} /></div><div className="form-field"><label htmlFor="checkout-email">Email</label><input id="checkout-email" {...field("email")} type="email" autoComplete="email" maxLength={254} required={!pending} /></div><div className="form-field"><label htmlFor="checkout-phone">Phone (optional)</label><input id="checkout-phone" {...field("phone")} type="tel" autoComplete="tel" maxLength={40} /></div></>}
        <div className="form-field"><label htmlFor="checkout-fulfillment">Fulfillment</label><select id="checkout-fulfillment" {...field("fulfillment")}><option value="pickup">Pickup at the farm</option><option value="delivery">Delivery</option></select></div>
        {fulfillment === "delivery" ? <div className="form-field"><label htmlFor="checkout-address">Delivery address</label><textarea id="checkout-address" {...field("delivery_address")} autoComplete="street-address" required={!pending} /></div> : <div className="form-field"><label htmlFor="checkout-pickup">Preferred pickup window (optional)</label><input id="checkout-pickup" {...field("pickup_window")} maxLength={200} /></div>}
        <div className="form-field"><label htmlFor="checkout-notes">Notes (optional)</label><textarea id="checkout-notes" {...field("notes")} rows={3} maxLength={5000} /></div>
      </div>
      <p className="cart-subtotal"><span>Delivery</span><strong>${delivery.toFixed(2)}</strong></p><p className="cart-subtotal"><span>{pending ? "Current cart estimate" : "Estimated total"}</span><strong>${(subtotal + delivery).toFixed(2)}</strong></p><p>The server confirms prices, delivery fees and stock before payment. Pickup is free.</p>
      {pending && <p className="cart-message">Resuming checkout uses the original submitted quantities and fulfillment details. Later cart edits are saved for your next order; the original payable total appears in Stripe. Cancel the unpaid checkout to change its details.</p>}
      {cart.message && <p role="status" className="cart-message">{cart.message}</p>}
      <button className="button button--dark" disabled={cart.busy || (!pending && !lines.length)}>{cart.busy ? "Checking your order…" : pending ? "Resume / check existing payment" : `Checkout ${channel} order`}</button>
      {pending && <button type="button" className="text-link" disabled={cart.busy} onClick={() => void cart.cancel(channel)}>Cancel unpaid checkout and release reserved flowers</button>}
      <p className="cart-explanation">A payment return URL is not confirmation. Only a verified paid order clears purchased quantities. New additions remain in your cart.</p>
    </form>
  </div>;
}
