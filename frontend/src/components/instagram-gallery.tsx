import { Camera } from "lucide-react";

import { getInstagramPosts, type InstagramPost } from "@/lib/api";
import { site } from "@/lib/site";

function PostGrid({ posts }: { posts: InstagramPost[] }) {
  return (
    <ul className="instagram-gallery__grid">
      {posts.map((post) => (
        <li key={post.id}>
          <a
            href={post.permalink}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={post.caption || "View this Honey Summer post on Instagram"}
          >
            {/* Instagram serves media from its own rotating CDN, outside the Next.js image pipeline. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={post.image}
              alt={post.caption || "Honey Summer flowers on Instagram"}
              loading="lazy"
              decoding="async"
            />
          </a>
        </li>
      ))}
    </ul>
  );
}

function FollowLink({ href }: { href: string }) {
  return (
    <a
      className="button button--sm button--primary instagram-gallery__cta"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      <Camera aria-hidden="true" size={16} strokeWidth={1.8} />
      Follow on Instagram
    </a>
  );
}

/**
 * A small strip of the account's most recent posts, linking out to Instagram.
 *
 * ``card`` fits inside the contact page's card; ``strip`` renders its own
 * section for the home page. Both hide themselves when no posts are available
 * (for example, before an access token is configured), leaving a plain profile
 * link on the contact card so the layout never looks broken.
 */
export async function InstagramGallery({
  variant = "card",
  profile = site.instagram,
}: {
  variant?: "card" | "strip";
  profile?: string;
}) {
  const posts = (await getInstagramPosts()).slice(0, 6);

  if (posts.length === 0) {
    return variant === "card" ? (
      <p>
        <a href={profile} target="_blank" rel="noopener noreferrer">
          Instagram
        </a>
      </p>
    ) : null;
  }

  if (variant === "strip") {
    return (
      <section className="instagram-strip section-wrap" aria-labelledby="instagram-strip-title">
        <div className="instagram-strip__intro">
          <p className="eyebrow">Follow along</p>
          <h2 id="instagram-strip-title">
            Fresh from the garden on <em>Instagram.</em>
          </h2>
          <p>See what is blooming right now, plus behind-the-scenes moments from the farm.</p>
        </div>
        <div className="instagram-gallery instagram-gallery--strip">
          <PostGrid posts={posts} />
          <FollowLink href={profile} />
        </div>
      </section>
    );
  }

  return (
    <div className="instagram-gallery instagram-gallery--card">
      <PostGrid posts={posts} />
      <FollowLink href={profile} />
    </div>
  );
}
