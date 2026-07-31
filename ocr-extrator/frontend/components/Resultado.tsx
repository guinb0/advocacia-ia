"use client";

import { useState } from "react";

import { ESTILO_VEREDITO, porcentagem, semUnderscore } from "@/lib/formato";
import type { Documento } from "@/lib/types";
import { Stat } from "./Basicos";
import { PainelJson, PainelXml } from "./PainelDados";
import PainelQualidade from "./PainelQualidade";
import PainelTexto from "./PainelTexto";
import PainelValidacao from "./PainelValidacao";
import TabelaCampos from "./TabelaCampos";
import ui from "./ui.module.css";

type Aba = "campos" | "validacao" | "qualidade" | "texto" | "json" | "xml";

export default function Resultado({ doc }: { doc: Documento }) {
  const [aba, setAba] = useState<Aba>("campos");
  const v = doc.validacao;
  const estilo = ESTILO_VEREDITO[v.veredito];

  const abas: { id: Aba; nome: string }[] = [
    { id: "campos", nome: `Campos (${doc.campos.length})` },
    { id: "validacao", nome: "Validação" },
    { id: "qualidade", nome: "Qualidade" },
    { id: "texto", nome: `Texto bruto (${doc.texto_linhas.length})` },
    { id: "json", nome: "JSON" },
    { id: "xml", nome: "XML" },
  ];

  const confiancaOcr = doc.ocr.confianca_media;

  return (
    <>
      <div className={`${ui.banner} ${ui[estilo.classe]}`}>
        <div className={ui.bannerIcone}>{estilo.icone}</div>
        <div>
          <strong>{semUnderscore(v.veredito)}</strong>
          <span>{v.resumo}</span>
        </div>
      </div>

      <div className={ui.stats}>
        <Stat
          chave="Tipo detectado"
          valor={doc.tipo.descricao.split(" (")[0]}
          titulo={doc.tipo.descricao}
        />
        <Stat
          chave="Legibilidade"
          valor={`${v.score_legibilidade}%`}
          score={v.score_legibilidade}
        />
        <Stat
          chave="Completude"
          valor={`${v.completude_percentual}%`}
          score={v.completude_percentual}
        />
        <Stat
          chave="Confiança OCR"
          valor={porcentagem(confiancaOcr)}
          score={confiancaOcr === null ? null : confiancaOcr * 100}
        />
        <Stat chave="Campos" valor={String(doc.campos.length)} />
        <Stat chave="Tempo" valor={`${doc.tempo_processamento_s}s`} />
      </div>

      <div className={ui.abas} role="tablist">
        {abas.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={aba === item.id}
            className={`${ui.aba} ${aba === item.id ? ui.abaAtiva : ""}`}
            onClick={() => setAba(item.id)}
          >
            {item.nome}
          </button>
        ))}
      </div>

      {aba === "campos" && <TabelaCampos campos={doc.campos} />}
      {aba === "validacao" && <PainelValidacao doc={doc} />}
      {aba === "qualidade" && <PainelQualidade qualidade={doc.qualidade_imagem} />}
      {aba === "texto" && <PainelTexto linhas={doc.texto_linhas} />}
      {aba === "json" && <PainelJson doc={doc} />}
      {aba === "xml" && <PainelXml doc={doc} />}
    </>
  );
}
