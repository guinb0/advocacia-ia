"use client";

/* O agente encaixado ao lado do caso.
 *
 * Antes, falar com o agente era uma aba que substituía o dossiê inteiro. A resposta citava
 * "Entrevista · falta fazer" e o advogado não estava mais vendo a entrevista — a citação
 * apontava para o vazio. Ao lado, ela vira caminho de ida e volta, e é esse o motivo de o
 * componente ser uma coluna e não uma tela.
 *
 * O que ele deliberadamente NÃO faz: alterar o caso. Toda alteração chega como proposta, com
 * o antes e o depois, e espera confirmação — o backend recusa qualquer outro caminho
 * (`AGENTS.md §2.4`), e a tela não pode sugerir que algo já foi feito. */

import { useCallback, useEffect, useRef, useState } from "react";

import { Aviso } from "@/components/ui/Basicos";
import estilos from "@/components/AjudanteDoCaso.module.css";
import { CartaoDeProposta, LastroDaResposta } from "@/components/RespostaDoAgente";
import {
  buscarDossie,
  confirmarProposta,
  perguntarAoCaso,
  type MensagemDoChat,
  type PropostaDoAgente,
} from "@/lib/agente";

const SUGESTOES = ["Resumir o caso", "O que falta?", "Quais documentos cobrar?"];

interface Props {
  casoId: string;
  /** Leva a citação ao cartão correspondente no dossiê ao lado. Sem isto o lastro vira
   * decoração: identificadores que o advogado não tem como seguir. */
  aoAbrirReferencia?: (referencia: string) => void;
  aoRecolher: () => void;
}

