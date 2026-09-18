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
 *
 * E uma regra de uso, vinda da primeira leitura da tela pronta: quem abre isto não sabe
 * o que pode pedir. Por isso o começo da conversa não é um campo vazio com uma frase
 * explicando — são três coisas concretas para clicar, e elas continuam ao alcance como
 * atalhos depois que a conversa começa.
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
  type ConfiancaDaFonte,
  type FonteDaWeb,
  type MensagemDoChat,
} from "@/lib/chatPeticao";

/**
 * O que dá para pedir aqui, em três coisas concretas.
 *
 * `envia: true` manda a pergunta como está — ela se basta. As outras duas ESCREVEM o
 * começo da frase no campo e deixam o cursor no fim: "busque na web" sem o assunto e
 * "altere a peça" sem dizer o quê não são pedidos, e mandá-las prontas gastaria uma
 * volta no modelo só para receber de volta "sobre o quê?".
 */
const ATALHOS: { rotulo: string; dica: string; texto: string; envia: boolean }[] = [
  {
    rotulo: "Entender a peça",
    dica: "O que ainda não tem prova, o que está frágil, por quê",
    texto: "O que nesta petição ainda não tem comprovação documental, e por quê?",
    envia: true,
  },
  {
    rotulo: "Buscar na web",
    dica: "Jurisprudência, súmula, lei — sempre com a fonte e o link",
    texto: "Pesquise na web ",
    envia: false,
  },
  {
    rotulo: "Alterar a petição",
    dica: "Você vê o antes × depois e decide antes de virar versão",
    texto: "Altere a petição: ",
    envia: false,
  },
];

/** O quarto caminho: existe como link no painel, e aqui vira pergunta. */
const CONFRONTO = "Mostre o confronto entre a entrevista e os documentos.";

interface Props {
  casoId: string;
  /** Recarrega a minuta e o histórico do lado esquerdo: é o que faz a comparação
   *  proposta pelo chat aparecer sobre o documento. */
  aoMudarAPeticao: () => void;
  /** Fecha a gaveta. Em tela larga o painel é coluna fixa e o botão não aparece. */
  aoFechar?: () => void;
  /** Alterna entre a coluna normal e a larga. Quem manda na grade é o `FluxoPeticao`. */
  expandido?: boolean;
  aoAlternarLargura?: () => void;
}

