"use client";

/* O chat da petição — a conversa ancorada ao lado da minuta, dentro do Dossiê.
 *
 * Substitui o que antes eram dois quadrados parados ("Confirmado por documentos" e
 * "Depende de prova ou confirmação") mais três botões: dava para disparar ações e não
 * dava para PERGUNTAR nada. Quem queria entender por que um ponto estava pendente não
 * tinha a quem perguntar; quem queria mudar uma linha da peça tinha de descrever a
 * mudança num campo, sem conversa antes.
 *
 * Três regras moldam o componente:
 *
 * 1. A PEÇA NÃO SAI DA TELA. É coluna à direita, não aba. A resposta cita "o item II dos
 *    pedidos" e ele está ali ao lado, visível.
 * 2. NADA É APLICADO SEM CLIQUE. Toda alteração chega como proposta, com o que vai
 *    acontecer escrito, e vira comparação (antes × depois) antes de virar versão.
 * 3. O QUE VEIO DA WEB TEM CARA DE WEB. Fonte e link, em bloco próprio, nunca com a
 *    mesma aparência do que veio dos autos do caso.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Aviso, Botao, Selo } from "@/components/ui/Basicos";
import { RespostaFormatada, dominioDe } from "@/components/ui/Markdown";
import estilos from "@/components/admin/ChatPeticao.module.css";
import {
  EVENTO_DO_CHAT,
  abrirChatDaPeticao,
  executarAcaoDoChat,
  perguntarNoChat,
  registrarEventoNoChat,
  type AcaoProposta,
  type AvisoParaOChat,
  type MensagemDoChat,
} from "@/lib/chatPeticao";

/* Escritas como um advogado escreveria, e cobrindo as três coisas que o chat faz de
 * diferente: explicar o lastro de um ponto, buscar fora do caso e mudar a peça. */
const SUGESTOES = [
  "Por que esse ponto está como pendente de confirmação?",
  "Mostra o confronto entrevista × documentos",
  "Procura jurisprudência recente sobre esse pedido",
  "Reescreve o pedido de dano moral em tom mais técnico",
];

interface Props {
  casoId: string;
  /** Recarrega a minuta e o histórico do lado esquerdo: é o que faz a comparação
   *  proposta pelo chat aparecer sobre o documento. */
  aoMudarAPeticao: () => void;
  /** Fecha a gaveta. Em tela larga o painel é coluna fixa e o botão não aparece. */
  aoFechar?: () => void;
}

