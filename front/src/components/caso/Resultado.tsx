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
  const estilo = v ? ESTILO_VEREDITO[v.veredito] ?? ESTILO_VEREDITO.APROVADO_COM_RESSALVAS : null;
  const campos = doc.campos ?? [];
  const textoLinhas = doc.texto_linhas ?? [];
  const tipoDescricao = doc.tipo?.descricao ?? "Tipo não identificado";
  const confiancaOcr = doc.ocr?.confianca_media ?? null;
  const temXml = Boolean(doc.arquivos_temporarios?.xml);
  const scoreLegibilidade = v?.score_legibilidade ?? null;
  const completude = v?.completude_percentual ?? null;

  /* Os nomes das abas dizem o que a pessoa vai encontrar, não o nome interno da
     estrutura: "Conferência" em vez de "Validação", "Qualidade da imagem" em
     vez de "Qualidade". JSON e XML ficam por último, com o rótulo do que são
     — quem não sabe o que é JSON não precisa entrar ali. */
  const abas: { id: Aba; nome: string }[] = [
    { id: "campos", nome: `Dados lidos (${campos.length})` },
    { id: "validacao", nome: "Conferência" },
    ...(doc.qualidade_imagem ? [{ id: "qualidade" as const, nome: "Qualidade da imagem" }] : []),
    { id: "texto", nome: `Texto bruto (${textoLinhas.length})` },
    { id: "json", nome: "Exportar JSON" },
    ...(temXml ? [{ id: "xml" as const, nome: "Exportar XML" }] : []),
  ];

  return (
    <>
      {/* Veredito da leitura: é a primeira coisa que a tela precisa dizer, e
          diz com símbolo + frase, não com um texto vermelho solto. */}
      {estilo ? (
        <Aviso tom={estilo.tom} titulo={estilo.rotulo}>
          {v?.resumo}
        </Aviso>
      ) : (
        <Aviso tom="atencao" titulo="Conferência indisponível">
          Esta leitura não trouxe o resumo de conferência.
        </Aviso>
      )}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-[10px] mb-5">
        <Stat
          chave="Tipo detectado"
          valor={tipoDescricao.split(" (")[0]}
          titulo={tipoDescricao}
        />
        <Stat
          chave="Nitidez da imagem"
          valor={scoreLegibilidade === null ? "—" : `${scoreLegibilidade}%`}
          score={scoreLegibilidade}
          titulo="Quanto a foto está legível para a leitura automática"
        />
        <Stat
          chave="Dados encontrados"
          valor={completude === null ? "—" : `${completude}%`}
          score={completude}
          titulo="Quanto dos campos esperados para este tipo de documento foi encontrado"
        />
        <Stat
          chave="Certeza da leitura"
          valor={porcentagem(confiancaOcr)}
          score={confiancaOcr === null ? null : confiancaOcr * 100}
          titulo="Confiança média que o OCR atribuiu ao que leu"
        />
        <Stat chave="Campos extraídos" valor={String(campos.length)} />
        <Stat
          chave="Tempo de leitura"
          valor={doc.tempo_processamento_s === undefined ? "—" : `${doc.tempo_processamento_s}s`}
        />
      </div>

      <BarraAbas className="mb-[18px]" aria-label="Ver os dados desta forma">
        {abas.map((item) => (
          <BotaoAba key={item.id} ativa={aba === item.id} onClick={() => setAba(item.id)}>
            {item.nome}
          </BotaoAba>
        ))}
      </BarraAbas>

      {aba === "campos" && <TabelaCampos campos={campos} />}
      {aba === "validacao" && <PainelValidacao doc={doc} />}
      {aba === "qualidade" && doc.qualidade_imagem && (
        <PainelQualidade qualidade={doc.qualidade_imagem} />
      )}
      {aba === "texto" && <PainelTexto linhas={textoLinhas} />}
      {aba === "json" && <PainelJson doc={doc} />}
      {aba === "xml" && <PainelXml doc={doc} />}
    </>
  );
}
