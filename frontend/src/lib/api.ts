const DEFAULT_API_URL = "http://localhost:8000";

export function getApiBaseUrl(): string {
  return (process.env.API_URL ?? DEFAULT_API_URL).replace(/\/+$/, "");
}

/**
 * Fetch JSON from the API for server components.
 *
 * Marketing content changes rarely, so reads are cached and revalidated every
 * five minutes. Failures fall back to the supplied value so a temporarily
 * unreachable API can never break a page render or a production build.
 */
export async function apiGet<T>(
  path: string,
  fallback: T,
  revalidate = 300,
): Promise<T> {
  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      headers: { Accept: "application/json" },
      next: { revalidate },
      signal: AbortSignal.timeout(4000),
    });
    if (!response.ok) {
      return fallback;
    }
    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}

export type Announcement = {
  id: number;
  text: string;
  link_url: string;
  link_label: string;
};

export type GalleryImage = {
  id: number;
  image: string;
  alt_text: string;
  caption: string;
  sort_order: number;
  focal_x: number;
  focal_y: number;
};

export type SiteContent = Partial<Record<
  | "location" | "serviceArea" | "email" | "phone" | "instagram"
  | "pickupLocation" | "pickupWindow" | "pickupNote"
  | "announcementFallback" | "homeIntro" | "aboutIntro"
  | "weddingsIntro" | "orderIntro" | "contactIntro" | "wholesaleIntro",
  string
>> & { faq?: { question: string; answer: string }[] };

export async function getSiteContent(): Promise<SiteContent> {
  const data = await apiGet<{ content: SiteContent }>("/api/site-content/", { content: {} });
  return data.content ?? {};
}

export type FlowerListing = {
  id: number;
  name: string;
  variety: string;
  color: string;
  photo_url: string;
  stem_notes: string;
  price: string;
  unit: string;
  delivery_fee: string;
  delivery_fee_mode: "per_listing" | "per_unit" | "per_order";
  quantity_available: number;
  sold_out: boolean;
  available: boolean;
};

export async function getAnnouncement(): Promise<Announcement | null> {
  const data = await apiGet<{ announcement: Announcement | null }>(
    "/api/announcement/",
    { announcement: null },
  );
  return data.announcement;
}

export async function getGallery(): Promise<GalleryImage[]> {
  return apiGet<GalleryImage[]>("/api/gallery/", []);
}

/**
 * Standard offerings available to retail customers.
 *
 * Availability changes as flowers sell, so this is revalidated far more
 * often than the slow-moving marketing content. The checkout endpoint holds
 * stock server-side, so a slightly stale grid can never oversell.
 */
export async function getRetailFlowers(): Promise<FlowerListing[]> {
  return apiGet<FlowerListing[]>("/api/retail/flowers/", [], 30);
}
