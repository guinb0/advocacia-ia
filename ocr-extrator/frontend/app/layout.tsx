import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono, Newsreader } from "next/font/google";

import DockChamada from "@/components/DockChamada";
import PortaoLogin from "@/components/PortaoLogin";
import { ProvedorAuth } from "@/lib/auth";
import { ProvedorChamada } from "@/lib/ChamadaContexto";
import "./globals.css";

export const metadata: Metadata = {
  title: "Acervo — carteira de casos",
  description:
    "Casos trabalhistas e previdenciários: checklist de documentos por categoria, entregas validadas por OCR e pedido ao cliente.",
};

/* A direção AUTOS é tipográfica antes de ser cromática — trocar Newsreader por
 * uma serifa do sistema desmancha o desenho. `next/font` baixa os arquivos no
 * build e os auto-hospeda em /_next/static, então o app continua rodando sem
 * rede, que era a preocupação registrada aqui antes; o que passa a exigir rede
 * é o `next build`. Os fallbacks abaixo seguram o layout se isso faltar. */
const serif = Newsreader({
  subsets: ["latin"],
  weight: "variable",
  style: ["normal", "italic"],
  display: "swap",
  variable: "--fonte-serif",
  fallback: ["Georgia", "Times New Roman", "serif"],
});

const sans = Archivo({
  subsets: ["latin"],
  weight: "variable",
  display: "swap",
  variable: "--fonte-sans",
  fallback: ["system-ui", "Segoe UI", "sans-serif"],
});

// IBM Plex Mono não publica eixo variável — os pesos vão explícitos.
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
  variable: "--fonte-mono",
  fallback: ["ui-monospace", "Menlo", "Consolas", "monospace"],
});

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    /* suppressHydrationWarning: extensões de navegador escrevem atributos no
     * <html> antes do React hidratar — a LanguageTool, por exemplo, injeta
     * `data-lt-installed`. Como o servidor nunca vai emitir esses atributos, a
     * hidratação acusa divergência a cada carga por algo que não está no nosso
     * código nem tem como ser corrigido aqui.
     *
     * O silenciamento vale só para os atributos DESTE elemento, não desce para
     * os filhos: uma divergência real dentro da árvore continua sendo apontada.
     * Os atributos do <html> saem daqui mesmo (lang + as classes de fonte). */
    <html
      lang="pt-BR"
      className={`${serif.variable} ${sans.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <body>
        <ProvedorAuth>
          {/* A chamada vive aqui, na raiz, para sobreviver à troca de telas — e
              o painel flutuante fica ao lado do gate, para seguir o usuário por
              todas elas. Vale para o escritório e para o cliente. */}
          <ProvedorChamada>
            <PortaoLogin>{children}</PortaoLogin>
            <DockChamada />
          </ProvedorChamada>
        </ProvedorAuth>
      </body>
    </html>
  );
}
