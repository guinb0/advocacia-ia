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

  /* A raiz é ESTA pasta, e precisa ser dita em voz alta.
   *
   * Sem esta linha o Turbopack sobe a árvore de diretórios procurando um `package.json` ou
   * lockfile que sirva de raiz de workspace, e acaba encontrando os de um projeto solto no
   * PERFIL do usuário (`C:\Users\<voce>\package.json`, do `bolao-copa-2026`). A partir daí
   * ele considera `C:\Users\<voce>` a raiz e passa a varrer o perfil inteiro — Documents,
   * Downloads, AppData, OneDrive. O `next dev` anuncia "Ready" e nunca responde: medido
   * aqui, o processo queimou 3.159 segundos de CPU e 966 MB sem servir uma requisição.
   *
   * Apagar o `package.json` do perfil também resolveria, mas depende de a máquina de cada
   * um estar limpa. Isto não depende. */
  turbopack: {
    root: __dirname,
  },
};

export default nextConfig;