export default function ChatPeticao({
  casoId,
  aoMudarAPeticao,
  aoFechar,
  expandido,
  aoAlternarLargura,
}: Props) {
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
  /* Quem rolou para cima está LENDO. Empurrar a conversa para o fim a cada pedaço de
   * texto que chega arranca do meio da leitura a resposta anterior, e não há como voltar
   * a ela sem procurar. Enquanto isso, o botão de descer diz que chegou coisa nova. */
  const [preso, setPreso] = useState(true);
  const conversa = useRef<HTMLDivElement>(null);
  const campo = useRef<HTMLTextAreaElement>(null);
  /* De QUAL caso é o que está na tela agora. O Dossiê vive em estado, e não em rota
   * (ver `app/home/home.model.ts`): voltar no navegador para o dossiê de outro caso
   * troca o `casoId` SEM remontar este componente. Sem esta referência, uma resposta
   * ou uma ação pedida no caso anterior voltaria do servidor depois da troca e entraria
   * na transcrição do caso novo. */
  const casoNaTela = useRef(casoId);
  /* A pergunta em voo pertence ao caso em que foi feita: trocar de caso a cancela, em
   * vez de deixá-la escrevendo no fluxo de outra conversa. */
  const emVoo = useRef<AbortController | null>(null);

  const descer = useCallback(() => {
    // `scrollTop` no contêiner, e não `scrollIntoView`: com o painel em coluna sticky, o
    // `scrollIntoView` arrastava a PÁGINA inteira junto, e o documento ao lado saía da
    // vista a cada pedaço de resposta que chegava.
    const alvo = conversa.current;
    if (alvo) alvo.scrollTop = alvo.scrollHeight;
    setPreso(true);
  }, []);

  const ajustarAltura = useCallback(() => {
    const alvo = campo.current;
    if (!alvo) return;
    // Zerar antes de medir: sem isto o `scrollHeight` nunca diminui e o campo fica
    // grande para sempre depois de uma pergunta longa.
    alvo.style.height = "auto";
    alvo.style.height = `${Math.min(alvo.scrollHeight, 168)}px`;
  }, []);

  useEffect(() => {
    let ativo = true;
    /* Zerar ANTES de buscar o histórico do caso novo. A transcrição é renderizada
     * mesmo durante o carregamento, então sem esta limpeza a conversa do caso anterior
     * seguiria na tela sob o aviso "Abrindo a conversa deste caso…" — e o pior: as
     * propostas já aceitas ou descartadas lá (`decididas`, que é chave de mensagem)
     * continuariam valendo aqui, além do rascunho no campo e do erro do outro caso. */
    casoNaTela.current = casoId;
    emVoo.current?.abort();
    emVoo.current = null;
    setMensagens([]);
    setDecididas({});
    setExecutando(null);
    setTexto("");
    setParcial("");
    setEtapa("");
    setEnviando(false);
    setErro("");
    setPreso(true);
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
    if (preso) descer();
  }, [mensagens, parcial, etapa, preso, descer]);

  /* O campo acompanha o que se escreve e para de crescer em ~6 linhas. As três linhas
   * fixas de antes roubavam altura da leitura mesmo quando a pergunta tinha cinco
   * palavras — e prendiam o pedido longo numa janelinha com rolagem própria. Rodar isto
   * por efeito, e não só no `onChange`, cobre também o que o código escreve no campo:
   * os atalhos que começam a frase e a limpeza depois do envio. */
  useEffect(ajustarAltura, [texto, ajustarAltura]);

  /* O que os BOTÕES do painel fizeram chega por evento de janela (ver
   * `lib/chatPeticao.avisarChatDaPeticao`). A IA conta na conversa o que mudou — é
   * depois de uma geração que o advogado mais precisa saber o que ficou sem prova. */
  useEffect(() => {
    async function aoAvisar(evento: Event) {
      const { detail } = evento as CustomEvent<AvisoParaOChat>;
      if (!detail || detail.casoId !== casoId) return;
      try {
        const mensagem = await registrarEventoNoChat(casoId, detail.tipo, detail.dados ?? {});
        // A ida ao servidor demora: se o dossiê já é outro, a mensagem ficou gravada na
        // conversa certa e só não pode aparecer nesta.
        if (mensagem && casoNaTela.current === casoId) {
          setMensagens((atuais) => [...atuais, mensagem]);
        }
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
      const controle = new AbortController();
      emVoo.current?.abort();
      emVoo.current = controle;
      /** Esta pergunta ainda é a que está na tela? Deixa de ser quando o caso troca. */
      const ehDaTela = () => emVoo.current === controle;
      setErro("");
      setTexto("");
      setParcial("");
      setEtapa("Lendo o caso");
      setEnviando(true);
      setPreso(true);
      try {
        await perguntarNoChat(
          casoId,
          limpa,
          (evento) => {
            // Chegou tarde: o dossiê na tela já é outro. A resposta continua gravada na
            // conversa do caso que a pediu — só não invade a transcrição deste.
            if (!ehDaTela()) return;
            switch (evento.tipo) {
              case "pergunta":
                setMensagens((atuais) => [...atuais, evento.mensagem]);
                break;
              case "etapa":
                setEtapa(evento.texto);
                break;
              case "delta":
                setEtapa("");
                setParcial((anterior) => anterior + evento.texto);
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
          },
          controle.signal,
        );
      } catch (falha) {
        // O cancelamento pela troca de caso não é falha de ninguém: avisar "a conversa
        // não chegou ao servidor" no caso recém-aberto seria mentira.
        if (ehDaTela()) {
          setErro(
            falha instanceof Error
              ? falha.message
              : "A conversa não chegou ao servidor. Tente de novo.",
          );
        }
      } finally {
        if (ehDaTela()) {
          emVoo.current = null;
          setEnviando(false);
          setEtapa("");
          setParcial("");
        }
      }
    },
    [casoId, enviando],
  );

  /** Atalho que não se basta: escreve o começo da frase e devolve o cursor ao campo. */
  function comecarFrase(inicio: string) {
    setTexto(inicio);
    const alvo = campo.current;
    if (!alvo) return;
    alvo.focus();
    // No FIM do texto: o cursor no lugar errado faz a pessoa escrever
    // "Pesquise na webestabilidade acidentária".
    requestAnimationFrame(() => alvo.setSelectionRange(inicio.length, inicio.length));
  }

  function usarAtalho(atalho: (typeof ATALHOS)[number]) {
    if (atalho.envia) void perguntar(atalho.texto);
    else comecarFrase(atalho.texto);
  }

  async function decidir(chave: string, acao: AcaoProposta, aceitar: boolean) {
    if (!aceitar) {
      setDecididas((atuais) => ({ ...atuais, [chave]: "descartada" }));
      return;
    }
    const doCaso = casoId;
    setExecutando(chave);
    setErro("");
    try {
      const resultado = await executarAcaoDoChat(doCaso, acao);
      // Gerar ou revisar leva tempo: se o dossiê na tela já é outro, a ação valeu no
      // caso certo e nada dela pode aparecer — nem o resultado, nem o recarregamento.
      if (casoNaTela.current !== doCaso) return;
      setMensagens((atuais) => [...atuais, resultado.mensagem]);
      setDecididas((atuais) => ({ ...atuais, [chave]: "aceita" }));
      // Mesmo quando a ação falha, o lado esquerdo é recarregado: uma revisão pode ter
      // sido gravada e a falha vir do passo seguinte, e a tela não pode ficar mostrando
      // uma peça mais velha do que a que está no banco.
      aoMudarAPeticao();
    } catch (falha) {
      if (casoNaTela.current !== doCaso) return;
      setErro(falha instanceof Error ? falha.message : "A ação não pôde ser executada.");
    } finally {
      // A troca de caso já zerou o `executando`; mexer nele aqui apagaria o indicador de
      // uma ação que esteja rodando no caso agora aberto.
      if (casoNaTela.current === doCaso) setExecutando(null);
    }
  }

  const conversaVazia = !carregandoHistorico && mensagens.length === 0;

  return (
    <aside className={estilos.painel} aria-label="Conversa com a IA sobre esta petição">
      {/* Uma linha só. O ícone em quadro e a frase explicativa que moravam aqui comiam
        * altura em TODA a conversa para dizer, o tempo inteiro, algo que só interessa
        * antes da primeira pergunta — e é onde eles estão agora, no convite abaixo. */}
      <header className={estilos.cabecalho}>
        <div className={estilos.identidade}>
          <span className={estilos.marca} aria-hidden>
            <IconeConversa />
          </span>
          <strong className={estilos.titulo}>Conversa sobre a peça</strong>
        </div>
        <div className={estilos.acoesDoCabecalho}>
          {aoAlternarLargura && (
            <button
              type="button"
              className={`${estilos.iconeBotao} max-lg:hidden`}
              onClick={aoAlternarLargura}
              aria-label={expandido ? "Estreitar a conversa" : "Alargar a conversa"}
              title={
                expandido ? "Estreitar — mais espaço para o documento" : "Alargar a conversa"
              }
            >
              <IconeLargura invertido={expandido} />
            </button>
          )}
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
        </div>
      </header>

      <div
        className={estilos.conversa}
        ref={conversa}
        onScroll={(evento) => {
          const alvo = evento.currentTarget;
          // 80px de folga: exigir o fim exato faria o botão piscar durante o streaming,
          // porque cada pedaço de texto muda a altura embaixo do cursor.
          setPreso(alvo.scrollHeight - alvo.scrollTop - alvo.clientHeight < 80);
        }}
      >
        {carregandoHistorico && <p className={estilos.vazio}>Abrindo a conversa deste caso…</p>}

        {!modeloDisponivel && (
          <Aviso tom="atencao" titulo="A conversa está desligada">
            Falta a chave do modelo no servidor (DEEPSEEK_API_KEY). Os botões de gerar,
            analisar e revisar continuam funcionando normalmente.
          </Aviso>
        )}

        {conversaVazia && modeloDisponivel && (
          <div className={estilos.comecar}>
            <p className={estilos.convite}>Por onde quer começar?</p>
            <p className={estilos.explicacao}>
              Leio a minuta, a entrevista e os documentos deste caso antes de responder.
            </p>
            <div className={estilos.cartoes}>
              {ATALHOS.map((atalho) => (
                <button
                  key={atalho.rotulo}
                  type="button"
                  className={estilos.cartao}
                  onClick={() => usarAtalho(atalho)}
                  disabled={enviando}
                >
                  <strong>{atalho.rotulo}</strong>
                  <span>{atalho.dica}</span>
                </button>
              ))}
            </div>
            <button
              type="button"
              className={`${estilos.sugestao} ${estilos.sugestaoLarga}`}
              onClick={() => void perguntar(CONFRONTO)}
              disabled={enviando}
            >
              Ver o confronto entrevista × documentos
            </button>
            <p className={estilos.rodapeDoConvite}>
              Nada na petição muda sem a sua confirmação — toda alteração passa por uma
              comparação antes × depois.
            </p>
          </div>
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

      {!preso && (
        <button type="button" className={estilos.descer} onClick={descer}>
          ↓ Ver o que chegou
        </button>
      )}

      {/* O rodapé da conversa em UMA linha de campo, e não em três blocos empilhados.
        *
        * Antes: chips sempre visíveis + campo de três linhas + botão numa linha própria +
        * legenda de teclas. Quase 190px de altura fixa comidos da leitura, para dizer
        * "Enter envia" a cada rolagem. Agora o campo começa com uma linha e cresce com o
        * que se escreve, e os atalhos recuam assim que há texto — quem já sabe o que
        * pedir não precisa mais deles. */}
      <div className={estilos.composicao}>
        {!conversaVazia && !texto.trim() && (
          <div className={estilos.sugestoes}>
            {ATALHOS.map((atalho) => (
              <button
                key={atalho.rotulo}
                type="button"
                className={estilos.sugestao}
                title={atalho.dica}
                onClick={() => usarAtalho(atalho)}
                disabled={enviando || !modeloDisponivel}
              >
                {atalho.rotulo}
              </button>
            ))}
          </div>
        )}

        <div className={estilos.linhaDeEnvio}>
          {/* Sem rótulo visível: o próprio texto de exemplo diz o que se escreve aqui, e
            * uma linha de rótulo acima do campo empurraria a conversa para cima. */}
          <textarea
            ref={campo}
            className={`campo campo--area ${estilos.campoDaPergunta}`}
            aria-label="Pergunta ou pedido sobre esta petição"
            placeholder="Pergunte ou peça uma alteração — Enter envia"
            value={texto}
            rows={1}
            disabled={!modeloDisponivel}
            onChange={(evento) => {
              setTexto(evento.target.value);
              ajustarAltura();
            }}
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
            className={estilos.enviar}
            onClick={() => void perguntar(texto)}
            disabled={enviando || !texto.trim() || !modeloDisponivel}
            aria-label={enviando ? "Enviando a pergunta" : "Enviar a pergunta"}
            title="Enviar · Shift+Enter quebra linha"
          >
            <IconeEnviar />
          </button>
        </div>
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

      {mensagem.fontes.length > 0 && <Fontes fontes={mensagem.fontes} />}

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

/** Como cada camada da hierarquia se apresenta. Palavra + cor, nunca só cor. */
const CAMADAS: Record<ConfiancaDaFonte, { rotulo: string; classe: string }> = {
  OFICIAL: { rotulo: "Oficial", classe: "border-ok bg-ok-claro text-ok" },
  TRIBUNAL: { rotulo: "Tribunal", classe: "border-ok bg-ok-claro text-ok" },
  PUBLICA: { rotulo: "Órgão público", classe: "border-acao-borda bg-acao-clara text-acao" },
  SECUNDARIA: { rotulo: "Não oficial", classe: "border-atencao-borda bg-atencao-claro text-atencao" },
};

/**
 * As fontes da web, na ordem em que o servidor as classificou: oficial primeiro.
 *
 * O aviso do topo muda conforme a busca tenha ou não encontrado norma ou tribunal. Sem
 * ele, uma resposta inteiramente apoiada em portal jurídico chegava com a mesma cara de
 * uma apoiada no Planalto — e é dela que sai o número de súmula que vai para a peça.
 */
function Fontes({ fontes }: { fontes: FonteDaWeb[] }) {
  const oficiais = fontes.filter(
    (f) => f.confianca === "OFICIAL" || f.confianca === "TRIBUNAL",
  ).length;
  return (
    <div className={estilos.fontes}>
      <p className={estilos.tituloDasFontes}>
        Da web — {fontes.length} fonte(s)
        {oficiais > 0 ? `, ${oficiais} oficial(is)` : ", nenhuma oficial"}
      </p>
      {oficiais === 0 && (
        <p className="mb-2 mt-0 text-xs leading-relaxed text-atencao">
          Nenhuma norma no Planalto, decisão no site do tribunal ou órgão público
          sustentou esta busca. Confirme na fonte antes de levar para a peça.
        </p>
      )}
      <ol className={estilos.listaDeFontes}>
        {fontes.map((fonte) => {
          const camada = CAMADAS[fonte.confianca] ?? CAMADAS.SECUNDARIA;
          return (
            <li key={fonte.url}>
              <span className="flex flex-wrap items-baseline gap-x-2">
                <a
                  href={fonte.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-acao underline break-words"
                >
                  {fonte.titulo || dominioDe(fonte.url)}
                </a>
                <span
                  className={`rounded-pill border px-[6px] py-[1px] text-[11px] font-semibold ${camada.classe}`}
                >
                  {camada.rotulo}
                </span>
              </span>
              <span className={estilos.dominio}>{dominioDe(fonte.url)}</span>
            </li>
          );
        })}
      </ol>
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

function IconeEnviar() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12h13M12 5l7 7-7 7" />
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

/** Setas para fora (alargar) ou para dentro (estreitar). */
function IconeLargura({ invertido }: { invertido?: boolean }) {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {invertido ? (
        <path d="M13 5h6v6M19 5l-7 7M11 19H5v-6M5 19l7-7" />
      ) : (
        <path d="M19 9V3h-6M13 11l6-6M5 15v6h6M11 13l-6 6" />
      )}
    </svg>
  );
}
