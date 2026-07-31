import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Extrator de Documentos — PaddleOCR",
  description:
    "Leitura de documentos brasileiros com validação de dígitos verificadores e análise de legibilidade da foto.",
};

// Fontes do sistema de propósito: a app roda offline na máquina do usuário, e
// next/font/google precisaria baixar os arquivos durante o build.
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
