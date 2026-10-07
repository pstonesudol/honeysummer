/**
 * Site-wide content and contact details.
 *
 * Items marked "client to provide" are placeholders until Isabella supplies
 * final copy, photography, and social links (see the launch checklist).
 */
export const site = {
  name: "Honey Summer",
  tagline: "Flower Farm & Floral Design",
  location: "Mountain Top, Pennsylvania",
  serviceArea:
    "Mountain Top and the greater Northeast Pennsylvania area, including Wilkes-Barre and the surrounding Wyoming Valley.",
  description:
    "Seasonal flowers, garden-inspired floral design, and florist wholesale in Mountain Top and Northeast Pennsylvania.",
  email: "hello@hellohoneysummer.com", // client to provide
  phone: "", // client to provide
  instagram: "", // client to provide
  announcementFallback: "Our growing season is waking up — spring flowers coming soon",
} as const;

export const pickup = {
  location: "The Honey Summer flower farm, Mountain Top, PA",
  window: "Pickup windows are shared with your order confirmation.",
  note: "Our growing space is not open to the public unless announced.",
} as const;
