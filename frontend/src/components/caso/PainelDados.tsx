"use client";

import { useEffect, useState } from "react";

import { baixarTexto, urlApi } from "@/lib/api";
import type { Documento } from "@/lib/types";
import { LinkBotao } from "@/components/ui/Basicos";

/** Aba JSON: o objeto já está em memória, basta formatar. */
export function PainelJson({ doc }: { doc: Documento }) {
  const temp = doc.arquivos_temporarios;

  return (
    <>
      <div className="flex gap-[10px] mb-[14px] flex-wrap items-center">
        <LinkBotao variante="secundario" pequeno href={urlApi(temp.json)} download>
          Baixar JSON
        </LinkBotao>
        <LinkBotao variante="discreto" pequeno href={urlApi(temp.json)} target="_blank" rel="noreferrer">
          Abrir em nova aba
        </LinkBotao>
        <span className="mt-1 text-tinta-3 text-xs leading-[1.5]">
          Arquivo temporário — expira em {temp.expira_em_segundos / 60} min
        </span>
      </div>
      <pre className="p-[14px] border border-borda rounded-campo bg-papel-2 text-tinta-2 font-codigo text-[0.8125rem] leading-[1.6] max-h-[520px] overflow-auto whitespace-pre">
        {JSON.stringify(doc, null, 2)}
      </pre>
    </>
  );
}

/** Aba XML: o backend é quem serializa, então buscamos o arquivo temporário. */
export function PainelXml({ doc }: { doc: Documento }) {
  const temp = doc.arquivos_temporarios;
  const [xml, setXml] = useState("carregando…");

  useEffect(() => {
    let cancelado = false;
    baixarTexto(temp.xml)
      .then((texto) => {
        if (!cancelado) setXml(texto);
      })
      .catch(() => {
        if (!cancelado) setXml("Não foi possível carregar o XML (pode ter expirado).");
      });
    return () => {
      cancelado = true;
    };
  }, [temp.xml]);

  return (
    <>
      <div className="flex gap-[10px] mb-[14px] flex-wrap items-center">
        <LinkBotao variante="secundario" pequeno href={urlApi(temp.xml)} download>
          Baixar XML
        </LinkBotao>
        <LinkBotao variante="discreto" pequeno href={urlApi(temp.xml)} target="_blank" rel="noreferrer">
          Abrir em nova aba
        </LinkBotao>
      </div>
      <pre className="p-[14px] border border-borda rounded-campo bg-papel-2 text-tinta-2 font-codigo text-[0.8125rem] leading-[1.6] max-h-[520px] overflow-auto whitespace-pre">
        {xml}
      </pre>
    </>
  );
}