export default function AjudanteDoCaso({ casoId, aoAbrirReferencia, aoRecolher }: Props) {
  const [mensagens, setMensagens] = useState<MensagemDoChat[]>([]);
  const [propostas, setPropostas] = useState<PropostaDoAgente[]>([]);
  const [conversaId, setConversaId] = useState<string | undefined>();
  const [texto, setTexto] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  // `undefined` enquanto não se sabe: abrir avisando que o caso não foi enviado, sem ter
  // conferido, seria dar uma má notícia por suposição.
  const [enviadoAoAgente, setEnviadoAoAgente] = useState<boolean | undefined>();
  const fim = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let ativo = true;
    void buscarDossie(casoId)
      .then((dossie) => {
        if (ativo) setEnviadoAoAgente(dossie.agente.vinculado);
      })
      // Falha aqui não vira erro na tela: é um aviso de contexto, não a conversa. O painel
      // continua servindo, e o advogado descobre pelo próprio agente se o caso está lá.
      .catch(() => undefined);
    return () => {
      ativo = false;
    };
  }, [casoId]);

  const perguntar = useCallback(
    async (pergunta: string) => {
      const limpa = pergunta.trim();
      if (!limpa || carregando) return;

      setErro("");
      setTexto("");
      setCarregando(true);
      // A pergunta aparece antes da resposta chegar: esperar a ida e a volta para mostrar o
      // que o próprio usuário escreveu faz a tela parecer travada.
      setMensagens((atuais) => [
        ...atuais,
        {
          id: `local-${Date.now()}`,
          papel: "USER",
          conteudo: limpa,
          citacoes: [],
          afirmacoes: [],
          pendencias: [],
          criadaEm: new Date().toISOString(),
        },
      ]);

      try {
        const resposta = await perguntarAoCaso(casoId, limpa, conversaId);
        setConversaId(resposta.conversaId);
        setMensagens((atuais) => [...atuais, resposta.mensagem]);
        setPropostas(resposta.propostas.filter((item) => item.estado === "PENDING"));
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : "Não foi possível perguntar.");
      } finally {
        setCarregando(false);
        fim.current?.scrollIntoView({ behavior: "smooth" });
      }
    },
    [carregando, casoId, conversaId],
  );

  async function aplicar(proposta: PropostaDoAgente) {
    setErro("");
    try {
      const aplicada = await confirmarProposta(casoId, proposta.id);
      setPropostas((atuais) => atuais.filter((item) => item.id !== aplicada.id));
    } catch (falha) {
      // A recusa mais comum é a proposta obsoleta — a peça mudou desde que ela foi feita. O
      // texto do agente já diz isso e o que fazer, então ele chega como está.
      setErro(falha instanceof Error ? falha.message : "Não foi possível aplicar.");
    }
  }

  return (
    <aside className={estilos.painel} aria-label="Agente do caso">
      <div className={estilos.cabecalho}>
        <div className={estilos.titulo}>
          <IconeConversa />
          <span>Agente do caso</span>
        </div>
        <div className={estilos.acoesDoCabecalho}>
          <button
            type="button"
            className={estilos.iconeBotao}
            onClick={aoRecolher}
            aria-label="Recolher o agente"
            title="Recolher"
          >
            <IconeSeta />
          </button>
        </div>
      </div>

      <div className={estilos.conversa}>
        {enviadoAoAgente === false && (
          <Aviso tom="atencao" titulo="Este caso ainda não foi enviado ao agente">
            Posso responder sobre o cadastro e o checklist. Fatos, classificação e peças só
            depois do envio.
          </Aviso>
        )}

        {mensagens.length === 0 && enviadoAoAgente !== false && (
          <p className={estilos.vazio}>
            Pergunte sobre este caso. Respondo com o que ele registra e mostro em que me apoiei.
          </p>
        )}

        {mensagens.map((mensagem) =>
          mensagem.papel === "USER" ? (
            <div key={mensagem.id} className={estilos.pergunta}>
              {mensagem.conteudo}
            </div>
          ) : (
            <Resposta
              key={mensagem.id}
              mensagem={mensagem}
              aoAbrirReferencia={aoAbrirReferencia}
            />
          ),
        )}

        {propostas.map((proposta) => (
          <CartaoDeProposta
            key={proposta.id}
            proposta={proposta}
            aoAplicar={() => aplicar(proposta)}
          />
        ))}

        {carregando && <p className={estilos.vazio}>Lendo o caso…</p>}
        {erro && <Aviso tom="critico">{erro}</Aviso>}
        <div ref={fim} />
      </div>

      <div className={estilos.composicao}>
        <div className={estilos.sugestoes}>
          {SUGESTOES.map((sugestao) => (
            <button
              key={sugestao}
              type="button"
              className={estilos.sugestao}
              onClick={() => void perguntar(sugestao)}
              disabled={carregando}
            >
              {sugestao}
            </button>
          ))}
        </div>

        <div className={estilos.linhaDeEnvio}>
          {/* Sem rótulo visível: o painel inteiro já se anuncia como "Agente do caso", e uma
            * segunda linha de texto acima do campo só empurraria a conversa para cima. O
            * `aria-label` mantém o campo nomeado para quem usa leitor de tela. */}
          <textarea
            className={`campo campo--area ${estilos.campoDaPergunta}`}
            aria-label="Pergunta ao agente sobre este caso"
            placeholder="Pergunte sobre este caso…"
            value={texto}
            rows={2}
            onChange={(evento) => setTexto(evento.target.value)}
            onKeyDown={(evento) => {
              // Enter envia, Shift+Enter quebra linha — o hábito de qualquer chat. Sem isto o
              // advogado manda a pergunta pela metade ao tentar formatá-la.
              if (evento.key === "Enter" && !evento.shiftKey) {
                evento.preventDefault();
                void perguntar(texto);
              }
            }}
          />
          <button
            type="button"
            className={`botao botao--primario ${estilos.enviar}`}
            onClick={() => void perguntar(texto)}
            disabled={carregando || !texto.trim()}
            aria-label="Enviar pergunta"
          >
            →
          </button>
        </div>

        <p className={estilos.rodape}>
          Responde só com o que este caso registra. Nada é alterado sem a sua confirmação.
        </p>
      </div>
    </aside>
  );
}

function Resposta({
  mensagem,
  aoAbrirReferencia,
}: {
  mensagem: MensagemDoChat;
  aoAbrirReferencia?: (referencia: string) => void;
}) {
  return (
    <>
      <div className={estilos.resposta}>{mensagem.conteudo}</div>
      <LastroDaResposta
        afirmacoes={mensagem.afirmacoes}
        pendencias={mensagem.pendencias}
        aoAbrirReferencia={(referencia) => {
          aoAbrirReferencia?.(referencia);
          // O destaque sozinho não resolve: o item pode estar fora da vista, e o advogado
          // veria a resposta mudar sem nada acontecer do outro lado.
          document
            .getElementById(`fato-${referencia}`)
            ?.scrollIntoView({ behavior: "smooth", block: "center" });
        }}
      />
    </>
  );
}

function IconeConversa() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function IconeSeta() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}
