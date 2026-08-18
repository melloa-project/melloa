import { once } from "node:events";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { createServer, request as requestHttp } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

import { describe, expect, it } from "vitest";

import {
  coreOriginFromEnvironment,
  createOwnerConsoleServer,
  validateCoreUrl,
} from "../server.mjs";

async function listenOnLoopback(server) {
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new Error("test server did not expose a TCP address");
  }
  return `http://127.0.0.1:${address.port}`;
}

async function closeServer(server) {
  if (!server.listening) {
    return;
  }
  await new Promise((resolve, reject) => {
    server.close((error) => error === undefined ? resolve() : reject(error));
  });
}

async function createStaticRoot(files) {
  const root = await mkdtemp(join(tmpdir(), "melloa-owner-console-"));
  await Promise.all(Object.entries(files).map(async ([path, content]) => {
    const target = join(root, path);
    await mkdir(join(target, ".."), { recursive: true });
    await writeFile(target, content);
  }));
  return root;
}

async function requestWithNodeHttp(url, { body, headers, method = "GET" } = {}) {
  return await new Promise((resolve, reject) => {
    const request = requestHttp(url, { headers, method }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => resolve({
        body: Buffer.concat(chunks),
        headers: response.headers,
        status: response.statusCode,
      }));
    });
    request.on("error", reject);
    request.end(body);
  });
}

