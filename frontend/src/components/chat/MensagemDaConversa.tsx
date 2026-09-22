"use client";

/* Uma mensagem do chat — e, quando é resposta, tudo que a sustenta.
 *
 * A REGRA QUE ORGANIZA ESTE ARQUIVO: a origem vem antes do texto.
 *
 * Uma página da internet, um documento conferido do caso e a leitura do acervo não valem
 * a mesma coisa, e numa bolha idêntica elas chegariam com o mesmo peso. Por isso toda
 * resposta abre com um selo dizendo de onde veio, e cada origem traz o seu próprio
 * rodapé: fontes na web, lastro no analista, pendências onde houver.
 *
 * Os atalhos ficam no fim, e o par "Abrir"/"Ver aqui" anda junto: o primeiro navega, o
 * segundo traz o material para dentro da conversa. Quem está no meio de uma pergunta
 * perde o fio ao navegar; quem vai trabalhar no caso não quer o resumo aqui. Os dois
 * custam um botão. */

import { useState } from "react";

import { Selo } from "@/components/ui/Basicos";
import { RespostaFormatada } from "@/components/ui/Markdown";
import estilos from "@/components/chat/Chat.module.css";
import PainelDeDocumentos from "@/components/chat/PainelDeDocumentos";
import {
  documentosDoCaso,
  type AtalhoDaResposta,
  type MensagemDoChat,
  type NaturezaDoChat,
  type PainelDeDocumentos as Painel,
} from "@/lib/chat";
import type { TomSelo } from "@/lib/formato";

/** Como cada origem se apresenta. O rótulo é a promessa que a resposta faz. */
const ORIGEM: Record<NaturezaDoChat, { rotulo: string; tom: TomSelo } | null> = {
  PERGUNTA: null,
  WEB: { rotulo: "Da internet", tom: "atencao" },
  /* Duas origens numa resposta só. O selo diz isso no alto, e os títulos dentro do texto
   * dizem onde uma acaba e a outra começa — sem isso, a página de internet e o dado
   * apurado do escritório chegariam com o mesmo peso. */
  MISTA: { rotulo: "Do acervo e da internet", tom: "info" },
  DOCUMENTOS: { rotulo: "Do checklist do caso", tom: "ok" },
  CASO: { rotulo: "Do agente jurídico", tom: "info" },
  ANALISE: { rotulo: "Leitura do acervo", tom: "info" },
  SISTEMA: { rotulo: "Sobre o sistema", tom: "neutro" },
  ACERVO: { rotulo: "Sem resposta ainda", tom: "atencao" },
  ESCOLHA: { rotulo: "Precisa de um caso", tom: "atencao" },
  INDISPONIVEL: { rotulo: "Não foi possível responder", tom: "critico" },
};

interface Props {
  mensagem: MensagemDoChat;
  onAbrirCaso: (casoId: string) => void;
  onNavegar: (tela: string, casoId?: string | null) => void;
  /** Clicar num candidato responde a pergunta que a lista fez. */
  onEscolherCaso: (casoId: string) => void;
}

