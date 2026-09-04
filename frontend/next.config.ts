import type { NextConfig } from "next";

function origem(valor: string | undefined): string {
  try {
    return valor ? new URL(valor).origin : "";
  } catch {
    return "";
  }
}

const origemJitsi = origem(process.env.NEXT_PUBLIC_JITSI_URL);
const origensConexao = [
  origem(process.env.NEXT_PUBLIC_OCR_API),
  origem(process.env.NEXT_PUBLIC_TRANSCRICAO_API),
  origemJitsi,
].filter(Boolean).join(" ");
const origensDesenvolvimento = process.env.NODE_ENV === "development"
  ? " http://localhost:8100 http://127.0.0.1:8100 http://localhost:8200 http://127.0.0.1:8200 http://localhost:8081"
  : "";

const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'self'",
  "form-action 'self'",
  `script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com${origemJitsi ? ` ${origemJitsi}` : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' https://challenges.cloudflare.com ws: wss:${origensConexao ? ` ${origensConexao}` : ""}${origensDesenvolvimento}`,
  `frame-src 'self' https://challenges.cloudflare.com${origemJitsi ? ` ${origemJitsi}` : ""}`,
  "media-src 'self' blob:",
  "worker-src 'self' blob:",
  ...(process.env.NODE_ENV === "production" ? ["upgrade-insecure-requests"] : []),
].join("; ");

const cabecalhosSeguranca = [
  { key: "Content-Security-Policy", value: csp },
  { key: "Strict-Transport-Security", value: "max-age=31536000" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "geolocation=(), payment=(), usb=(), browsing-topics=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

/**
 * Sem rewrite de /api aqui de propósito.
 *
 * O caminho óbvio seria proxiar /api para o FastAPI, mas o proxy do Next derruba a
 * conexão em 30s (timeout fixo, sem opção de configuração) e bufferiza o upload
 * inteiro na memória do Node — inclusive truncando o corpo em silêncio acima de
 * `proxyClientMaxBodySize`. Foto de celular tem vários MB e o OCR leva de 3 a 30s,
 * então os uploads morriam com "socket hang up". O navegador fala direto com o
 * Python (ver lib/api.ts e NEXT_PUBLIC_OCR_API); o backend já habilita CORS.
 */
/* `standalone` so no build de imagem, e nao sempre.
 *
 * O Dockerfile copia `.next/standalone` — um servidor Node que traz apenas os
 * modulos que as rotas de fato importam, o que dispensa `node_modules` inteiro
 * na imagem final. Sem esta linha a pasta nem existe, e o `COPY` do Dockerfile
 * falha no build: erro claro, mas so no CI.
 *
 * Condicional para nao mudar nada de quem desenvolve: `next dev` ignora
 * `output`, mas um `next build` local passaria a escrever uma pasta a mais sem
 * motivo. O Dockerfile liga a variavel; a maquina de ninguem precisa. */
const nextConfig: NextConfig = {
  output: process.env.BUILD_STANDALONE === "1" ? "standalone" : undefined,
  poweredByHeader: false,
  // Impede o Turbopack de subir ate outro package-lock existente no perfil do Windows.
  turbopack: { root: process.cwd() },
  async headers() {
    return [
      { source: "/(.*)", headers: cabecalhosSeguranca },
      { source: "/", headers: [{ key: "Cache-Control", value: "no-store, max-age=0" }] },
    ];
  },
};

export default nextConfig;
