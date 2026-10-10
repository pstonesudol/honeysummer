import { test } from "node:test";
import assert from "node:assert/strict";
import { consumePurchased, quantityChange, readCart, cartIssues } from "../src/lib/cart.ts";

test("restoration validates stored IDs and quantities without storing product/contact data", () => {
  const restored = readCart(JSON.stringify({ items: { 1: { quantity: 2, added: 2 }, 2: { quantity: -1, added: 1 }, 3: { quantity: 1.5, added: 2 } } }));
  assert.deepEqual(restored.items, { 1: { quantity: 2, added: 2 } });
  assert.deepEqual(readCart("broken"), { items: {} });
});
test("verified payment subtracts submitted quantities but keeps subsequent additions and other listings", () => {
  const submitted = quantityChange({}, 1, 2);
  let current = quantityChange(submitted, 1, 5);
  current = quantityChange(current, 2, 1);
  assert.equal(consumePurchased(current, submitted)[1].quantity, 3);
  assert.equal(consumePurchased(current, submitted)[2].quantity, 1);
});
test("removing then re-adding after checkout preserves only the new additions, including across reloads", () => {
  const submitted = quantityChange({}, 1, 3);
  const removed = readCart(JSON.stringify({ items: quantityChange(submitted, 1, 0) }));
  const added = quantityChange(removed.items, 1, 2);
  assert.equal(consumePurchased(added, submitted)[1].quantity, 2);
});
test("independent retail and wholesale carts can contain the same listing without merging", () => {
  const retail = quantityChange({}, 1, 2), wholesale = quantityChange({}, 1, 4);
  assert.equal(consumePurchased(retail, retail)[1].quantity, 0);
  assert.equal(wholesale[1].quantity, 4);
});
test("revalidation flags missing, sold-out and reduced stock instead of silently removing purchases", () => {
  const items = { 1: { quantity: 3, added: 3 }, 2: { quantity: 1, added: 1 }, 3: { quantity: 1, added: 1 } };
  assert.equal(cartIssues(items, [{ id: 1, name: "Dahlias", unit: "bunch", available: true, quantity_available: 2 }, { id: 2, name: "Roses", available: false }]).length, 3);
  assert.equal(items[1].quantity, 3);
});
