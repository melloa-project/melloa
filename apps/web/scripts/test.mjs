import { readdir, rm } from "node:fs/promises";
import { spawnSync } from "node:child_process";

const output = ".test-dist";
await rm(output, { force: true, recursive: true });
try {
  const compiler = process.platform === "win32" ? "node_modules/.bin/tsc.cmd" : "node_modules/.bin/tsc";
  const compile = spawnSync(compiler, ["--noEmit", "false", "--outDir", output], {
    stdio: "inherit",
  });
  if (compile.status !== 0) {
    process.exitCode = compile.status ?? 1;
  } else {
    const tests = (await readdir("tests"))
      .filter((name) => name.endsWith(".test.mjs"))
      .sort()
      .map((name) => `tests/${name}`);
    const result = spawnSync(process.execPath, ["--test", ...tests], { stdio: "inherit" });
    process.exitCode = result.status ?? 1;
  }
} finally {
  await rm(output, { force: true, recursive: true });
}
