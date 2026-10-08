"use client";

import { useActionState, useEffect, useState } from "react";
import { AlertCircle, Loader2, Lock } from "lucide-react";

import { submitInquiry } from "@/lib/actions";
import type { FlowerListing } from "@/lib/api";
import { estimateDeliveryFee } from "@/lib/delivery-fee";
import {
  inquiryFields,
  type InquiryField,
  type InquiryKind,
  type InquiryState,
} from "@/lib/inquiry-fields";

const initialState: InquiryState = { status: "idle" };

function FieldControl({ field, kind }: { field: InquiryField; kind: InquiryKind }) {
  const id = `${kind}-${field.name}`;
  const helpId = field.help ? `${id}-help` : undefined;
  const describedBy = helpId;

  switch (field.type) {
    case "textarea":
      return (
        <textarea
          id={id}
          name={field.name}
          rows={field.rows ?? 4}
          required={field.required}
          placeholder={field.placeholder}
          aria-describedby={describedBy}
        />
      );
    case "select":
      return (
        <select
          id={id}
          name={field.name}
          required={field.required}
          defaultValue=""
          aria-describedby={describedBy}
        >
          <option value="" disabled>
            Please choose…
          </option>
          {field.options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      );
    case "checkbox":
      return (
        <label className="checkbox" htmlFor={id}>
          <input id={id} name={field.name} type="checkbox" required={field.required} />
          <span>{field.label}</span>
        </label>
      );
    case "file":
      return (
        <input
          id={id}
          name={field.name}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          aria-describedby={describedBy}
        />
      );
    case "number":
      return (
        <input
          id={id}
          name={field.name}
          type="number"
          min={0}
          required={field.required}
          placeholder={field.placeholder}
          aria-describedby={describedBy}
        />
      );
    default:
      return (
        <input
          id={id}
          name={field.name}
          type={field.type}
          required={field.required}
          placeholder={field.placeholder}
          autoComplete={field.autoComplete}
          aria-describedby={describedBy}
        />
      );
  }
}

function Field({ field, kind }: { field: InquiryField; kind: InquiryKind }) {
  const id = `${kind}-${field.name}`;
  const helpId = field.help ? `${id}-help` : undefined;
  const isCheckbox = field.type === "checkbox";

  return (
    <div
      className={`form-field${field.half ? " form-field--half" : ""}${
        isCheckbox ? " form-field--checkbox" : ""
      }`}
    >
      {!isCheckbox ? (
        <label htmlFor={id}>
          {field.label}
          {field.required ? <span aria-hidden="true"> *</span> : null}
        </label>
      ) : null}
      <FieldControl field={field} kind={kind} />
      {field.help ? (
        <p className="form-field__help" id={helpId}>
          {field.help}
        </p>
      ) : null}
    </div>
  );
}

export function InquiryForm({
  kind,
  submitLabel = "Send inquiry",
}: {
  kind: InquiryKind;
  submitLabel?: string;
}) {
  const [state, action, pending] = useActionState(
    submitInquiry.bind(null, kind),
    initialState,
  );

  return (
    <form className="inquiry-form" action={action}>
      <div className="form-honeypot" aria-hidden="true">
        <label htmlFor={`${kind}-company`}>Company</label>
        <input
          id={`${kind}-company`}
          name="company"
          type="text"
          tabIndex={-1}
          autoComplete="off"
        />
      </div>

      <div className="form-grid">
        {inquiryFields[kind].map((field) => (
          <Field field={field} kind={kind} key={field.name} />
        ))}
      </div>

      {state.status === "error" ? (
        <p className="form-status form-status--error" role="alert">
          <AlertCircle aria-hidden="true" size={18} strokeWidth={1.8} />
          <span>{state.message}</span>
        </p>
      ) : null}

      <div className="inquiry-form__actions">
        <button className="button button--primary" type="submit" disabled={pending}>
          {pending ? (
            <>
              <Loader2 className="spin" aria-hidden="true" size={16} strokeWidth={1.8} />
              Sending…
            </>
          ) : (
            submitLabel
          )}
        </button>
        <p className="inquiry-form__privacy">
          <Lock aria-hidden="true" size={14} strokeWidth={1.8} />
          We only use your details to reply to you.
        </p>
      </div>
    </form>
  );
}
type Flower = FlowerListing;
type Cart = Record<number, number>;

async function api(path: string, options?: RequestInit) {
  const response = await fetch(`/api/${path}`, { cache: "no-store", ...options, headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Something went wrong.");
  return data;
}

export function WholesaleShop() {
  const [account, setAccount] = useState<{ authenticated: boolean; approved: boolean; business_name: string } | null>(null);
  const [flowers, setFlowers] = useState<Flower[]>([]);
  const [cart, setCart] = useState<Cart>({});
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [fulfillment, setFulfillment] = useState<"pickup" | "delivery">("pickup");
  const [pickupWindow, setPickupWindow] = useState("");
  const [deliveryAddress, setDeliveryAddress] = useState("");

  useEffect(() => {
    let active = true;
    function refresh() {
      api("auth/me/")
        .then((next) => { if (active) setAccount(next); })
        .catch(() => { if (active) setAccount({ authenticated: false, approved: false, business_name: "" }); });
    }
    refresh();
    function onVisibilityChange() { if (document.visibilityState === "visible") refresh(); }
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => { active = false; document.removeEventListener("visibilitychange", onVisibilityChange); };
  }, []);
  useEffect(() => { if (account?.authenticated && account.approved) api("flowers/").then(setFlowers).catch(() => undefined); }, [account]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      const body: Record<string, string> = { email: String(form.get("email")), password: String(form.get("password")) };
      if (mode === "signup") { body.business_name = String(form.get("business_name")); body.phone = String(form.get("phone")); }
      const data = await api(`auth/${mode}/`, { method: "POST", body: JSON.stringify(body) });
      if (mode === "signup") setMessage(data.detail);
      else setAccount(data);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Unable to continue."); }
    setBusy(false);
  }

  async function checkout() {
    if (fulfillment === "delivery" && !deliveryAddress.trim()) {
      setMessage("Enter a delivery address before checkout.");
      return;
    }
    setBusy(true); setMessage("");
    try {
      const data = await api("checkout/", { method: "POST", body: JSON.stringify({
        items: Object.entries(cart).map(([id, quantity]) => ({ id: Number(id), quantity })),
        fulfillment,
        pickup_window: fulfillment === "pickup" ? pickupWindow.trim() : "",
        delivery_address: fulfillment === "delivery" ? deliveryAddress.trim() : "",
      }) });
      if (data.checkout_url) window.location.href = data.checkout_url;
      else setMessage(`Order #${data.order_id} received. Isabella will confirm your pickup details.`);
      setCart({});
    } catch (error) { setMessage(error instanceof Error ? error.message : "Checkout failed."); }
    setBusy(false);
  }

  if (!account?.authenticated || !account.approved) return <section className="wholesale-access section-wrap" aria-labelledby="shop-title">
    <div><p className="eyebrow">Wholesale shop</p><h2 id="shop-title">Sign in to see what is blooming.</h2><p>Approved Honey Summer florist accounts see live availability and wholesale pricing here.</p></div>
    <form className="wholesale-auth" onSubmit={submit}>
      {mode === "signup" && <><label>Business name<input name="business_name" required /></label><label>Phone<input name="phone" /></label></>}
      <label>Email<input name="email" type="email" required /></label><label>Password<input name="password" type="password" minLength={8} required /></label>
      <button className="button button--dark" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Request account"}</button>
      <button type="button" className="text-link" onClick={() => setMode(mode === "login" ? "signup" : "login")}>{mode === "login" ? "Need wholesale access? Request an account" : "Already approved? Sign in"}</button>
      {message && <p role="status" className="form-message">{message}</p>}
    </form>
  </section>;

  const cartTotal = Object.entries(cart).reduce((sum, [id, quantity]) => sum + Number(flowers.find((flower) => flower.id === Number(id))?.price ?? 0) * quantity, 0);
  const deliveryFee = fulfillment === "delivery" ? estimateDeliveryFee(
    Object.entries(cart).flatMap(([id, quantity]) => {
      const flower = flowers.find((candidate) => candidate.id === Number(id));
      return flower && quantity > 0 ? [{ flower, quantity }] : [];
    }),
  ) : 0;
  return <section className="wholesale-shop section-wrap" aria-labelledby="shop-title">
    <div className="wholesale-shop__heading"><div><p className="eyebrow">Welcome, {account.business_name}</p><h2 id="shop-title">This week’s stems.</h2></div><button className="text-link" onClick={() => api("auth/logout/", { method: "POST" }).then(() => setAccount({ authenticated: false, approved: false, business_name: "" }))}>Sign out</button></div>
    {flowers.length === 0 ? <p>Nothing is listed today — check back soon.</p> : <div className="flower-grid">{flowers.map((flower) => <article className="flower-card" key={flower.id}>
      {flower.photo_url ? <img src={flower.photo_url} alt="" /> : <div className="flower-card__placeholder">✿</div>}<div className="flower-card__body"><p className="eyebrow">{flower.color || "Seasonal"}</p><h3>{flower.name}</h3><p>{flower.variety} {flower.stem_notes && `· ${flower.stem_notes}`}</p><strong>${flower.price} / {flower.unit}</strong>{Number(flower.delivery_fee) > 0 ? <p>Delivery: ${flower.delivery_fee} {flower.delivery_fee_mode === "per_unit" ? "/ unit" : flower.delivery_fee_mode === "per_order" ? "/ order" : "/ listing"}</p> : null}{flower.available ? <div className="quantity"><label htmlFor={`flower-${flower.id}`}>Quantity</label><input id={`flower-${flower.id}`} type="number" min="0" max={flower.quantity_available} value={cart[flower.id] ?? 0} onChange={(event) => setCart({ ...cart, [flower.id]: Math.min(flower.quantity_available, Math.max(0, Number(event.target.value))) })} /></div> : <span className="sold-out">Sold out</span>}</div>
    </article>)}</div>}
    {Object.keys(cart).length > 0 && <div className="retail-checkout inquiry-form">
      <div className="form-grid">
        <div className="form-field form-field--half">
          <label htmlFor="wholesale-fulfillment">Pickup or delivery?</label>
          <select id="wholesale-fulfillment" value={fulfillment} onChange={(event) => setFulfillment(event.target.value as "pickup" | "delivery")}>
            <option value="pickup">Pickup at the farm</option>
            <option value="delivery">Delivery</option>
          </select>
        </div>
        {fulfillment === "delivery" ? <div className="form-field">
          <label htmlFor="wholesale-delivery-address">Delivery address (required)</label>
          <input id="wholesale-delivery-address" autoComplete="street-address" required value={deliveryAddress} onChange={(event) => setDeliveryAddress(event.target.value)} />
        </div> : <div className="form-field">
          <label htmlFor="wholesale-pickup-window">Preferred pickup window (optional)</label>
          <input id="wholesale-pickup-window" value={pickupWindow} onChange={(event) => setPickupWindow(event.target.value)} />
        </div>}
      </div>
      <div className="cart-bar"><span>{Object.values(cart).reduce((sum, quantity) => sum + quantity, 0)} stems · ${cartTotal.toFixed(2)}{fulfillment === "delivery" ? ` + $${deliveryFee.toFixed(2)} delivery = $${(cartTotal + deliveryFee).toFixed(2)}` : ""}</span><button className="button button--dark" disabled={busy} onClick={checkout}>Continue to checkout</button></div>
    </div>}
    {message && <p role="status" className="form-message">{message}</p>}
  </section>;
}
