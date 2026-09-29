import { cpSync, existsSync, mkdirSync } from "node:fs";

const origem = new URL("../node_modules/@mediapipe/tasks-vision/wasm/", import.meta.url);
const destino = new URL("../public/mediapipe/wasm/", import.meta.url);

if (existsSync(origem)) {
  mkdirSync(destino, { recursive: true });
  for (const nome of [
    "vision_wasm_internal.js",
    "vision_wasm_internal.wasm",
    "vision_wasm_nosimd_internal.js",
    "vision_wasm_nosimd_internal.wasm",
  ]) {
    cpSync(new URL(nome, origem), new URL(nome, destino));
  }
}
