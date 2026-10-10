import type { FlowerListing } from "./api";

export type Channel = "retail" | "wholesale";
export type Basket = Record<number, { quantity: number; added: number }>;
export type Attempt = { key: string; items: Basket };
export type SavedCart = { items: Basket; attempt?: Attempt };

export function readCart(raw: string | null): SavedCart {
  try {
    const value = JSON.parse(raw ?? "{}");
    const clean = (items: Basket): Basket => Object.fromEntries(Object.entries(items ?? {}).filter(
      ([id, line]) => Number.isSafeInteger(Number(id)) && Number(id) > 0 &&
        Number.isSafeInteger(line?.quantity) && line.quantity >= 0 && line.quantity <= 9999 &&
        Number.isSafeInteger(line.added) && line.added >= line.quantity,
    ).slice(0, 200));
    return { items: clean(value.items), ...(typeof value.attempt?.key === "string" && /^[0-9a-f-]{36}$/.test(value.attempt.key)
      ? { attempt: { key: value.attempt.key, items: clean(value.attempt.items) } } : {}) };
  } catch { return { items: {} }; }
}

export function quantityChange(items: Basket, id: number, quantity: number): Basket {
  const old = items[id] ?? { quantity: 0, added: 0 };
  // Keep zero lines in memory for monotonic addition counts during checkout.
  return { ...items, [id]: { quantity, added: old.added + Math.max(0, quantity - old.quantity) } };
}

export function consumePurchased(current: Basket, submitted: Basket): Basket {
  return Object.fromEntries(Object.entries(current).map(([id, line]) => {
    const paid = submitted[Number(id)];
    const quantity = paid ? Math.max(0, line.quantity - paid.quantity, Math.min(line.quantity, line.added - paid.added)) : line.quantity;
    return [id, { ...line, quantity }];
  }));
}

export function cartIssues(items: Basket, flowers: FlowerListing[]): string[] {
  return Object.entries(items).flatMap(([id, line]) => {
    if (!line.quantity) return [];
    const flower = flowers.find((f) => f.id === Number(id));
    if (!flower || !flower.available) return [flower ? `${flower.name} is unavailable. Remove it to continue.` : `Item #${id} is no longer listed. Remove it to continue.`];
    return line.quantity > flower.quantity_available ? [`Only ${flower.quantity_available} ${flower.unit} of ${flower.name} remain. Update its quantity.`] : [];
  });
}
