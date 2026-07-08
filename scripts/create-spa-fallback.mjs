import { copyFileSync } from "node:fs";
import { resolve } from "node:path";

const distIndex = resolve("dist", "index.html");
const distFallback = resolve("dist", "404.html");

copyFileSync(distIndex, distFallback);
console.log("Created dist/404.html SPA fallback.");
