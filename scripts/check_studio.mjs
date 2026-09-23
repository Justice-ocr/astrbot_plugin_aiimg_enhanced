import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { artifactDigests, sourceDigest } from "./studio_integrity.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(root, "pages", "Settings");
const manifest = JSON.parse(await readFile(path.join(target, ".studio-integrity.json"), "utf8"));
const source = await sourceDigest(root);
const files = await artifactDigests(target);
if (manifest.source !== source || JSON.stringify(manifest.files) !== JSON.stringify(files)) {
  throw new Error("Studio 源码、依赖锁文件或安装产物不一致，请重新构建并安装");
}
console.log("Studio source and installed assets match");
