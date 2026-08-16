import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const host = "127.0.0.1";
const port = Number.parseInt(process.env.MELLOA_WEB_PORT ?? "8787", 10);
const root = new URL("./dist/", import.meta.url).pathname;
const core = new URL(process.env.MELLOA_CORE_URL ?? "http://127.0.0.1:8000");
if (core.protocol !== "http:" && core.protocol !== "https:") {
  throw new Error("MELLOA_CORE_URL must use HTTP or HTTPS");
}
const types = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
]);

const hopByHopHeaders = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

async function readRequestBody(request) {
  const chunks = [];
  let length = 0;
  for await (const chunk of request) {
    length += chunk.length;
    if (length > 1_048_576) {
      throw new Error("request_body_too_large");
    }
    chunks.push(chunk);
  }
  return chunks.length === 0 ? undefined : Buffer.concat(chunks);
}

async function proxyToCore(request, response, url) {
  try {
    const headers = new Headers();
    for (const [name, value] of Object.entries(request.headers)) {
      if (value !== undefined && !hopByHopHeaders.has(name) && name !== "host") {
        headers.set(name, Array.isArray(value) ? value.join(", ") : value);
      }
    }
    const body = request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await readRequestBody(request);
    const upstream = await fetch(new URL(`${url.pathname}${url.search}`, core), {
      method: request.method,
      headers,
      body,
      redirect: "manual",
    });
    const responseHeaders = {};
    for (const [name, value] of upstream.headers) {
      if (!hopByHopHeaders.has(name) && name !== "content-length" && name !== "set-cookie") {
        responseHeaders[name] = value;
      }
    }
    const cookies = upstream.headers.getSetCookie();
    if (cookies.length > 0) {
      responseHeaders["set-cookie"] = cookies;
    }
    const payload = Buffer.from(await upstream.arrayBuffer());
    responseHeaders["content-length"] = String(payload.length);
    response.writeHead(upstream.status, responseHeaders).end(payload);
  } catch (error) {
    const status = error instanceof Error && error.message === "request_body_too_large" ? 413 : 502;
    response.writeHead(status, {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
    }).end(JSON.stringify({ code: "core_proxy_unavailable", message: "Private core unavailable." }));
  }
}

createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://localhost");
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/health/")) {
    await proxyToCore(request, response, url);
    return;
  }
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" }).end();
    return;
  }
  const requested = url.pathname === "/" ? "index.html" : normalize(url.pathname).replace(/^\/+/, "");
  const path = join(root, requested);
  if (!path.startsWith(root) || !statSync(path, { throwIfNoEntry: false })?.isFile()) {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'",
    "Content-Type": types.get(extname(path)) ?? "application/octet-stream",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
  });
  if (request.method === "HEAD") {
    response.end();
    return;
  }
  createReadStream(path).pipe(response);
}).listen(port, host, () => {
  console.log(`Melloa Owner Console: http://${host}:${port}`);
});
