import { getAnnouncement } from "@/lib/api";
import { AnnouncementBannerLive } from "./announcement-banner-live";

export async function AnnouncementBanner() {
  // Server-rendered for the first paint; the live component keeps it fresh.
  const announcement = await getAnnouncement();
  return <AnnouncementBannerLive initial={announcement} />;
}