describe("Owner Console server core target validation", () => {
  it.each([
    ["http://127.0.0.1:8000", "http://127.0.0.1:8000"],
    ["http://localhost:8000", "http://localhost:8000"],
    ["http://10.1.2.3:8000", "http://10.1.2.3:8000"],
    ["http://172.16.0.1:8000", "http://172.16.0.1:8000"],
    ["http://172.31.255.255:8000", "http://172.31.255.255:8000"],
    ["http://192.168.1.50:8000", "http://192.168.1.50:8000"],
    ["http://[::1]:8000", "http://[::1]:8000"],
    ["https://[fc00::1]:8443", "https://[fc00::1]:8443"],
    ["https://[fdff::1]:8443", "https://[fdff::1]:8443"],
  ])("accepts exact local/private origin %s", (value, expected) => {
    expect(validateCoreUrl(value).href).toBe(`${expected}/`);
  });

  it.each([
    "ftp://127.0.0.1:8000",
    "http://owner:secret@127.0.0.1:8000",
    "http://127.0.0.1:8000/api",
    "http://127.0.0.1:8000//",
    "http://127.0.0.1:8000?debug=true",
    "http://127.0.0.1:8000#fragment",
    " http://127.0.0.1:8000",
    "http://127.0.0.1:8000\n",
    "http://127.0.0.\t1:8000",
    "http://8.8.8.8:8000",
    "http://0.0.0.0:8000",
    "http://255.255.255.255:8000",
    "http://100.64.0.1:8000",
    "http://100.100.10.20:8000",
    "http://100.127.255.255:8000",
    "http://100.128.0.1:8000",
    "http://172.15.255.255:8000",
    "http://172.32.0.1:8000",
    "http://169.254.1.1:8000",
    "http://169.254.169.254:8000",
    "http://224.0.0.1:8000",
    "http://example.com:8000",
    "http://core.local:8000",
    "http://localhost.:8000",
    "http://127.0.0.1.nip.io:8000",
    "http://127.1:8000",
    "http://0177.0.0.1:8000",
    "http://2130706433:8000",
    "http://0x7f000001:8000",
    "http://192.168.001.001:8000",
    "http://[::]:8000",
    "http://[::ffff:127.0.0.1]:8000",
    "http://[::ffff:10.0.0.1]:8000",
    "http://[::fc00:1]:8000",
    "http://[::fd00:1]:8000",
    "http://[fc0::1]:8000",
    "http://[fc00::192.168.1.1]:8000",
    "http://[fe80::1]:8000",
    "http://[ff02::1]:8000",
    "http://[2001:4860:4860::8888]:8000",
  ])("rejects unsafe or ambiguous core target %s", (value) => {
    expect(() => validateCoreUrl(value)).toThrow(/MELLOA_CORE_URL/);
  });

  it("uses the loopback core origin by default", () => {
    expect(coreOriginFromEnvironment({}).href).toBe("http://127.0.0.1:8000/");
  });

  it("rejects unsafe environment values before server creation", () => {
    expect(() => coreOriginFromEnvironment({
      MELLOA_CORE_URL: "https://public.example",
    })).toThrow(/private literal IP/);
  });

  it("rejects unsafe environment values before creating a listener", () => {
    const previous = process.env.MELLOA_CORE_URL;
    process.env.MELLOA_CORE_URL = "https://public.example";
    try {
      expect(() => createOwnerConsoleServer({ staticRoot: "/tmp" })).toThrow(/private literal IP/);
    } finally {
      if (previous === undefined) {
        delete process.env.MELLOA_CORE_URL;
      } else {
        process.env.MELLOA_CORE_URL = previous;
      }
    }
  });

  it("rejects an unsafe injected core target before creating a listener", () => {
    expect(() => createOwnerConsoleServer({
      core: "https://public.example",
      staticRoot: "/tmp",
    })).toThrow(/private literal IP/);
  });

  it("preserves same-origin owner headers and upstream session cookies", async () => {
    let observedRequest;
    const upstream = createServer((request, response) => {
      observedRequest = {
        cookie: request.headers.cookie,
        csrf: request.headers["x-csrf-token"],
        proof: request.headers["x-owner-proof"],
        host: request.headers.host,
        url: request.url,
      };
      response.writeHead(200, {
        "Content-Type": "application/json",
        "Set-Cookie": "__Host-melloa_session=opaque; Path=/; Secure; HttpOnly; SameSite=Strict",
        "X-Upstream-Evidence": "preserved",
      }).end('{"ok":true}');
    });
    const upstreamOrigin = await listenOnLoopback(upstream);
    const ownerConsole = createOwnerConsoleServer({
      core: upstreamOrigin,
      staticRoot: "/tmp",
    });

    try {
      const ownerConsoleOrigin = await listenOnLoopback(ownerConsole);
      const response = await fetch(`${ownerConsoleOrigin}/api/v1/session?view=active`, {
        headers: {
          Cookie: "__Host-melloa_session=owner-session",
          "X-Csrf-Token": "csrf-proof",
          "X-Owner-Proof": "same-origin",
        },
      });

      expect(await response.json()).toEqual({ ok: true });
      expect(response.headers.get("x-upstream-evidence")).toBe("preserved");
      expect(response.headers.getSetCookie()).toEqual([
        "__Host-melloa_session=opaque; Path=/; Secure; HttpOnly; SameSite=Strict",
      ]);
      expect(observedRequest).toEqual({
        cookie: "__Host-melloa_session=owner-session",
        csrf: "csrf-proof",
        proof: "same-origin",
        host: new URL(upstreamOrigin).host,
        url: "/api/v1/session?view=active",
      });
    } finally {
      await closeServer(ownerConsole);
      await closeServer(upstream);
    }
  });
});

