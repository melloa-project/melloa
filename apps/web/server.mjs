import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import { isIP } from "node:net";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const host = "127.0.0.1";
const port = Number.parseInt(process.env.MELLOA_WEB_PORT ?? "8787", 10);
const defaultCoreUrl = "http://127.0.0.1:8000";
const maximumRequestBodyBytes = 1_048_576;
const proxiedMethods = new Set(["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]);
const proxiedMethodsHeader = [...proxiedMethods].join(", ");
const types = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".webp", "image/webp"],
  [".woff2", "font/woff2"],
]);

function normalizedHostname(hostname) {
  return hostname.startsWith("[") && hostname.endsWith("]")
    ? hostname.slice(1, -1).toLowerCase()
    : hostname.toLowerCase();
}

function literalHostnameFromOrigin(value) {
  const rawValue = value instanceof URL ? value.href : value;
  if (
    typeof rawValue !== "string"
    || rawValue.trim() !== rawValue
    || /[\u0000-\u0020\u007f]/u.test(rawValue)
  ) {
    return undefined;
  }
  const match = /^https?:\/\/(\[[^\]]+\]|[^:/?#]+)(?::[0-9]+)?\/?$/iu.exec(rawValue);
  if (match === null) {
    return undefined;
  }
  const hostname = match[1];
  const normalized = normalizedHostname(hostname);
  return normalized === "localhost" || isIP(normalized) !== 0 ? hostname : undefined;
}

function isPrivateEndpoint(hostname) {
  const hostName = normalizedHostname(hostname);
  // RFC 6761 reserves this exact name for loopback resolution. Do not broaden
  // this allowance to suffixes or arbitrary DNS names that can be rebound.
  if (hostName === "localhost") {
    return true;
  }
  const version = isIP(hostName);
  if (version === 4) {
    const [first, second] = hostName.split(".").map((value) => Number.parseInt(value, 10));
    return (
      first === 127
      || first === 10
      || (first === 172 && second >= 16 && second <= 31)
      || (first === 192 && second === 168)
    );
  }
  if (version === 6) {
    if (hostName === "::1") {
      return true;
    }
    // Reject mapped/embedded IPv4 spellings instead of applying the IPv4
    // policy to a representation that can bypass literal-address checks.
    if (hostName.includes(".")) {
      return false;
    }
    // The first textual hextet is the high-order hextet. Looking for the
    // first *non-empty* hextet would incorrectly accept ::fc00:1 as ULA.
    const firstHextet = hostName.split(":", 1)[0];
    if (firstHextet.length === 0) {
      return false;
    }
    const firstValue = Number.parseInt(firstHextet, 16);
    return firstValue >= 0xfc00 && firstValue <= 0xfdff;
  }
  return false;
}

export function validateCoreUrl(value) {
  let coreUrl;
  try {
    coreUrl = new URL(value);
  } catch (error) {
    throw new Error("MELLOA_CORE_URL must be an absolute HTTP(S) origin", { cause: error });
  }
  if ((coreUrl.protocol !== "http:" && coreUrl.protocol !== "https:") || !coreUrl.hostname) {
    throw new Error("MELLOA_CORE_URL must use HTTP or HTTPS with a host");
  }
  if (
    coreUrl.username
    || coreUrl.password
    || coreUrl.pathname !== "/"
    || coreUrl.search
    || coreUrl.hash
  ) {
    throw new Error("MELLOA_CORE_URL cannot contain credentials, path, query, or fragment");
  }
  const literalHostname = literalHostnameFromOrigin(value);
  if (literalHostname === undefined) {
    throw new Error("MELLOA_CORE_URL must use exact localhost or a private literal IP");
  }
  if (!isPrivateEndpoint(literalHostname)) {
    throw new Error("MELLOA_CORE_URL must use localhost or a private literal IP");
  }
  return new URL(coreUrl.origin);
}

export function coreOriginFromEnvironment(environment = process.env) {
  return validateCoreUrl(environment.MELLOA_CORE_URL ?? defaultCoreUrl);
}

function defaultStaticRoot() {
  return resolve(fileURLToPath(new URL("./dist/", import.meta.url)));
}

const hopByHopHeaders = new Set([
  "connection",
  "keep-alive",
  "proxy-connection",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function connectionHeaderNames(value) {
  const values = Array.isArray(value) ? value : [value];
  return new Set(values.flatMap((item) => typeof item === "string"
    ? item.split(",").map((name) => name.trim().toLowerCase()).filter(Boolean)
    : []));
}

function requestBodyExceedsLimit(request) {
  const contentLength = request.headers["content-length"];
  if (contentLength === undefined) {
    return false;
  }
  return !/^\d+$/u.test(contentLength)
    || BigInt(contentLength) > BigInt(maximumRequestBodyBytes);
}

async function readRequestBody(request) {
  if (requestBodyExceedsLimit(request)) {
    throw new Error("request_body_too_large");
  }
  const chunks = [];
  let length = 0;
  for await (const chunk of request) {
    length += chunk.length;
    if (length > maximumRequestBodyBytes) {
      throw new Error("request_body_too_large");
    }
    chunks.push(chunk);
  }
  return chunks.length === 0 ? undefined : Buffer.concat(chunks);
}

function writeProxyError(response, status, code, message) {
  const payload = Buffer.from(JSON.stringify({ code, message }));
  response.writeHead(status, {
    "Cache-Control": "no-store",
    "Content-Length": String(payload.length),
    "Content-Type": "application/json; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
  }).end(payload);
}

function isStaticFile(path) {
  try {
    return statSync(path, { throwIfNoEntry: false })?.isFile() === true;
  } catch {
    return false;
  }
}

function writeStaticError(response, status, headers = {}) {
  response.writeHead(status, {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    ...headers,
  }).end();
}

async function proxyToCore(request, response, url, core) {
  try {
    const connectionHeaders = connectionHeaderNames(request.headers.connection);
    const headers = new Headers();
    for (const [name, value] of Object.entries(request.headers)) {
      if (
        value !== undefined
        && !hopByHopHeaders.has(name)
        && !connectionHeaders.has(name)
        && name !== "accept-encoding"
        && name !== "content-length"
        && name !== "host"
      ) {
        headers.set(name, Array.isArray(value) ? value.join(", ") : value);
      }
    }
    // Fetch decodes standard content encodings before arrayBuffer() returns.
    // Request identity so forwarded entity headers remain truthful.
    headers.set("accept-encoding", "identity");
    const body = request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await readRequestBody(request);
    const upstream = await fetch(new URL(`${url.pathname}${url.search}`, core), {
      method: request.method,
      headers,
      body,
      redirect: "manual",
    });
    const upstreamConnectionHeaders = connectionHeaderNames(upstream.headers.get("connection"));
    const responseHeaders = {};
    for (const [name, value] of upstream.headers) {
      if (
        !hopByHopHeaders.has(name)
        && !upstreamConnectionHeaders.has(name)
        && name !== "content-encoding"
        && name !== "content-length"
        && name !== "set-cookie"
      ) {
        responseHeaders[name] = value;
      }
    }
    const cookies = upstream.headers.getSetCookie();
    if (cookies.length > 0 && !upstreamConnectionHeaders.has("set-cookie")) {
      responseHeaders["set-cookie"] = cookies;
    }
    const payload = Buffer.from(await upstream.arrayBuffer());
    const upstreamContentLength = upstream.headers.get("content-length");
    responseHeaders["content-length"] = request.method === "HEAD" && /^\d+$/u.test(upstreamContentLength ?? "")
      ? upstreamContentLength
      : String(payload.length);
    response.writeHead(upstream.status, responseHeaders).end(payload);
  } catch (error) {
    if (error instanceof Error && error.message === "request_body_too_large") {
      writeProxyError(
        response,
        413,
        "request_body_too_large",
        "Request body exceeds the 1 MiB Owner Console proxy limit.",
      );
      return;
    }
    writeProxyError(response, 502, "core_proxy_unavailable", "Private core unavailable.");
  }
}

export function createOwnerConsoleServer({
  staticRoot = defaultStaticRoot(),
  core = coreOriginFromEnvironment(),
} = {}) {
  const validatedCore = validateCoreUrl(core);
  const resolvedStaticRoot = resolve(staticRoot);
  return createServer(async (request, response) => {
    let url;
    try {
      url = new URL(request.url ?? "/", "http://localhost");
    } catch {
      writeStaticError(response, 400);
      return;
    }
    if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/health/")) {
      if (!proxiedMethods.has(request.method ?? "GET")) {
        response.writeHead(405, {
          Allow: proxiedMethodsHeader,
          "Cache-Control": "no-store",
          "X-Content-Type-Options": "nosniff",
        }).end();
        return;
      }
      await proxyToCore(request, response, url, validatedCore);
      return;
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      writeStaticError(response, 405, { Allow: "GET, HEAD" });
      return;
    }
    let requested;
    try {
      const decodedPath = decodeURIComponent(url.pathname);
      if (/[\u0000-\u001f\u007f]/u.test(decodedPath)) {
        writeStaticError(response, 400);
        return;
      }
      requested = decodedPath === "/"
        ? "index.html"
        : normalize(decodedPath).replace(/^[/\\]+/, "");
    } catch {
      writeStaticError(response, 400);
      return;
    }
    let path = resolve(resolvedStaticRoot, requested);
    const insideRoot = path === resolvedStaticRoot || path.startsWith(`${resolvedStaticRoot}${sep}`);
    if (!insideRoot) {
      writeStaticError(response, 404);
      return;
    }
    if (!isStaticFile(path) && extname(requested) === "") {
      path = join(resolvedStaticRoot, "index.html");
    }
    if (!isStaticFile(path)) {
      writeStaticError(response, 404);
      return;
    }
    const immutableAsset = requested.startsWith("assets/") && path !== join(resolvedStaticRoot, "index.html");
    response.writeHead(200, {
      "Cache-Control": immutableAsset ? "public, max-age=31536000, immutable" : "no-store",
      "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'",
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
    const stream = createReadStream(path);
    stream.on("error", () => {
      if (!response.headersSent) {
        writeStaticError(response, 404);
        return;
      }
      response.destroy();
    });
    stream.pipe(response);
  });
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  createOwnerConsoleServer().listen(port, host, () => {
    console.log(`Melloa Owner Console: http://${host}:${port}`);
  });
}
