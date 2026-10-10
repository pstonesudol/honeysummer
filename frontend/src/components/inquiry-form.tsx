"use client";

import { useActionState, useEffect, useState } from "react";
import { AlertCircle, Loader2, Lock } from "lucide-react";

import { submitInquiry } from "@/lib/actions";
import type { FlowerListing } from "@/lib/api";
import { useCart } from "./cart-provider";
import { ProductGrid } from "./retail-shop";
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

async function api(path: string, options?: RequestInit) {
  const response = await fetch(`/api/${path}`, { cache: "no-store", ...options, headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Something went wrong.");
  return data;
}

export function WholesaleShop() {
  const { account, refreshAccount, logout } = useCart();
  const [catalogue, setCatalogue] = useState<{ owner: number | null; flowers: Flower[] }>({ owner: null, flowers: [] });
  const flowers = catalogue.owner === account.id ? catalogue.flowers : [];
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    if (account.authenticated && account.approved) api("flowers/").then((next) => { if (active) setCatalogue({ owner: account.id, flowers: next }); }).catch(() => undefined);
    return () => { active = false; };
  }, [account.id, account.authenticated, account.approved]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage("");
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      const body: Record<string, string> = { email: String(form.get("email")), password: String(form.get("password")) };
      if (mode === "signup") {
        for (const field of ["name", "business_name", "phone", "business_type", "website", "message"]) {
          body[field] = String(form.get(field) ?? "").trim();
        }
      }
      const data = await api(`auth/${mode}/`, { method: "POST", body: JSON.stringify(body) });
      if (mode === "signup") { setMessage(data.detail); formElement.reset(); }
      else await refreshAccount();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Unable to continue."); }
    setBusy(false);
  }

  if (account?.authenticated && !account.approved) return <section className="wholesale-access section-wrap" aria-labelledby="shop-title">
    <div><p className="eyebrow">Wholesale shop</p><h2 id="shop-title">Your account is awaiting approval.</h2><p>Isabella will email you once your account is ready. You can sign in with the password you chose.</p></div>
    <div><button className="text-link" onClick={() => void logout()}>Sign out</button></div>
  </section>;

  if (!account?.authenticated) return <section className="wholesale-access section-wrap" aria-labelledby="shop-title">
    <div><p className="eyebrow">Wholesale shop</p><h2 id="shop-title">{mode === "login" ? "Sign in to see what is blooming." : "Request a wholesale account."}</h2><p>{mode === "login" ? "Approved Honey Summer florist accounts see live availability and wholesale pricing here." : "Tell us about your business and choose a password. Isabella will review your request; you can sign in once your account is approved."}</p></div>
    <form className="wholesale-auth" onSubmit={submit}>
      {mode === "signup" && <>
        <label>Your name<input name="name" autoComplete="name" maxLength={200} required /></label>
        <label>Business name<input name="business_name" autoComplete="organization" maxLength={200} required /></label>
        <label>Phone (optional)<input name="phone" type="tel" autoComplete="tel" maxLength={40} /></label>
        <label>Business type<select name="business_type" defaultValue=""><option value="">Please choose…</option><option value="florist">Florist</option><option value="event">Event designer or planner</option><option value="shop">Retail shop or studio</option><option value="other">Other</option></select></label>
        <label>Website or Instagram<input name="website" type="url" placeholder="https://…" maxLength={500} /></label>
        <label>Tell us about your work<textarea name="message" rows={4} maxLength={5000} /></label>
      </>}
      <label>Email<input name="email" type="email" autoComplete="email" required /></label><label>Password<input name="password" type="password" autoComplete={mode === "signup" ? "new-password" : "current-password"} minLength={8} required /></label>
      <button className="button button--dark" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Request account"}</button>
      <button type="button" className="text-link" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setMessage(""); }}>{mode === "login" ? "Need wholesale access? Request an account" : "Already have an account? Sign in"}</button>
      {message && <p role="status" className="form-message">{message}</p>}
    </form>
  </section>;

  return <section className="wholesale-shop section-wrap" aria-labelledby="shop-title">
    <div className="wholesale-shop__heading"><div><p className="eyebrow">Welcome, {account.business_name}</p><h2 id="shop-title">This week’s stems.</h2></div><button className="text-link" onClick={() => void logout()}>Sign out</button></div>
    {flowers.length === 0 ? <p>Nothing is listed today — check back soon.</p> : <ProductGrid flowers={flowers} channel="wholesale" />}
    {message && <p role="status" className="form-message">{message}</p>}
  </section>;
}
