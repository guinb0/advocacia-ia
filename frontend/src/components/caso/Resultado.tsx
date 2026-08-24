"use client";

import { useState } from "react";

import { ESTILO_VEREDITO, porcentagem } from "@/lib/formato";
import type { Documento } from "@/lib/types";
import { Aviso, BarraAbas, BotaoAba, Stat } from "@/components/ui/Basicos";
import { PainelJson, PainelXml } from "@/components/caso/PainelDados";
import PainelQualidade from "@/components/caso/PainelQualidade";
import PainelTexto from "@/components/caso/PainelTexto";
import PainelValidacao from "@/components/caso/PainelValidacao";
import TabelaCampos from "@/components/ui/TabelaCampos";

type Aba = "campos" | "validacao" | "qualidade" | "texto" | "json" | "xml";

export default function Resultado({ doc }: { doc: Documento }) {
  const [aba, setAba] = useState<Aba>("campos");
  const v = doc.validacao;
  const estilo = ESTILO_VEREDITO[v.veredito];

  /* Os nomes das abas dizem o que a pessoa vai encontrar, não o nome interno da
     estrutura: "Conferência" em vez de "Validação", "Qualidade da imagem" em
     vez de "Qualidade". JSON e XML ficam por último, com o rótulo do que são
     — quem não sabe o que é JSON não precisa entrar ali. */
  const abas: { id: Aba; nome: string }[] = [
    { id: "campos", nome: `Dados lidos (${doc.campos.length})` },
    { id: "validacao", nome: "Conferência" },
    { id: "qualidade", nome: "Qualidade da imagem" },
    { id: "texto", nome: `Texto bruto (${doc.texto_linhas.length})` },
    { id: "json", nome: "Exportar JSON" },
    { id: "xml", nome: "Exportar XML" },
  ];

  const confiancaOcr = doc.ocr.confianca_media;

  return (
    <>
      {/* Veredito da leitura: é a primeira coisa que a tela precisa dizer, e
          diz com símbolo + frase, não com um texto vermelho solto. */}
      <Aviso tom={estilo.tom} titulo={estilo.rotulo}>
        {v.resumo}
      </Aviso>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-[10px] mb-5">
        <Stat
          chave="Tipo detectado"
          valor={doc.tipo.descricao.split(" (")[0]}
          titulo={doc.tipo.descricao}
        />
        <Stat
          chave="Nitidez da imagem"
          valor={`${v.score_legibilidade}%`}
          score={v.score_legibilidade}
          titulo="Quanto a foto está legível para a leitura automática"
        />
        <Stat
          chave="Dados encontrados"
          valor={`${v.completude_percentual}%`}
          score={v.completude_percentual}
          titulo="Quanto dos campos esperados para este tipo de documento foi encontrado"
        />
        <Stat
          chave="Certeza da leitura"
          valor={porcentagem(confiancaOcr)}
          score={confiancaOcr === null ? null : confiancaOcr * 100}
          titulo="Confiança média que o OCR atribuiu ao que leu"
        />
        <Stat chave="Campos extraídos" valor={String(doc.campos.length)} />
        <Stat chave="Tempo de leitura" valor={`${doc.tempo_processamento_s}s`} />
      </div>

      <BarraAbas className="mb-[18px]" aria-label="Ver os dados desta forma">
        {abas.map((item) => (
          <BotaoAba key={item.id} ativa={aba === item.id} onClick={() => setAba(item.id)}>
            {item.nome}
          </BotaoAba>
        ))}
      </BarraAbas>

      {aba === "campos" && <TabelaCampos campos={doc.campos} />}
      {aba === "validacao" && <PainelValidacao doc={doc} />}
      {aba === "qualidade" && <PainelQualidade qualidade={doc.qualidade_imagem} />}
      {aba === "texto" && <PainelTexto linhas={doc.texto_linhas} />}
      {aba === "json" && <PainelJson doc={doc} />}
      {aba === "xml" && <PainelXml doc={doc} />}
    </>
  );
}