describe("Owner Console server static and proxy behavior", () => {
  it("serves static files, SPA fallbacks, and security headers without leaking unsupported methods", async () => {
    const staticRoot = await createStaticRoot({
      "index.html": "<!doctype html><title>Melloa</title><main>Owner console</main>",
      "assets/app.js": "console.log('melloa')",
    });
    const ownerConsole = createOwnerConsoleServer({
      core: "http://127.0.0.1:8000",
      staticRoot,
    });

    try {
      const ownerConsoleOrigin = await listenOnLoopback(ownerConsole);
      const index = await fetch(`${ownerConsoleOrigin}/conversation`);
      expect(index.status).toBe(200);
      expect(await index.text()).toContain("Owner console");
      expect(index.headers.get("cache-control")).toBe("no-store");
      expect(index.headers.get("content-security-policy")).toContain("default-src 'self'");
      expect(index.headers.get("cross-origin-resource-policy")).toBe("same-origin");
      expect(index.headers.get("referrer-policy")).toBe("no-referrer");
      expect(index.headers.get("x-content-type-options")).toBe("nosniff");
      expect(index.headers.get("x-frame-options")).toBe("DENY");

      const asset = await fetch(`${ownerConsoleOrigin}/assets/app.js`);
      expect(asset.status).toBe(200);
      expect(await asset.text()).toBe("console.log('melloa')");
      expect(asset.headers.get("cache-control")).toBe("public, max-age=31536000, immutable");
      expect(asset.headers.get("content-type")).toBe("text/javascript; charset=utf-8");

      const head = await fetch(`${ownerConsoleOrigin}/assets/app.js`, { method: "HEAD" });
      expect(head.status).toBe(200);
      expect(await head.text()).toBe("");
      expect(head.headers.get("cache-control")).toBe("public, max-age=31536000, immutable");
      expect(head.headers.get("content-type")).toBe("text/javascript; charset=utf-8");

      const post = await fetch(`${ownerConsoleOrigin}/conversation`, { method: "POST" });
      expect(post.status).toBe(405);
      expect(post.headers.get("allow")).toBe("GET, HEAD");

      const traversal = await fetch(`${ownerConsoleOrigin}/..%2Fserver.mjs`);
      expect(traversal.status).toBe(404);

      const malformedPath = await fetch(`${ownerConsoleOrigin}/%E0%A4%A`);
      expect(malformedPath.status).toBe(400);

      for (const invalidPath of ["/%00", "/%0A", "/%7F"]) {
        const invalid = await requestWithNodeHttp(`${ownerConsoleOrigin}${invalidPath}`);
        expect(invalid.status).toBe(400);
        expect(invalid.headers["cache-control"]).toBe("no-store");
        expect(invalid.headers["x-content-type-options"]).toBe("nosniff");
      }

      const afterMalformedPath = await fetch(`${ownerConsoleOrigin}/`);
      expect(afterMalformedPath.status).toBe(200);
      expect(await afterMalformedPath.text()).toContain("Owner console");
    } finally {
      await closeServer(ownerConsole);
      await rm(staticRoot, { force: true, recursive: true });
    }
  });

  it("forwards method, body, owner headers, and upstream security headers on proxy routes", async () => {
    let observedRequest;
    const upstream = createServer((request, response) => {
      const chunks = [];
      request.on("data", (chunk) => chunks.push(chunk));
      request.on("end", () => {
        observedRequest = {
          body: Buffer.concat(chunks).toString("utf8"),
          contentType: request.headers["content-type"],
          cookie: request.headers.cookie,
          csrf: request.headers["x-csrf-token"],
          host: request.headers.host,
          method: request.method,
          url: request.url,
        };
        response.writeHead(201, {
          "Cache-Control": "no-store",
          Connection: "X-Upstream-Hop",
          "Content-Security-Policy": "default-src 'none'",
          "Content-Type": "application/json",
          "X-Content-Type-Options": "nosniff",
          "X-Upstream-Hop": "must-not-leak",
        }).end('{"created":true}');
      });
    });
    const upstreamOrigin = await listenOnLoopback(upstream);
    const ownerConsole = createOwnerConsoleServer({
      core: upstreamOrigin,
      staticRoot: "/tmp",
    });

    try {
      const ownerConsoleOrigin = await listenOnLoopback(ownerConsole);
      const response = await fetch(`${ownerConsoleOrigin}/api/v1/messages?draft=true`, {
        body: JSON.stringify({ text: "owner draft" }),
        headers: {
          "Content-Type": "application/json",
          Cookie: "__Host-melloa_session=owner-session",
          "X-Csrf-Token": "csrf-proof",
        },
        method: "POST",
      });

      expect(response.status).toBe(201);
      expect(await response.json()).toEqual({ created: true });
      expect(response.headers.get("cache-control")).toBe("no-store");
      expect(response.headers.get("content-security-policy")).toBe("default-src 'none'");
      expect(response.headers.get("content-length")).toBe("16");
      expect(response.headers.get("x-content-type-options")).toBe("nosniff");
      expect(response.headers.get("x-upstream-hop")).toBeNull();
      expect(observedRequest).toEqual({
        body: '{"text":"owner draft"}',
        contentType: "application/json",
        cookie: "__Host-melloa_session=owner-session",
        csrf: "csrf-proof",
        host: new URL(upstreamOrigin).host,
        method: "POST",
        url: "/api/v1/messages?draft=true",
      });
    } finally {
      await closeServer(ownerConsole);
      await closeServer(upstream);
    }
  });

  it("strips connection-scoped request and response headers", async () => {
    let observedRequest;
    const upstream = createServer((request, response) => {
      observedRequest = {
        acceptEncoding: request.headers["accept-encoding"],
        clientHop: request.headers["x-client-hop"],
      };
      response.writeHead(200, {
        Connection: "X-Upstream-Hop",
        "Content-Type": "application/json",
        "X-Preserved": "end-to-end",
        "X-Upstream-Hop": "private-hop",
      }).end("{}");
    });
    const upstreamOrigin = await listenOnLoopback(upstream);
    const ownerConsole = createOwnerConsoleServer({
      core: upstreamOrigin,
      staticRoot: "/tmp",
    });

    try {
      const ownerConsoleOrigin = await listenOnLoopback(ownerConsole);
      const response = await requestWithNodeHttp(`${ownerConsoleOrigin}/api/v1/status`, {
        headers: {
          Connection: "X-Client-Hop",
          "X-Client-Hop": "browser-hop",
        },
      });

      expect(response.status).toBe(200);
      expect(response.headers["x-preserved"]).toBe("end-to-end");
      expect(response.headers["x-upstream-hop"]).toBeUndefined();
      expect(observedRequest).toEqual({
        acceptEncoding: "identity",
        clientHop: undefined,
      });
    } finally {
      await closeServer(ownerConsole);
      await closeServer(upstream);
    }
  });

  it("keeps decoded response headers truthful and preserves HEAD length", async () => {
    const payload = Buffer.from('{"status":"ready"}');
    const upstream = createServer((request, response) => {
      if (request.method === "HEAD") {
        response.writeHead(200, {
          "Content-Length": "37",
          "Content-Type": "application/json",
        }).end();
        return;
      }
      const compressed = gzipSync(payload);
      response.writeHead(200, {
        "Content-Encoding": "gzip",
        "Content-Length": String(compressed.length),
        "Content-Type": "application/json",
      }).end(compressed);
    });
    const upstreamOrigin = await listenOnLoopback(upstream);
    const ownerConsole = createOwnerConsoleServer({
      core: upstreamOrigin,
      staticRoot: "/tmp",
    });

    try {
      const ownerConsoleOrigin = await listenOnLoopback(ownerConsole);
      const decoded = await fetch(`${ownerConsoleOrigin}/health/ready`);
      expect(await decoded.json()).toEqual({ status: "ready" });
      expect(decoded.headers.get("content-encoding")).toBeNull();
      expect(decoded.headers.get("content-length")).toBe(String(payload.length));

      const head = await fetch(`${ownerConsoleOrigin}/health/ready`, { method: "HEAD" });
      expect(head.status).toBe(200);
      expect(head.headers.get("content-length")).toBe("37");
      expect(await head.text()).toBe("");
    } finally {
      await closeServer(ownerConsole);
      await closeServer(upstream);
    }
  });

  it("rejects unsupported proxy methods before the private core handles them", async () => {
    let upstreamHit = false;
    const upstream = createServer((_request, response) => {
      upstreamHit = true;
      response.writeHead(204).end();
    });
    const upstreamOrigin = await listenOnLoopback(upstream);
    const ownerConsole = createOwnerConsoleServer({
      core: upstreamOrigin,
      staticRoot: "/tmp",
    });

    try {
      const ownerConsoleOrigin = await listenOnLoopback(ownerConsole);
      const response = await requestWithNodeHttp(`${ownerConsoleOrigin}/api/v1/messages`, {
        method: "PROPFIND",
      });
      expect(response.status).toBe(405);
      expect(response.headers.allow).toBe("DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT");
      expect(response.headers["cache-control"]).toBe("no-store");
      expect(upstreamHit).toBe(false);
    } finally {
      await closeServer(ownerConsole);
      await closeServer(upstream);
    }
  });

  it("rejects oversized proxied request bodies before the private core handles them", async () => {
    let upstreamHit = false;
    const upstream = createServer((_request, response) => {
      upstreamHit = true;
      response.writeHead(204).end();
    });
    const upstreamOrigin = await listenOnLoopback(upstream);
    const ownerConsole = createOwnerConsoleServer({
      core: upstreamOrigin,
      staticRoot: "/tmp",
    });

    try {
      const ownerConsoleOrigin = await listenOnLoopback(ownerConsole);
      const response = await fetch(`${ownerConsoleOrigin}/api/v1/messages`, {
        body: Buffer.alloc(1_048_577, "x"),
        method: "POST",
      });
      expect(response.status).toBe(413);
      expect(await response.json()).toEqual({
        code: "request_body_too_large",
        message: "Request body exceeds the 1 MiB Owner Console proxy limit.",
      });
      expect(response.headers.get("cache-control")).toBe("no-store");
      expect(response.headers.get("x-content-type-options")).toBe("nosniff");
      expect(upstreamHit).toBe(false);
    } finally {
      await closeServer(ownerConsole);
      await closeServer(upstream);
    }
  });

  it("allows a proxied request body at the one MiB boundary", async () => {
    let observedLength = 0;
    const upstream = createServer((request, response) => {
      request.on("data", (chunk) => {
        observedLength += chunk.length;
      });
      request.on("end", () => response.writeHead(204).end());
    });
    const upstreamOrigin = await listenOnLoopback(upstream);
    const ownerConsole = createOwnerConsoleServer({
      core: upstreamOrigin,
      staticRoot: "/tmp",
    });

    try {
      const ownerConsoleOrigin = await listenOnLoopback(ownerConsole);
      const response = await fetch(`${ownerConsoleOrigin}/api/v1/messages`, {
        body: Buffer.alloc(1_048_576, "x"),
        method: "POST",
      });
      expect(response.status).toBe(204);
      expect(observedLength).toBe(1_048_576);
    } finally {
      await closeServer(ownerConsole);
      await closeServer(upstream);
    }
  });

  it("does not follow private core redirects on behalf of the owner", async () => {
    let upstreamHits = 0;
    const upstream = createServer((_request, response) => {
      upstreamHits += 1;
      response.writeHead(302, {
        Location: "https://example.com/outside-core",
      }).end("redirect");
    });
    const upstreamOrigin = await listenOnLoopback(upstream);
    const ownerConsole = createOwnerConsoleServer({
      core: upstreamOrigin,
      staticRoot: "/tmp",
    });

    try {
      const ownerConsoleOrigin = await listenOnLoopback(ownerConsole);
      const response = await fetch(`${ownerConsoleOrigin}/api/v1/redirect`, {
        redirect: "manual",
      });
      expect(response.status).toBe(302);
      expect(response.headers.get("location")).toBe("https://example.com/outside-core");
      expect(await response.text()).toBe("redirect");
      expect(upstreamHits).toBe(1);
    } finally {
      await closeServer(ownerConsole);
      await closeServer(upstream);
    }
  });

  it("returns a bounded no-store error when the private core is unavailable", async () => {
    const unavailable = createServer();
    const unavailableOrigin = await listenOnLoopback(unavailable);
    await closeServer(unavailable);
    const ownerConsole = createOwnerConsoleServer({
      core: unavailableOrigin,
      staticRoot: "/tmp",
    });

    try {
      const ownerConsoleOrigin = await listenOnLoopback(ownerConsole);
      const response = await fetch(`${ownerConsoleOrigin}/health/ready`);
      expect(response.status).toBe(502);
      expect(response.headers.get("cache-control")).toBe("no-store");
      expect(response.headers.get("content-type")).toBe("application/json; charset=utf-8");
      expect(response.headers.get("x-content-type-options")).toBe("nosniff");
      expect(await response.json()).toEqual({
        code: "core_proxy_unavailable",
        message: "Private core unavailable.",
      });
    } finally {
      await closeServer(ownerConsole);
    }
  });
});
