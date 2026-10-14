# Uploaded display images

## Policy and retention

New public gallery and listing uploads store **only a static WebP display image**:

- At most 2400 pixels on either edge, preserving aspect ratio, no upscaling.
- WebP quality 82, method 4; at most 2 MiB encoded. Complex images shrink by
  20% per pass until they fit, retaining the same encoding quality.
- Apply EXIF orientation, convert embedded ICC profiles to sRGB, and preserve
  transparency (including palette images). Untagged images are assumed sRGB;
  untagged CMYK is converted to RGB. Unusable/unsupported profiles fail with an
  sRGB-export hint. Public animations use only the first frame.
- Strip EXIF (including GPS), ICC and XMP. Store `.webp` / `image/webp`
  regardless of submitted filename or MIME type. Random immutable keys and
  one-year public R2 caching remain. Local development uses the same policy.

**No public-upload original is retained anywhere by the application.** Owners
must keep professional masters in their own backed-up photo library. An upload
is not an archival backup. This avoids accidental public original archives,
extra storage/lifecycle rules, and a second private-original authorization
surface. Tradeoffs: lossy output, no recovery/re-editing of masters here, and
future larger variants require re-uploading the owner's original. This is a
storefront display service, not a professional photo archive.

Customer inquiry photos remain separate: validated original bytes stay in
`R2_PRIVATE_BUCKET` (different from the public bucket), or the private local
root outside `/media`. **No public derivatives or public URLs** are created.
Existing authorized operator retrieval and `private, no-store` responses are
unchanged. Private EXIF/profiles are not rewritten. Historical inquiry-photo
cleanup remains the separate reviewed procedure in `OWNER_OPERATIONS.md`;
this implementation does not perform it.

## Safety and concurrency

The **50 MiB per-image upload** and **60 MiB streaming Worker proxy request**
limits are unchanged. Compressed bytes alone do not bound memory:

- Pillow verifies supported PNG/JPEG/GIF/WebP structure, then actually decodes
  every frame before public or private storage. Magic prefixes and truncated
  images are insufficient. SVG and other formats are rejected.
- Limit edges to 16000 pixels and **40 million total decoded pixels** across
  at most **100 frames**, checked before frame loads. Normalize Pillow bomb
  exceptions to validation errors. A 4000×6000 professional photo fits; a 45/60 MP
  master must be exported below the pixel limit even if below 50 MiB compressed.
- Existing `asyncio.to_thread` calls keep decoding off the event loop. A shared
  nonblocking semaphore permits one validation/encoding operation per process,
  public or private. Overlap gets a retryable validation message, not a wait on
  the decode lock. The slot is released on success/failure.
- Close full-resolution buffers promptly; transpose orientation in place and
  convert color after shrinking. Fully decoding originals is necessary for
  validation; JPEG draft decoding alone would not validate all original pixels.

Local isolated-process measurements (macOS, Python 3.14.8, Pillow 12.3; generated
noisy quality-98 JPEGs with rotation EXIF, not deployed performance claims):

| Source | Upload bytes | Display bytes | Display dimensions | Time | Peak RSS |
| --- | ---: | ---: | --- | ---: | ---: |
| 4000×6000 | 29,329,489 | 1,480,918 | 2400×1600 | 0.50 s | 312 MiB |
| 8000×5000 | 48,883,200 | 1,228,766 | 1500×2400 | 0.61 s | 439 MiB |

These include imports, not Sanic/DB/request overhead. Reserve generous headroom
(start with at least 1 GiB per decoding worker, then measure); native codecs,
profiles, animation and input modes vary. This is **not a global service or
HTTP admission limit**: workers multiply decoder memory, multipart parsing can
buffer/copy large bodies before admission, and the default thread executor/R2
requests can still queue. The Worker streams instead of buffering requests.
Test simultaneous near-limit uploads with ordinary storefront traffic on the
intended worker/memory configuration. If unsafe, separately approve HTTP
concurrency/rate limits, spooled uploads, or isolated image jobs, rather than
blindly increasing limits. No infrastructure/resource changes are made here.

## Existing objects and rollout (requires separate approval)

There is no schema migration, provider mutation, bucket enumeration, automatic
backfill, or fetch-time rewrite. Existing keys keep working unchanged,
**including oversized originals**. Models/APIs retain one public display key.
Gallery, listing/cart, and site-content images already use these keys directly
without Next optimization, so no frontend/UI change is needed. A single bounded
variant is intentionally scoped; this does not claim responsive thumbnails.

After an authorized staging release:

1. Upload a representative master via admin. Check WebP Content-Type,
   dimensions ≤2400, bytes ≤2 MiB, rotation/color/alpha/focal crop and immutable
   caching. Review gallery, product cards/cart and site-content heroes on mobile
   and desktop, cold/warm cache. Check understandable validation/retry errors.
2. Submit a synthetic inquiry photo. Verify original private bytes, absence from
   public storage and `/media`, anonymous denial, and existing authorized
   operator retrieval with no-store. Recheck private bucket access policy.
3. Explicitly inventory legacy public keys/references. Re-upload an owner-held
   master into the **existing gallery row** for a new immutable key. Site-content
   selections reference the row ID. Listings/duplicates store a copied key,
   **not a live gallery relationship**: reselect each affected listing. Historical
   order snapshots can also retain old keys; review them before deletion.
4. Allow API/page cache refresh (normally up to five minutes), verify references,
   then separately approve old-object deletion/CDN purge and retention handling.
   Re-uploading does not delete old originals; old URLs may remain accessible
   and cached for a year. Never overwrite immutable keys or claim old exposure
   is removed automatically.
5. Retest the original finding on the replaced key and perform concurrency/RSS
   checks above before marking deployed delivery resolved.

No deployment or live cleanup was authorized/performed. Tests mock R2 and cannot
prove live access policies, CDN behavior, device visual quality, or Linux RSS.
