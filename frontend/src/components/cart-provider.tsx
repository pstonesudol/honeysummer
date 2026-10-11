"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import type { FlowerListing } from "@/lib/api";
import { cartIssues, checkoutOutcome, consumePurchased, quantityChange, readCart, type Channel, type CheckoutOutcome, type SavedCart } from "@/lib/cart";

export type Account = { id: number | null; authenticated: boolean; approved: boolean; business_name: string; must_change_password: boolean };
/** A short-lived, non-modal message shown at the top of the viewport. */
export type CartToast = { id: string; tone: "success" | "info" | "error"; message: string };
const anonymous: Account = { id: null, authenticated: false, approved: false, business_name: "", must_change_password: false };
const blank = (): SavedCart => ({ items: {} });
const keyFor = (channel: Channel, id: number | null) => `hs-cart-v1:${channel === "retail" ? "retail" : `wholesale:${id}`}`;

export async function cartApi(path: string, options?: RequestInit) {
  const response = await fetch(`/api/${path}`, { cache: "no-store", signal: AbortSignal.timeout(15000), ...options,
    headers: { "Content-Type": "application/json", "X-HoneySummer-Request": "1", ...options?.headers } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || Object.entries(data).map(([key, value]) => `${key.replaceAll("_", " ")}: ${Array.isArray(value) ? value.join(" ") : value}`).join(" ") || "Unable to connect. Please try again.");
    Object.assign(error, { status: response.status });
    throw error;
  }
  return data;
}

