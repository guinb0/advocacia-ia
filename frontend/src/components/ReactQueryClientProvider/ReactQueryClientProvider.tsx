"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

/**
 * O cliente do React Query, criado DENTRO do componente.
 *
 * Um `new QueryClient()` no escopo do módulo pareceria mais simples e seria um
 * bug: no servidor o módulo é compartilhado entre requisições, e o cache de um
 * usuário apareceria para o próximo. Dentro do `useState` cada árvore tem o seu,
 * e ele sobrevive às re-renderizações porque o `useState` só chama a fábrica na
 * primeira.
 */
export default function ReactQueryClientProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            /* Um minuto de "fresco". O padrão do React Query é zero, que faz
             * cada componente montado disparar rede de novo — num painel com
             * seis leituras isso é seis chamadas a cada troca de aba. */
            staleTime: 60_000,
            // Refazer a consulta a cada foco de janela atrapalha aqui: o
            // advogado alterna entre a tela e o PDF do processo o tempo todo.
            refetchOnWindowFocus: false,
            /* Uma tentativa extra, e só. 401 e 403 não melhoram com repetição —
             * quem os trata é o `api.ts`, que já manda para o login. */
            retry: 1,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
