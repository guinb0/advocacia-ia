"use client";

import { useEffect, useState } from "react";

import { baixarTexto, urlApi } from "@/lib/api";
import type { Documento } from "@/lib/types";
import { Aviso, LinkBotao } from "@/components/ui/Basicos";

/** Aba JSON: o objeto já está em memória, basta formatar. */
export function PainelJson({ doc }: { doc: Documento }) {
  const temp = doc.arquivos_temporarios;

  return (
    <>
      {temp?.json ? (
        <div className="flex gap-[10px] mb-[14px] flex-wrap items-center">
          <LinkBotao variante="secundario" pequeno href={urlApi(temp.json)} download>
            Baixar JSON
          </LinkBotao>
          <LinkBotao variante="discreto" pequeno href={urlApi(temp.json)} target="_blank" rel="noreferrer">
            Abrir em nova aba
          </LinkBotao>
          {temp.expira_em_segundos !== undefined && (
            <span className="mt-1 text-tinta-3 text-xs leading-[1.5]">
              Arquivo temporário — expira em {temp.expira_em_segundos / 60} min
            </span>
          )}
        </div>
      ) : (
        <Aviso tom="atencao" titulo="Arquivo temporário indisponível">
          Esta leitura não trouxe link de download do JSON, mas os dados salvos aparecem abaixo.
        </Aviso>
      )}
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
    if (!temp?.xml) {
      setXml("XML temporário indisponível para esta leitura.");
      return;
    }
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
  }, [temp?.xml]);

  return (
    <>
      {temp?.xml && (
        <div className="flex gap-[10px] mb-[14px] flex-wrap items-center">
          <LinkBotao variante="secundario" pequeno href={urlApi(temp.xml)} download>
            Baixar XML
          </LinkBotao>
          <LinkBotao variante="discreto" pequeno href={urlApi(temp.xml)} target="_blank" rel="noreferrer">
            Abrir em nova aba
          </LinkBotao>
        </div>
      )}
      <pre className="p-[14px] border border-borda rounded-campo bg-papel-2 text-tinta-2 font-codigo text-[0.8125rem] leading-[1.6] max-h-[520px] overflow-auto whitespace-pre">
        {xml}
      </pre>
    </>
  );
}