export default function ChatPeticao({ casoId, aoMudarAPeticao, aoFechar }: Props) {
  const [mensagens, setMensagens] = useState<MensagemDoChat[]>([]);
  const [carregandoHistorico, setCarregandoHistorico] = useState(true);
  const [modeloDisponivel, setModeloDisponivel] = useState(true);
  const [texto, setTexto] = useState("");
  const [parcial, setParcial] = useState("");
  const [etapa, setEtapa] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");
  /* As propostas já decididas nesta sessão. Some o par de botões sem apagar a mensagem:
   * a transcrição precisa continuar mostrando o que foi proposto e aceito. */
  const [decididas, setDecididas] = useState<Record<string, "aceita" | "descartada">>({});
  const [executando, setExecutando] = useState<string | null>(null);
  const conversa = useRef<HTMLDivElement>(null);

  const rolarParaOFim = useCallback(() => {
    // `scrollTop` no contêiner, e não `scrollIntoView` no fim: com o painel em coluna
    // sticky, o `scrollIntoView` arrastava a PÁGINA inteira junto, e o documento ao lado
    // saía da vista a cada pedaço de resposta que chegava.
    const alvo = conversa.current;
    if (alvo) alvo.scrollTop = alvo.scrollHeight;
  }, []);

  useEffect(() => {
    let ativo = true;
    setCarregandoHistorico(true);
    void abrirChatDaPeticao(casoId)
      .then((chat) => {
        if (!ativo) return;
        setMensagens(chat.mensagens);
        setModeloDisponivel(chat.modeloDisponivel);
      })
      .catch((falha) => {
        if (ativo) setErro(falha instanceof Error ? falha.message : "Não foi possível abrir a conversa.");
      })
      .finally(() => ativo && setCarregandoHistorico(false));
    return () => {
      ativo = false;
    };
  }, [casoId]);

  useEffect(() => {
    rolarParaOFim();
  }, [mensagens, parcial, etapa, rolarParaOFim]);

  /* O que os BOTÕES do painel fizeram chega por evento de janela (ver
   * `lib/chatPeticao.avisarChatDaPeticao`). A IA conta na conversa o que mudou — é
   * depois de uma geração que o advogado mais precisa saber o que ficou sem prova. */
  useEffect(() => {
    async function aoAvisar(evento: Event) {
      const { detail } = evento as CustomEvent<AvisoParaOChat>;
      if (!detail || detail.casoId !== casoId) return;
      try {
        const mensagem = await registrarEventoNoChat(casoId, detail.tipo, detail.dados ?? {});
        if (mensagem) setMensagens((atuais) => [...atuais, mensagem]);
      } catch {
        /* O aviso é complementar: a ação já aconteceu e o painel já a mostrou. Falhar
         * aqui não pode transformar um sucesso em mensagem de erro. */
      }
    }
    window.addEventListener(EVENTO_DO_CHAT, aoAvisar);
    return () => window.removeEventListener(EVENTO_DO_CHAT, aoAvisar);
  }, [casoId]);

  const perguntar = useCallback(
    async (pergunta: string) => {
      const limpa = pergunta.trim();
      if (!limpa || enviando) return;
      setErro("");
      setTexto("");
      setParcial("");
      setEtapa("Lendo o caso");
      setEnviando(true);
      try {
        await perguntarNoChat(casoId, limpa, (evento) => {
          switch (evento.tipo) {
            case "pergunta":
              setMensagens((atuais) => [...atuais, evento.mensagem]);
              break;
            case "etapa":
              setEtapa(evento.texto);
              break;
            case "delta":
              setEtapa("");
              setParcial((atual) => atual + evento.texto);
              break;
            case "recomeco":
              setParcial("");
              break;
            case "fim":
              setParcial("");
              setEtapa("");
              setMensagens((atuais) => [...atuais, evento.mensagem]);
              break;
            case "erro":
              setParcial("");
              setEtapa("");
              if (evento.mensagem) setMensagens((atuais) => [...atuais, evento.mensagem!]);
              else setErro(evento.texto);
              break;
          }
        });
      } catch (falha) {
        setErro(
          falha instanceof Error
            ? falha.message
            : "A conversa não chegou ao servidor. Tente de novo.",
        );
      } finally {
        setEnviando(false);
        setEtapa("");
        setParcial("");
      }
    },
    [casoId, enviando],
  );

  async function decidir(chave: string, acao: AcaoProposta, aceitar: boolean) {
    if (!aceitar) {
      setDecididas((atuais) => ({ ...atuais, [chave]: "descartada" }));
      return;
    }
    setExecutando(chave);
    setErro("");
    try {
      const resultado = await executarAcaoDoChat(casoId, acao);
      setMensagens((atuais) => [...atuais, resultado.mensagem]);
      setDecididas((atuais) => ({ ...atuais, [chave]: "aceita" }));
      // Mesmo quando a ação falha, o lado esquerdo é recarregado: uma revisão pode ter
      // sido gravada e a falha vir do passo seguinte, e a tela não pode ficar mostrando
      // uma peça mais velha do que a que está no banco.
      aoMudarAPeticao();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "A ação não pôde ser executada.");
    } finally {
      setExecutando(null);
    }
  }

  return (
    <aside className={estilos.painel} aria-label="Conversa com a IA sobre esta petição">
      <header className={estilos.cabecalho}>
        <div className={estilos.titulo}>
          <IconeConversa />
          <span>Falar com a IA sobre esta peça</span>
        </div>
        {aoFechar && (
          <button
            type="button"
            className={`${estilos.iconeBotao} lg:hidden`}
            onClick={aoFechar}
            aria-label="Fechar a conversa"
            title="Fechar"
          >
            <IconeFechar />
          </button>
        )}
      </header>

      <div className={estilos.conversa} ref={conversa}>
        {carregandoHistorico && <p className={estilos.vazio}>Abrindo a conversa deste caso…</p>}

        {!carregandoHistorico && mensagens.length === 0 && (
          <p className={estilos.vazio}>
            Pergunte sobre este caso, peça uma busca na web ou descreva uma alteração na
            petição. Eu leio a minuta, a entrevista e os documentos antes de responder — e
            nada na peça muda sem a sua confirmação.
          </p>
        )}

        {!modeloDisponivel && (
          <Aviso tom="atencao" titulo="A conversa está desligada">
            Falta a chave do modelo no servidor (DEEPSEEK_API_KEY). Os botões de gerar,
            analisar e revisar continuam funcionando normalmente.
          </Aviso>
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
              decididas={decididas}
              executando={executando}
              aoDecidir={decidir}
              aoRepetir={() => void perguntar(mensagem.perguntaOriginal)}
            />
          ),
        )}

        {etapa && (
          <p className={estilos.andamento}>
            <span className={estilos.ponto} aria-hidden />
            {etapa}…
          </p>
        )}

        {parcial && (
          <div className={estilos.resposta}>
            <RespostaFormatada texto={parcial} />
          </div>
        )}

        {enviando && !etapa && !parcial && (
          <p className={estilos.andamento}>
            <span className={estilos.ponto} aria-hidden />
            Escrevendo…
          </p>
        )}

        {erro && <Aviso tom="critico">{erro}</Aviso>}
      </div>

      <div className={estilos.composicao}>
        {mensagens.length === 0 && (
          <div className={estilos.sugestoes}>
            {SUGESTOES.map((sugestao) => (
              <button
                key={sugestao}
                type="button"
                className={estilos.sugestao}
                onClick={() => void perguntar(sugestao)}
                disabled={enviando || !modeloDisponivel}
              >
                {sugestao}
              </button>
            ))}
          </div>
        )}

        <div className={estilos.linhaDeEnvio}>
          {/* Sem rótulo visível: o painel inteiro já se anuncia no cabeçalho, e uma
            * segunda linha de texto acima do campo empurraria a conversa para cima. */}
          <textarea
            className={`campo campo--area ${estilos.campoDaPergunta}`}
            aria-label="Pergunta ou pedido sobre esta petição"
            placeholder="Pergunte, peça uma busca na web ou descreva uma alteração…"
            value={texto}
            rows={2}
            disabled={!modeloDisponivel}
            onChange={(evento) => setTexto(evento.target.value)}
            onKeyDown={(evento) => {
              // Enter envia, Shift+Enter quebra linha — o hábito de qualquer chat.
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
            disabled={enviando || !texto.trim() || !modeloDisponivel}
            aria-label="Enviar"
          >
            {enviando ? "…" : "→"}
          </button>
        </div>

        <p className={estilos.rodape}>
          A conversa fica salva neste caso. Alteração na peça só depois da sua
          confirmação, e sempre com comparação antes × depois.
        </p>
      </div>
    </aside>
  );
}

