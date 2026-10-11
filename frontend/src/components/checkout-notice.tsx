"use client";

import { useEffect, useRef } from "react";
import { useCart } from "./cart-provider";
import type { Channel } from "@/lib/cart";

/**
 * Inline notice for a checkout return URL, shared by the retail and wholesale
 * shops. A Stripe return is not proof of payment, so this only resolves to a
 * confirmed order once the cart has polled the server and seen a paid status —
 * and a confirmed payment surfaces as a top-of-page toast, not this banner.
 */
export function CheckoutNotice({ channel, checkoutStatus }: { channel: Channel; checkoutStatus: "success" | "cancelled" }) {
  const { checkouts, notify } = useCart();
  const announced = useRef(false);
  const cancelledMessage = `Your cart is saved. Resume your existing checkout or cancel the unpaid reservation from ${channel} checkout.`;

  // A cancelled checkout never reaches checkPayment, so announce it as a toast
  // once; the inline notice stays for the detail and the recovery action.
  useEffect(() => {
    if (announced.current) return;
    announced.current = true;
    if (checkoutStatus === "cancelled") notify(`Your cart is saved. Resume your existing checkout or cancel the unpaid reservation from ${channel} checkout.`, "info");
  }, [checkoutStatus, channel, notify]);

  if (checkoutStatus === "cancelled") {
    return <p className="retail-notice" role="status">{cancelledMessage}</p>;
  }
  const { outcome } = checkouts[channel];
  // A confirmed payment surfaces as a top-of-page toast, not an inline banner.
  if (outcome === "paid") return null;
  if (outcome === "closed") {
    return <p className="retail-notice" role="status" aria-live="polite">That checkout closed before payment was confirmed. Your cart is saved; review availability before trying again.</p>;
  }
  return <p className="retail-notice" role="status" aria-live="polite">Thank you. We are checking payment confirmation; your cart updates only after verified payment.</p>;
}
