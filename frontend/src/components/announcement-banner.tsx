import { getAnnouncement } from "@/lib/api";
import { site } from "@/lib/site";

export async function AnnouncementBanner() {
  const announcement = await getAnnouncement();
  const text = announcement?.text ?? site.announcementFallback;
  const link = announcement?.link_url;

  return (
    <div className="announcement">
      <p>
        {text}
        {link ? (
          <>
            {" "}
            <a href={link} target="_blank" rel="noreferrer">
              {announcement?.link_label || "Learn more"}
            </a>
          </>
        ) : null}
      </p>
    </div>
  );
}
