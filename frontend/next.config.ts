import type { NextConfig } from "next";

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
const nextConfig: NextConfig = {};

export default nextConfig;