export default function MensagemDaConversa({
  mensagem,
  onAbrirCaso,
  onNavegar,
  onEscolherCaso,
}: Props) {
  /* O painel embutido por clique. Começa com o que veio junto da resposta (destino
   * DOCUMENTOS já traz), e o botão "Ver aqui" de outra mensagem busca o seu. */
  const [painel, setPainel] = useState<Painel | null>(mensagem.documentos);
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState("");

  if (mensagem.papel === "USER") {
    return <div className={estilos.pergunta}>{mensagem.conteudo}</div>;
  }

  const origem = ORIGEM[mensagem.natureza];

  async function verAqui(casoId: string) {
    setErro("");
    setBuscando(true);
    try {
      setPainel(await documentosDoCaso(casoId));
    } catch (falha) {
      // Falha aqui não apaga a resposta: o atalho "Abrir" continua ao lado, e é o
      // caminho que sempre funciona.
      setErro(falha instanceof Error ? falha.message : "Não consegui trazer os documentos.");
    } finally {
      setBuscando(false);
    }
  }

  return (
    <div className={estilos.resposta}>
      {origem && (
        <div className={estilos.origemDaResposta}>
          <Selo tom={origem.tom}>{origem.rotulo}</Selo>
          {mensagem.cliente && <Selo tom="neutro">{mensagem.cliente}</Selo>}
          {/* A pesquisa mede a confiança pelo DOMÍNIO, não pelo que o modelo diz. Quando
              nenhuma fonte é oficial, quem lê precisa saber antes de citar na peça. */}
          {mensagem.natureza === "WEB" && mensagem.temFonteOficial === false && (
            <Selo tom="critico" simbolo="!">
              nenhuma fonte oficial
            </Selo>
          )}
        </div>
      )}

      <div className={estilos.corpoDaResposta}>
        <RespostaFormatada texto={mensagem.conteudo} />
      </div>

      {painel && <PainelDeDocumentos painel={painel} onAbrirCaso={onAbrirCaso} />}
      {erro && <p className={estilos.exemploDaSugestao}>{erro}</p>}

      {mensagem.candidatos.length > 0 && (
        <div className={estilos.atalhos}>
          {mensagem.candidatos.map((candidato) => (
            <button
              key={candidato.casoId}
              type="button"
              className={estilos.atalho}
              onClick={() => onEscolherCaso(candidato.casoId)}
            >
              {candidato.cliente}
              {candidato.categoria ? ` · ${candidato.categoria}` : ""}
              {candidato.desempate ? ` · ${candidato.desempate}` : ""}
            </button>
          ))}
        </div>
      )}

      {mensagem.fontes.length > 0 && (
        <div className={estilos.blocoDeApoio}>
          <span className={estilos.tituloDoBloco}>Fontes consultadas</span>
          <ul className={estilos.listaSimples}>
            {mensagem.fontes.map((fonte) => (
              <li key={fonte.url}>
                <a href={fonte.url} target="_blank" rel="noreferrer" className={estilos.abrirArquivo}>
                  {fonte.titulo || fonte.url}
                </a>
                {fonte.confianca && ` — ${fonte.confianca.toLowerCase()}`}
              </li>
            ))}
          </ul>
        </div>
      )}

      {mensagem.afirmacoes.length > 0 && (
        <div className={estilos.blocoDeApoio}>
          {/* Sem o lastro, reabrir a conversa amanhã mostraria a conclusão sem as
              afirmações que a sustentam — que é o que este sistema não pode produzir. */}
          <span className={estilos.tituloDoBloco}>O que sustenta esta resposta</span>
          <ul className={estilos.listaSimples}>
            {mensagem.afirmacoes.map((afirmacao, i) => (
              <li key={i}>
                {afirmacao.statement}
                {afirmacao.nature && (
                  <span className={estilos.exemploDaSugestao}> ({afirmacao.nature})</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {mensagem.consultas.length > 0 && (
        <details className={estilos.blocoDeApoio}>
          <summary className={estilos.tituloDoBloco}>
            Como cheguei nisso ({mensagem.consultas.length} consulta(s))
          </summary>
          <ul className={estilos.listaSimples}>
            {mensagem.consultas.map((consulta, i) => (
              <li key={i}>{consulta.ferramenta}</li>
            ))}
          </ul>
        </details>
      )}

      {(mensagem.pendencias.length > 0 || mensagem.falta.length > 0) && (
        <div className={estilos.blocoDeApoio}>
          <span className={estilos.tituloDoBloco}>
            {mensagem.falta.length > 0 ? "O que falta para responder" : "Pendências"}
          </span>
          <ul className={estilos.listaSimples}>
            {[...mensagem.falta, ...mensagem.pendencias].map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {mensagem.atalhos.length > 0 && (
        <div className={estilos.atalhos}>
          {mensagem.atalhos.map((atalho, i) => (
            <Atalho
              key={`${atalho.tipo}-${atalho.casoId ?? atalho.url ?? i}`}
              atalho={atalho}
              buscando={buscando}
              jaEmbutido={Boolean(painel)}
              onNavegar={onNavegar}
              onVerAqui={verAqui}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Atalho({
  atalho,
  buscando,
  jaEmbutido,
  onNavegar,
  onVerAqui,
}: {
  atalho: AtalhoDaResposta;
  buscando: boolean;
  jaEmbutido: boolean;
  onNavegar: (tela: string, casoId?: string | null) => void;
  onVerAqui: (casoId: string) => void;
}) {
  if (atalho.tipo === "FONTE" && atalho.url) {
    return (
      <a className={estilos.atalho} href={atalho.url} target="_blank" rel="noreferrer">
        {atalho.rotulo}
      </a>
    );
  }

  const abrir = (
    <button
      type="button"
      className={estilos.atalho}
      onClick={() => onNavegar(atalho.tela ?? "carteira", atalho.casoId)}
    >
      {atalho.rotulo}
    </button>
  );

  // "Ver aqui" só aparece onde o material cabe na conversa — e some depois de trazido,
  // porque clicar de novo no mesmo botão não faria nada visível.
  if (!atalho.embutido || !atalho.casoId || jaEmbutido) return abrir;

  return (
    <span className={estilos.parDeAtalhos}>
      {abrir}
      <button
        type="button"
        className={estilos.atalho}
        disabled={buscando}
        onClick={() => onVerAqui(atalho.casoId as string)}
      >
        {buscando ? "trazendo…" : "ver aqui"}
      </button>
    </span>
  );
}
