"use client";

import { useMemo, useState } from "react";
import { AlertCircle, Check, Loader2, Lock } from "lucide-react";

import type { FlowerListing } from "@/lib/api";
import { estimateDeliveryFee } from "@/lib/delivery-fee";
import { pickup } from "@/lib/site";

type Cart = Record<number, number>;
type CheckoutStatus = "success" | "cancelled" | null;
type Fulfillment = "pickup" | "delivery";

function formatError(data: unknown): string {
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    if (typeof record.detail === "string" && record.detail) {
      return record.detail;
    }
    const parts = Object.entries(record).map(([field, value]) => {
      const text = Array.isArray(value) ? value.join(" ") : String(value);
      return `${field.replace(/_/g, " ")}: ${text}`;
    });
    if (parts.length > 0) {
      return parts.join(" ");
    }
  }
  return "Something went wrong starting your order. Please try again.";
}

/**
 * Retail storefront: standard offerings with live availability and guest
 * checkout. The backend re-validates stock when the order is placed, so a
 * briefly stale grid can never oversell.
 */
export function RetailShop({
  flowers,
  checkoutStatus = null,
}: {
  flowers: FlowerListing[];
  checkoutStatus?: CheckoutStatus;
}) {
  const [cart, setCart] = useState<Cart>({});
  const [fulfillment, setFulfillment] = useState<Fulfillment>("pickup");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const orderable = useMemo(() => flowers.filter((flower) => flower.available), [flowers]);

  const cartLines = useMemo(
    () =>
      Object.entries(cart)
        .map(([id, quantity]) => ({
          flower: flowers.find((candidate) => candidate.id === Number(id)),
          quantity,
        }))
        .filter(
          (line): line is { flower: FlowerListing; quantity: number } =>
            Boolean(line.flower) && line.quantity > 0,
        ),
    [cart, flowers],
  );

  const count = cartLines.reduce((sum, line) => sum + line.quantity, 0);
  const total = cartLines.reduce(
    (sum, line) => sum + Number(line.flower.price) * line.quantity,
    0,
  );
  const deliveryFee = fulfillment === "delivery" ? estimateDeliveryFee(cartLines) : 0;

  function setQuantity(flower: FlowerListing, value: number) {
    const next = Math.max(0, Math.min(flower.quantity_available, value || 0));
    setCart((current) => {
      const updated = { ...current };
      if (next === 0) {
        delete updated[flower.id];
      } else {
        updated[flower.id] = next;
      }
      return updated;
    });
  }

  async function checkout(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (cartLines.length === 0) {
      setError("Add at least one offering to your basket first.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/retail/checkout/", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          items: cartLines.map((line) => ({
            id: line.flower.id,
            quantity: line.quantity,
          })),
          name: String(form.get("name") ?? "").trim(),
          email: String(form.get("email") ?? "").trim(),
          phone: String(form.get("phone") ?? "").trim(),
          fulfillment,
          delivery_address: String(form.get("delivery_address") ?? "").trim(),
          pickup_window: String(form.get("pickup_window") ?? "").trim(),
          notes: String(form.get("notes") ?? "").trim(),
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(formatError(data));
      }
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
        return;
      }
      setCart({});
      setNotice(
        `Order #${data.order_id} received. Isabella will confirm your pickup or delivery details by email.`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Checkout failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="retail-shop">
      {checkoutStatus === "success" ? (
        <p className="retail-notice retail-notice--success" role="status">
          <Check aria-hidden="true" size={18} strokeWidth={1.8} />
          <span>Thank you! Your order is confirmed and a receipt is on its way.</span>
        </p>
      ) : null}
      {checkoutStatus === "cancelled" ? (
        <p className="retail-notice" role="status">
          <span>Your checkout was cancelled, but your flowers are still waiting below.</span>
        </p>
      ) : null}

      {orderable.length === 0 ? (
        <p className="retail-shop__empty">
          Nothing is listed for online ordering this week. Send a custom request
          below and we will make something just for you.
        </p>
      ) : (
        <form className="retail-shop__form" onSubmit={checkout}>
          <div className="flower-grid">
            {orderable.map((flower) => (
              <article className="flower-card" key={flower.id}>
                {flower.photo_url ? (
                  <img src={flower.photo_url} alt={flower.name} />
                ) : (
                  <div className="flower-card__placeholder">✿</div>
                )}
                <div className="flower-card__body">
                  <p className="eyebrow">{flower.color || "Seasonal"}</p>
                  <h3>{flower.name}</h3>
                  <p>
                    {flower.variety}
                    {flower.stem_notes ? ` · ${flower.stem_notes}` : ""}
                  </p>
                  <strong>
                    ${flower.price} / {flower.unit}
                  </strong>
                  {Number(flower.delivery_fee) > 0 ? (
                    <p>Delivery: ${flower.delivery_fee} {flower.delivery_fee_mode === "per_unit" ? "/ unit" : flower.delivery_fee_mode === "per_order" ? "/ order" : "/ listing"}</p>
                  ) : null}
                  <div className="quantity">
                    <label htmlFor={`retail-flower-${flower.id}`}>Quantity</label>
                    <input
                      id={`retail-flower-${flower.id}`}
                      type="number"
                      min="0"
                      max={flower.quantity_available}
                      value={cart[flower.id] ?? 0}
                      onChange={(event) => setQuantity(flower, Number(event.target.value))}
                    />
                  </div>
                </div>
              </article>
            ))}
          </div>

          <div className="retail-checkout inquiry-form">
            <div className="retail-checkout__intro">
              <p className="eyebrow">Your details</p>
              <h3>Where should the flowers go?</h3>
            </div>
            <div className="form-grid">
              <div className="form-field form-field--half">
                <label htmlFor="retail-name">
                  Your name <span aria-hidden="true">*</span>
                </label>
                <input id="retail-name" name="name" autoComplete="name" required />
              </div>
              <div className="form-field form-field--half">
                <label htmlFor="retail-email">
                  Email <span aria-hidden="true">*</span>
                </label>
                <input
                  id="retail-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                />
              </div>
              <div className="form-field form-field--half">
                <label htmlFor="retail-phone">Phone (optional)</label>
                <input id="retail-phone" name="phone" type="tel" autoComplete="tel" />
              </div>
              <div className="form-field form-field--half">
                <label htmlFor="retail-fulfillment">Pickup or delivery?</label>
                <select
                  id="retail-fulfillment"
                  name="fulfillment"
                  value={fulfillment}
                  onChange={(event) =>
                    setFulfillment(event.target.value as Fulfillment)
                  }
                >
                  <option value="pickup">Pickup at the farm</option>
                  <option value="delivery">Delivery</option>
                </select>
              </div>
              {fulfillment === "delivery" ? (
                <div className="form-field">
                  <label htmlFor="retail-address">
                    Delivery address <span aria-hidden="true">*</span>
                  </label>
                  <input
                    id="retail-address"
                    name="delivery_address"
                    autoComplete="street-address"
                    required
                  />
                </div>
              ) : (
                <div className="form-field">
                  <label htmlFor="retail-pickup">Preferred pickup window (optional)</label>
                  <input
                    id="retail-pickup"
                    name="pickup_window"
                    placeholder={pickup.window}
                  />
                </div>
              )}
              <div className="form-field">
                <label htmlFor="retail-notes">Notes (optional)</label>
                <textarea id="retail-notes" name="notes" rows={3} />
              </div>
            </div>

            {error ? (
              <p className="form-status form-status--error" role="alert">
                <AlertCircle aria-hidden="true" size={18} strokeWidth={1.8} />
                <span>{error}</span>
              </p>
            ) : null}
            {notice ? (
              <p className="form-status form-status--success" role="status">
                <Check aria-hidden="true" size={18} strokeWidth={1.8} />
                <span>{notice}</span>
              </p>
            ) : null}

            <div className="cart-bar">
              <span>
                 {count} {count === 1 ? "item" : "items"} · ${total.toFixed(2)}
                 {fulfillment === "delivery" ? ` + $${deliveryFee.toFixed(2)} delivery = $${(total + deliveryFee).toFixed(2)}` : ""}
              </span>
              <button
                className="button button--dark"
                type="submit"
                disabled={busy || cartLines.length === 0}
              >
                {busy ? (
                  <>
                    <Loader2 className="spin" aria-hidden="true" size={16} strokeWidth={1.8} />
                    Starting checkout…
                  </>
                ) : (
                  "Continue to checkout"
                )}
              </button>
            </div>
            <p className="inquiry-form__privacy">
              <Lock aria-hidden="true" size={14} strokeWidth={1.8} />
              Secure payment through Stripe. We only use your details to fulfill your order.
            </p>
          </div>
        </form>
      )}
    </div>
  );
}
