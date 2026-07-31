# Frontend — Extrator de Documentos

Next.js 16 (App Router) + React 19, sem Tailwind: CSS Modules e variáveis de tema em
`app/globals.css` (claro/escuro via `prefers-color-scheme`).

```powershell
npm run dev         # http://localhost:3100
npm run build
npm run start       # http://localhost:3100
npm run typecheck
```

O backend precisa estar no ar em `http://127.0.0.1:8100` — suba os dois de uma vez com
`..\iniciar.ps1`.

## Onde mexer

| Arquivo | O que faz |
|---|---|
| `app/page.tsx` | página única, junta o painel de envio e o de resultado |
| `lib/useExtracao.ts` | estado do upload, status do modelo, lista de tipos |
| `lib/api.ts` | cliente HTTP; base vem de `NEXT_PUBLIC_OCR_API` |
| `lib/types.ts` | espelho tipado do JSON de `/api/extrair` |
| `components/` | painéis do resultado |

**`lib/types.ts` precisa acompanhar `app/pipeline.py`** — é ele que monta o JSON. Se um
campo mudar de nome lá, mude aqui também.

## Por que não há rewrite de `/api`

O proxy do Next derruba a conexão em 30s (timeout fixo, sem opção de config) e bufferiza
o upload inteiro na memória, truncando o corpo em silêncio acima de
`proxyClientMaxBodySize`. Como o OCR leva de 3 a 30s e fotos têm vários MB, o navegador
fala direto com o FastAPI, que habilita CORS. Detalhes no README da raiz.