function useCartState() {
  const pathname = usePathname();
  const [account, setAccount] = useState<Account>(anonymous);
  const accountRef = useRef(account);
  const [carts, setCarts] = useState<Record<Channel, SavedCart>>({ retail: blank(), wholesale: blank() });
  const state = useRef(carts);
  const [catalogues, setCatalogues] = useState<Record<Channel, FlowerListing[]>>({ retail: [], wholesale: [] });
  const cataloguesRef = useRef(catalogues);
  const [selected, setSelected] = useState<Channel>("retail");
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  // Latest server-verified outcome of each channel's checkout attempt, so a
  // return page can show a confirmed order instead of only "we are checking".
  const [checkouts, setCheckouts] = useState<Record<Channel, { outcome: CheckoutOutcome; reference: string }>>({
    retail: { outcome: "pending", reference: "" },
    wholesale: { outcome: "pending", reference: "" },
  });
  // Order and payment updates stack briefly above the page, then clear on their
  // own so a Stripe return still reaches the customer even if they land anywhere.
  const [toasts, setToasts] = useState<CartToast[]>([]);
  const toastTimers = useRef(new Map<string, number>());
  // Fulfillment/contact fields survive navigation only in memory, never storage.
  const [details, setDetails] = useState<Record<Channel, Record<string, string>>>({ retail: { fulfillment: "pickup" }, wholesale: { fulfillment: "pickup" } });
  const submitting = useRef(false);
  const generation = useRef(0);
  const mounted = useRef(true);
  const selectionRestored = useRef(false);
  const invalidateRequests = useCallback(() => { mounted.current = false; generation.current++; }, []);

  const dismissToast = useCallback((id: string) => {
    const timer = toastTimers.current.get(id);
    if (timer !== undefined) { window.clearTimeout(timer); toastTimers.current.delete(id); }
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const pushToast = useCallback((message: string, tone: CartToast["tone"] = "info") => {
    if (!message) return;
    const id = crypto.randomUUID();
    // Keep a small stack; the oldest falls off once a fourth arrives.
    setToasts((current) => [...current, { id, tone, message }].slice(-3));
    const timer = window.setTimeout(() => { toastTimers.current.delete(id); setToasts((current) => current.filter((toast) => toast.id !== id)); }, 9000);
    toastTimers.current.set(id, timer);
  }, []);

  const save = useCallback((channel: Channel, value: SavedCart) => {
    value = { ...value, items: Object.fromEntries(Object.entries(value.items).filter(([id, line]) => line.quantity > 0 || value.attempt?.items[Number(id)]?.quantity)) };
    state.current = { ...state.current, [channel]: value };
    setCarts(state.current);
    try { localStorage.setItem(keyFor(channel, accountRef.current.id), JSON.stringify(value)); }
    catch {
      const message = "Browser storage is unavailable. Keep this tab open to preserve your cart.";
      setMessage(message);
      pushToast(message, "error");
    }
  }, [pushToast]);

  const setIdentity = useCallback((next: Account) => {
    const previous = accountRef.current;
    if (previous.id !== next.id || !next.approved) {
      generation.current++;
      if (previous.id) localStorage.removeItem(keyFor("wholesale", previous.id));
      state.current = { ...state.current, wholesale: blank() };
      setCarts(state.current);
      setDetails((current) => ({ ...current, wholesale: { fulfillment: "pickup" } }));
      setCatalogues((current) => ({ ...current, wholesale: [] }));
      cataloguesRef.current = { ...cataloguesRef.current, wholesale: [] };
      setSelected("retail");
    }
    accountRef.current = next;
    setAccount(next);
    if (next.id && next.approved && previous.id !== next.id) {
      state.current = { ...state.current, wholesale: readCart(localStorage.getItem(keyFor("wholesale", next.id))) };
      setCarts(state.current);
    }
  }, []);

  const refreshAccount = useCallback(async () => {
    const stamp = generation.current;
    // A failed/aborted request is not a server-confirmed logout. In particular,
    // unload can abort an in-flight poll; it must not delete the saved basket.
    const next = await cartApi("auth/me/") as Account;
    if (mounted.current && stamp === generation.current) setIdentity(next);
    return accountRef.current;
  }, [setIdentity]);

  const validate = useCallback(async (channel: Channel) => {
    const identity = await refreshAccount();
    if (channel === "wholesale" && !identity.approved) throw new Error("Wholesale access is no longer available. Sign in with an approved account.");
    const stamp = generation.current;
    const flowers: FlowerListing[] = await cartApi(channel === "retail" ? "retail/flowers/" : "flowers/");
    if (channel === "wholesale" && (stamp !== generation.current || identity.id !== accountRef.current.id)) throw new Error("Your account changed. Please reopen your cart.");
    const changed = flowers.filter((flower) => state.current[channel].items[flower.id]?.quantity && cataloguesRef.current[channel].some((old) => old.id === flower.id && (old.price !== flower.price || old.delivery_fee !== flower.delivery_fee || old.delivery_fee_mode !== flower.delivery_fee_mode)));
    if (changed.length) setMessage("Prices or delivery fees changed. Review the current cart totals before checkout.");
    cataloguesRef.current = { ...cataloguesRef.current, [channel]: flowers };
    setCatalogues(cataloguesRef.current);
    return flowers;
  }, [refreshAccount]);

  const checkPayment = useCallback(async (channel: Channel) => {
    const attempt = state.current[channel].attempt;
    if (!attempt) return;
    const owner = accountRef.current.id;
    const data = await cartApi(`cart/checkout/${attempt.key}/`);
    if (channel === "wholesale" && owner !== accountRef.current.id) return;
    if (state.current[channel].attempt?.key !== attempt.key) return;
    const outcome = checkoutOutcome(data.status);
    const reference = data.order_reference ?? "";
    setCheckouts((current) => (current[channel].outcome === outcome && current[channel].reference === reference ? current : { ...current, [channel]: { outcome, reference } }));
    if (outcome === "paid") {
      const latest = readCart(localStorage.getItem(keyFor(channel, owner)));
      if (latest.attempt?.key !== attempt.key) return data;
      save(channel, { items: consumePurchased(latest.items, attempt.items) });
      setMessage(`Order ${data.order_reference} payment confirmed. Your other cart and new additions are saved.`);
      pushToast(`Thank you. Payment confirmed${reference ? ` for order ${reference}` : ""}; your cart has been updated.`, "success");
    } else if (outcome === "closed") {
      save(channel, { items: state.current[channel].items });
      setMessage("Checkout expired or was cancelled. Your cart is saved; review availability before trying again.");
      pushToast("That checkout closed before payment was confirmed. Your cart is saved; review availability before trying again.", "info");
    } else setMessage("Payment is not yet confirmed. Resume your existing checkout, or wait while payment is processing.");
    return data;
  }, [save, pushToast]);

  useEffect(() => {
    mounted.current = true;
    let active = true;
    const refresh = async () => {
      const next = await refreshAccount();
      if (!active) return;
      if (!selectionRestored.current) {
        selectionRestored.current = true;
        setSelected(localStorage.getItem("hs-cart-v1:selected") === "wholesale" && next.approved ? "wholesale" : "retail");
      }
      for (const channel of ["retail", ...(next.approved ? ["wholesale"] : [])] as Channel[]) {
        state.current = { ...state.current, [channel]: readCart(localStorage.getItem(keyFor(channel, next.id))) };
        setCarts(state.current);
        await checkPayment(channel).catch(() => undefined);
        await validate(channel).catch(() => undefined);
      }
      setReady(true);
    };
    void refresh().catch(() => setReady(true));
    const onFocus = () => { void refresh().catch(() => undefined); };
    const onVisibility = () => { if (document.visibilityState === "visible") onFocus(); };
    const onStorage = (event: StorageEvent) => { if (event.key?.startsWith("hs-cart-v1:")) onFocus(); };
    window.addEventListener("focus", onFocus);
    window.addEventListener("storage", onStorage);
    document.addEventListener("visibilitychange", onVisibility);
    const timer = window.setInterval(onFocus, 15000);
    return () => { active = false; invalidateRequests(); clearInterval(timer); window.removeEventListener("focus", onFocus); window.removeEventListener("storage", onStorage); document.removeEventListener("visibilitychange", onVisibility); };
  }, [refreshAccount, checkPayment, validate, invalidateRequests]);

  useEffect(() => () => {
    for (const timer of toastTimers.current.values()) window.clearTimeout(timer);
    toastTimers.current.clear();
  }, []);

  const show = useCallback((channel?: Channel) => {
    const next = channel ?? (pathname.startsWith("/wholesale") && accountRef.current.approved ? "wholesale" : pathname.startsWith("/order-flowers") ? "retail" : selected);
    const accessible = next === "wholesale" && !accountRef.current.approved ? "retail" : next;
    setSelected(accessible); setOpen(true);
    try { localStorage.setItem("hs-cart-v1:selected", accessible); } catch { /* Selection can stay in memory. */ }
    void validate(accessible).catch((error) => setMessage(error.message));
    void checkPayment(accessible).catch(() => undefined);
  }, [pathname, selected, validate, checkPayment]);

  const add = (channel: Channel, flower: FlowerListing, quantity = 1) => {
    if (!ready || (channel === "wholesale" && !accountRef.current.approved)) return;
    const current = state.current[channel];
    if (Object.values(current.items).filter((line) => line.quantity > 0).length >= 100 && !current.items[flower.id]?.quantity) {
      setMessage("Your cart can contain up to 100 different offerings."); return;
    }
    const next = Math.min(flower.quantity_available, (current.items[flower.id]?.quantity ?? 0) + quantity);
    save(channel, { ...current, items: quantityChange(current.items, flower.id, next) });
    setCatalogues((catalogues) => ({ ...catalogues, [channel]: [...catalogues[channel].filter((f) => f.id !== flower.id), flower] }));
    show(channel); setMessage(`${flower.name} added to your ${channel} cart.`);
  };

  const quantity = (channel: Channel, id: number, value: number) => {
    const current = state.current[channel];
    save(channel, { ...current, items: quantityChange(current.items, id, Math.max(0, Math.min(9999, Math.floor(value || 0)))) });
  };

  const checkout = async (channel: Channel, details: Record<string, string>) => {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setMessage("");
    const run = async () => {
      const owner = accountRef.current.id;
      const storageKey = keyFor(channel, owner);
      const stored = localStorage.getItem(storageKey);
      if (stored) { state.current = { ...state.current, [channel]: readCart(stored) }; setCarts(state.current); }
      if (state.current[channel].attempt) {
        const data = await checkPayment(channel).catch((error) => { if (error.status !== 404) throw error; return null; });
        if (data?.status === "pending") { if (data.checkout_url) window.location.assign(data.checkout_url); return; }
        if (data) return;
        // No order was created: retry the SAME key, including after a lost response.
      }
      const previous = catalogues[channel];
      const flowers = await validate(channel);
      if (channel === "wholesale" && owner !== accountRef.current.id) throw new Error("Your account changed. Reopen your cart.");
      const current = state.current[channel];
      const issues = cartIssues(current.items, flowers);
      const priceChanges = flowers.filter((f) => current.items[f.id]?.quantity && previous.some((old) => old.id === f.id && (old.price !== f.price || old.delivery_fee !== f.delivery_fee || old.delivery_fee_mode !== f.delivery_fee_mode)));
      if (priceChanges.length) issues.push("Prices or delivery fees changed. Review the updated totals and submit again.");
      if (issues.length) throw new Error(issues.join(" "));
      const items = Object.entries(current.items).filter(([, line]) => line.quantity > 0);
      if (!items.length) throw new Error("Add flowers to your cart first.");
      const attempt = current.attempt ?? { key: crypto.randomUUID(), items: structuredClone(Object.fromEntries(items)) };
      save(channel, { ...current, attempt }); // Write before the network request.
      try {
        const data = await cartApi(channel === "retail" ? "retail/checkout/" : "checkout/", {
          method: "POST", body: JSON.stringify({ ...details, checkout_key: attempt.key,
            items: Object.entries(attempt.items).filter(([, line]) => line.quantity).map(([id, line]) => ({ id: Number(id), quantity: line.quantity, price: flowers.find((f) => f.id === Number(id))?.price })) }),
        });
        if (data.checkout_url) window.location.assign(data.checkout_url);
        else await checkPayment(channel);
      } catch (error) {
        // Validation failures have no reservation. Uncertain responses retain the key.
        if ([400, 409].includes((error as { status?: number }).status ?? 0)) save(channel, { items: state.current[channel].items });
        throw error;
      }
    };
    try {
      if (navigator.locks) await navigator.locks.request(`hs-checkout:${channel}:${accountRef.current.id}`, run);
      else await run();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to start checkout. Your cart is saved.";
      setMessage(message);
      pushToast(message, "error");
    }
    finally { submitting.current = false; setBusy(false); }
  };

  const cancel = async (channel: Channel) => {
    const attempt = state.current[channel].attempt;
    if (!attempt) return;
    setBusy(true);
    try { await cartApi(`cart/checkout/${attempt.key}/`, { method: "DELETE" }); await checkPayment(channel); }
    catch (error) {
      const message = error instanceof Error ? error.message : "Unable to cancel checkout.";
      setMessage(message);
      pushToast(message, "error");
    }
    finally { setBusy(false); }
  };
  const logout = async () => {
    // Hide gated state immediately, including while logout is in flight.
    setIdentity(anonymous);
    try { await cartApi("auth/logout/", { method: "POST" }); }
    catch {
      const message = "Sign-out could not reach the server. Your wholesale cart was cleared; reconnect and sign out again.";
      setMessage(message);
      pushToast(message, "error");
    }
  };
  const updateDetails = (channel: Channel, name: string, value: string) => setDetails((current) => ({ ...current, [channel]: { ...current[channel], [name]: value } }));
  return { account, refreshAccount, logout, carts, catalogues, selected, open, setOpen, show, add, quantity, checkout, cancel, validate, details, updateDetails, message, checkouts, toasts, notify: pushToast, dismissToast, ready, busy };
}

type CartContext = ReturnType<typeof useCartState>;
const Context = createContext<CartContext | null>(null);
export function CartProvider({ children }: { children: React.ReactNode }) {
  const value = useCartState();
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useCart() {
  const value = useContext(Context);
  if (!value) throw new Error("CartProvider is required.");
  return value;
}
