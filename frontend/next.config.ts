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
};

export default nextConfig;
