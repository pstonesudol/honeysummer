const prefixes = ["/api", "/admin", "/media"];
export const maxProxyBodyBytes = 12 * 1024 * 1024;

function tooLarge() {
  return new Response("Request body exceeds 12 MiB.", {
    status: 413,
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
  });
}

export function isBackendPath(path) {
  return prefixes.some(prefix => path === prefix || path.startsWith(`${prefix}/`));
}

export async function proxyBackend(request, apiOrigin, fetcher = fetch, originHeaders = {}) {
  const incoming = new URL(request.url);
  if (!isBackendPath(incoming.pathname)) throw new Error("Not a backend route.");
  const backend = new URL(apiOrigin);
  if (backend.protocol !== "https:" || backend.username || backend.password ||
      backend.pathname !== "/" || backend.search || backend.hash) {
    throw new Error("Backend must be a configured HTTPS origin.");
  }
  // Assign path/search separately: a client-supplied // path must never replace
  // the configured backend origin or turn this into an open proxy.
  const destination = new URL(backend.origin);
  destination.pathname = incoming.pathname;
  destination.search = incoming.search;
  const headers = new Headers(request.headers);
  // A browser must never choose this trust credential, including in production.
  headers.delete("X-HoneySummer-Origin-Secret");
  for (const [name, value] of Object.entries(originHeaders)) headers.set(name, value);
  for (const header of ["host", "connection", "keep-alive", "transfer-encoding",
    "upgrade", "proxy-authorization", "proxy-authenticate", "cf-connecting-ip",
    // Access service credentials/JWT authenticate at Cloudflare's edge only.
    // Never forward them to Railway or any redirect target.
    "cf-access-client-id", "cf-access-client-secret", "cf-access-jwt-assertion"]) {
    headers.delete(header);
  }
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  if (hasBody && Number(headers.get("content-length")) > maxProxyBodyBytes) return tooLarge();
  let exceeded = false;
  let body = request.body;
  if (hasBody && body) {
    const reader = body.getReader();
    let bytes = 0;
    // Preserve the existing Next proxy's 12 MiB limit, including chunked uploads
    // without Content-Length, without buffering uploads into Worker memory.
    body = new ReadableStream({
      async pull(controller) {
        const chunk = await reader.read();
        if (chunk.done) { controller.close(); return; }
        bytes += chunk.value.byteLength;
        if (bytes > maxProxyBodyBytes) {
          exceeded = true;
          controller.error(new Error("Body limit exceeded."));
          await reader.cancel();
          return;
        }
        controller.enqueue(chunk.value);
      },
      cancel(reason) { return reader.cancel(reason); },
    });
  }
  const upstreamRequest = new Request(destination, {
    method: request.method, headers,
    ...(hasBody ? { body, duplex: "half" } : {}),
    // Essential: return the login redirect and its cookie to the browser.
    // Following it here requests /admin without the newly issued session.
    redirect: "manual", signal: request.signal,
  });
  let upstream;
  try {
    upstream = await fetcher(upstreamRequest);
  } catch (error) {
    if (exceeded) return tooLarge();
    throw error;
  }
  if (exceeded) return tooLarge();
  const responseHeaders = new Headers(upstream.headers);
  const location = responseHeaders.get("location");
  if (location) {
    const redirect = new URL(location, destination);
    if (redirect.origin === backend.origin) {
      responseHeaders.set("location", `${redirect.pathname}${redirect.search}${redirect.hash}`);
    }
  }
  if (incoming.pathname.startsWith("/admin") || incoming.pathname.startsWith("/api/auth")) {
    responseHeaders.set("Cache-Control", "no-store");
  }
  // Headers preserves separate Set-Cookie fields (including deletion cookies).
  // No values/flags/domains are weakened and the body remains streamed.
  return new Response(upstream.body, {
    status: upstream.status, statusText: upstream.statusText, headers: responseHeaders,
  });
}
