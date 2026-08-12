"use client";

import { useEffect, useState } from "react";

import { baixarTexto, urlApi } from "@/lib/api";
import type { Documento } from "@/lib/types";
import ui from "./ui.module.css";

/** Aba JSON: o objeto já está em memória, basta formatar. */
export function PainelJson({ doc }: { doc: Documento }) {
  const temp = doc.arquivos_temporarios;

  return (
    <>
      <div className={ui.downloads}>
        <a className="botao botao--secundario botao--pequeno" href={urlApi(temp.json)} download>
          Baixar JSON
        </a>
        <a
          className="botao botao--discreto botao--pequeno"
          href={urlApi(temp.json)}
          target="_blank"
          rel="noreferrer"
        >
          Abrir em nova aba
        </a>
        <span className={ui.observacao}>
          Arquivo temporário — expira em {temp.expira_em_segundos / 60} min
        </span>
      </div>
      <pre className={ui.pre}>{JSON.stringify(doc, null, 2)}</pre>
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
      <div className={ui.downloads}>
        <a className="botao botao--secundario botao--pequeno" href={urlApi(temp.xml)} download>
          Baixar XML
        </a>
        <a
          className="botao botao--discreto botao--pequeno"
          href={urlApi(temp.xml)}
          target="_blank"
          rel="noreferrer"
        >
          Abrir em nova aba
        </a>
      </div>
      <pre className={ui.pre}>{xml}</pre>
    </>
  );
}
