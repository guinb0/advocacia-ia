# Frontend — Acervo

Next.js 16 (App Router) + React 19, na estrutura MVVM usada nos demais projetos da
Level (SIDAF/DFLegal).

```powershell
npm run dev         # http://localhost:3000
npm run build
npm run start
npm run typecheck
```

O backend precisa estar no ar em `http://localhost:8100` — suba os dois de uma vez com
`..\iniciar.ps1`.

## Estrutura

```
src/
  app/                    rotas (App Router)
    page.tsx              login: casa ViewModel e View
    page.model.ts         ViewModel do login (react-hook-form + zod + mutação)
    page.view.tsx         View do login
    page.interface.ts     o formato da sessão que a API devolve
    home/                 a aplicação, protegida pelo proxy.ts
      page.tsx  home.model.ts  home.view.tsx
    portal/[token]/       o cliente, com senha do caso (fora do login)
    chamada/[sala]/       sala de vídeo, aberta por link
  components/             as telas em CSS Modules (Carteira, Dossiê, Checklist…)
  contexts/ContextWrapper.tsx   quem está logado + React Query
  global/services/        api.ts (fetch com cookie) e auth.service.ts
  global/hooks/           mutações e queries compartilhadas
  lib/                    clientes de API e hooks por assunto
  proxy.ts                a guarda de rota (era `middleware.ts`)
```

**O MVVM vale para o código novo.** As ~60 telas em `components/` continuam como
estavam, em CSS Modules, e migram uma a uma quando forem mexidas por outro motivo
— converter as 23 mil linhas de uma vez seria reescrever o produto inteiro para
não mudar nada que o usuário veja.

## Login

A sessão é um JWT que o backend assina e grava num cookie `HttpOnly` chamado
`JwtToken` (ver `app/auth.py` e `app/usuarios.py`). Três consequências que valem
saber antes de mexer:

1. **O JavaScript não lê o token** — é o que o protege de um XSS. Quem precisa
   saber o nome de quem entrou lê o `ContextWrapper`, não o token;
2. **toda chamada precisa de `credentials: "include"`**, senão o navegador não
   manda o cookie e a rota responde 401;
3. **frontend e API precisam ser o mesmo site.** `localhost:3000` e
   `localhost:8100` são; `localhost:3000` e `127.0.0.1:8100` **não** — para o
   navegador são hosts diferentes, e o cookie não atravessa. O sintoma é entrar
   no login e voltar para o login, sem erro que mencione cookie.

Quem barra quem não tem sessão é o `src/proxy.ts`, no servidor. No Next 16 esse
arquivo **não** se chama mais `middleware.ts`; um arquivo com o nome antigo é
ignorado em silêncio.

## Onde mexer

| Arquivo | O que faz |
|---|---|
| `src/app/home/home.view.tsx` | a aplicação: qual tela desenhar |
| `src/app/home/home.model.ts` | o estado dela (tela aberta, caso em foco) |
| `src/lib/api.ts` | cliente HTTP das telas antigas; base em `NEXT_PUBLIC_OCR_API` |
| `src/global/services/api.ts` | cliente HTTP do padrão novo (`apiFetch`) |
| `src/lib/types.ts` | espelho tipado do JSON de `/api/extrair` |
| `src/components/` | as telas |

**`src/lib/types.ts` precisa acompanhar `app/pipeline.py`** — é ele que monta o JSON.
Se um campo mudar de nome lá, mude aqui também.

## Tailwind convive com os CSS Modules

O Tailwind está ligado **sem o preflight** e com as cores apontando para as
variáveis de `src/app/globals.css`. Os dois motivos estão escritos em
`tailwind.config.ts`; o resumo é que o reset do Tailwind desmancharia as 44
folhas existentes, e a paleta padrão dele desfaria o contraste já medido do
sistema visual.

## Por que não há rewrite de `/api`

O proxy do Next derruba a conexão em 30s (timeout fixo, sem opção de config) e bufferiza
o upload inteiro na memória, truncando o corpo em silêncio acima de
`proxyClientMaxBodySize`. Como o OCR leva de 3 a 30s e fotos têm vários MB, o navegador
fala direto com o FastAPI, que habilita CORS. Detalhes no README da raiz.