function Resposta({
  mensagem,
  decididas,
  executando,
  aoDecidir,
  aoRepetir,
}: {
  mensagem: MensagemDoChat;
  decididas: Record<string, "aceita" | "descartada">;
  executando: string | null;
  aoDecidir: (chave: string, acao: AcaoProposta, aceitar: boolean) => void;
  aoRepetir: () => void;
}) {
  if (mensagem.natureza === "ERRO") {
    return (
      <Aviso tom="critico" titulo="Não deu certo">
        <span className="block whitespace-pre-wrap">{mensagem.conteudo}</span>
        {mensagem.podeRepetir && mensagem.perguntaOriginal && (
          <span className="mt-2 block">
            <Botao variante="secundario" pequeno onClick={aoRepetir}>
              Tentar de novo
            </Botao>
          </span>
        )}
      </Aviso>
    );
  }

  const proativa = mensagem.natureza === "EVENTO";
  return (
    <div className={`${estilos.resposta} ${proativa ? estilos.evento : ""}`}>
      {proativa && <span className={estilos.selo}>A IA avisou</span>}
      <RespostaFormatada texto={mensagem.conteudo} />

      {mensagem.fontes.length > 0 && (
        <div className={estilos.fontes}>
          <p className={estilos.tituloDasFontes}>
            Da web — confira antes de usar na peça ({mensagem.fontes.length})
          </p>
          <ol className={estilos.listaDeFontes}>
            {mensagem.fontes.map((fonte) => (
              <li key={fonte.url}>
                <a
                  href={fonte.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-acao underline break-words"
                >
                  {fonte.titulo || dominioDe(fonte.url)}
                </a>
                <span className={estilos.dominio}>{dominioDe(fonte.url)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {mensagem.acoes.map((acao, indice) => {
        const chave = `${mensagem.id}:${indice}`;
        return (
          <PropostaDeAcao
            key={chave}
            acao={acao}
            decisao={decididas[chave]}
            ocupado={executando === chave}
            aoDecidir={(aceitar) => aoDecidir(chave, acao, aceitar)}
          />
        );
      })}
    </div>
  );
}

const ROTULOS: Record<AcaoProposta["tipo"], string> = {
  REVISAR: "Alterar a petição",
  GERAR: "Gerar a petição de novo",
  ANALISAR_DOCUMENTOS: "Reler os documentos",
  PECA_ANEXA: "Redigir outra peça",
};

/**
 * A proposta, com o que ela faz escrito antes dos botões.
 *
 * O aviso reforçado de `sensivel` não substitui a confirmação — ela é exigida em
 * qualquer caso. Ele existe porque "troque «reclamante» por «autor»" e "aumente o valor
 * para R$ 60.000" chegariam com o mesmo peso visual, e o segundo merece uma leitura
 * mais lenta.
 */
function PropostaDeAcao({
  acao,
  decisao,
  ocupado,
  aoDecidir,
}: {
  acao: AcaoProposta;
  decisao?: "aceita" | "descartada";
  ocupado: boolean;
  aoDecidir: (aceitar: boolean) => void;
}) {
  return (
    <section className="mt-3 rounded-campo border border-acao-borda border-l-4 border-l-acao bg-papel p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <strong className="text-sm text-tinta">{ROTULOS[acao.tipo] ?? "Ação"}</strong>
        {decisao === "aceita" ? (
          <Selo tom="ok" simbolo="✓">Executada</Selo>
        ) : decisao === "descartada" ? (
          <Selo tom="neutro" simbolo="✕">Descartada</Selo>
        ) : acao.sensivel ? (
          <Selo tom="atencao" simbolo="!">Mexe em valor, pedido ou fundamentação</Selo>
        ) : (
          <Selo tom="info" simbolo="✎">Aguardando sua confirmação</Selo>
        )}
      </div>

      {acao.pedido && (
        <p className="mb-0 mt-2 text-sm text-tinta-2">
          Pedido: <span className="text-tinta">“{acao.pedido}”</span>
        </p>
      )}
      {acao.titulo && acao.tipo === "PECA_ANEXA" && (
        <p className="mb-0 mt-2 text-sm text-tinta-2">Peça: {acao.titulo}</p>
      )}
      {acao.motivo && <p className="mb-0 mt-1 text-sm text-tinta-3">{acao.motivo}</p>}
      {acao.oQueAcontece && (
        <p className="mb-0 mt-2 text-xs leading-relaxed text-tinta-3">{acao.oQueAcontece}</p>
      )}

      {!decisao && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Botao variante="primario" pequeno disabled={ocupado} onClick={() => aoDecidir(true)}>
            {ocupado ? "Executando…" : "Confirmar"}
          </Botao>
          <Botao variante="secundario" pequeno disabled={ocupado} onClick={() => aoDecidir(false)}>
            Agora não
          </Botao>
        </div>
      )}
    </section>
  );
}

function IconeConversa() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function IconeFechar() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}
