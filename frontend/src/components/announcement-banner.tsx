import { getAnnouncement, getSiteContent } from "@/lib/api";
import { site } from "@/lib/site";
import { AnnouncementBannerLive } from "./announcement-banner-live";

export async function AnnouncementBanner() {
  // Server-rendered for the first paint; the live component keeps it fresh.
  const [announcement, content] = await Promise.all([getAnnouncement(), getSiteContent()]);
  return <AnnouncementBannerLive initial={announcement} fallback={content.announcementFallback || site.announcementFallback} />;
}
