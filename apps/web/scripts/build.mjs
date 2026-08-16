import { cp, mkdir, rm } from "node:fs/promises";
import { spawnSync } from "node:child_process";

await rm("dist", { force: true, recursive: true });
await mkdir("dist", { recursive: true });
const compile = spawnSync(
  process.platform === "win32" ? "node_modules/.bin/tsc.cmd" : "node_modules/.bin/tsc",
  ["--noEmit", "false", "--outDir", "dist"],
  { stdio: "inherit" },
);
if (compile.status !== 0) {
  process.exit(compile.status ?? 1);
}
await cp("index.html", "dist/index.html");
await cp("styles.css", "dist/styles.css");
