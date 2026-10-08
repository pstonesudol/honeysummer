import type { FlowerListing } from "@/lib/api";

/** Display estimate only; checkout calculates the authoritative fee from the database. */
export function estimateDeliveryFee(
  lines: { flower: FlowerListing; quantity: number }[],
): number {
  let total = 0;
  let perOrder = 0;
  const seen = new Set<number>();
  for (const { flower, quantity } of lines) {
    if (quantity <= 0 || seen.has(flower.id)) continue;
    seen.add(flower.id);
    const fee = Number(flower.delivery_fee || 0);
    if (flower.delivery_fee_mode === "per_unit") total += fee * quantity;
    else if (flower.delivery_fee_mode === "per_order") perOrder = Math.max(perOrder, fee);
    else total += fee;
  }
  return total + perOrder;
}
