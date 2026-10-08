"use client";

import { useEffect, useState } from "react";

import type { Announcement } from "@/lib/api";
import { site } from "@/lib/site";

/**
 * Announcement banner that stays fresh without making its pages dynamic.
 *
 * The server renders the cached announcement for an instant, flash-free first
 * paint. After hydration this component re-fetches it with `no-store`, so an
 * edit in the admin shows up as soon as the page loads — and when you come
 * back to the tab — while every route remains statically generated.
 */
export function AnnouncementBannerLive({
  initial,
}: {
  initial: Announcement | null;
}) {
  const [announcement, setAnnouncement] = useState<Announcement | null>(initial);

  useEffect(() => {
    let active = true;

    async function refresh() {
      try {
        const response = await fetch("/api/announcement/", {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          return;
        }
        const data = (await response.json()) as { announcement: Announcement | null };
        if (active) {
          setAnnouncement(data.announcement ?? null);
        }
      } catch {
        // Keep the server-rendered announcement if the refresh fails.
      }
    }

    refresh();
    function onVisibilityChange() {
      if (document.visibilityState === "visible") {
        refresh();
      }
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      active = false;
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

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
