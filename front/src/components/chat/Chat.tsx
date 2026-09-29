"use client";

/* O chat do escritório — a tela única de perguntas.
 *
 * POR QUE ELA EXISTE, TENDO JÁ TRÊS CONVERSAS NO PRODUTO
 *
 * O Acervo tinha a conversa do Dossiê (sobre a petição), a do agente (sobre um caso) e a
 * pesquisa na web (ao lado da minuta). Três telas, três históricos, três jeitos de
 * perguntar — e quem trabalha aqui não pensa em módulos, pensa em "preciso saber X".
 * Aqui a pergunta é uma só e quem escolhe o caminho é o servidor
 * (`app/chat/destinos.py`), de forma determinística.
 *
 * O QUE A TELA FAZ, E O QUE ELA NÃO FAZ
 *
 * Ela não decide destino, não classifica pergunta e não escreve resposta. O que ela faz é
 * mostrar DE ONDE cada resposta veio (o selo de origem, em `MensagemDaConversa`) e abrir
 * o caminho para o trabalho seguinte: o dossiê do caso citado, os documentos daquele caso
 * — dentro da conversa ou na tela do caso, como a pessoa preferir.
 *
 * TRÊS ATALHOS DE TECLADO, E O MOTIVO DE CADA UM
 *
 * - `#` abre a lista de casos e manda o IDENTIFICADOR, não o nome: é o que faz a pergunta
 *   chegar ao caso certo mesmo com homônimo ou grafia diferente;
 * - `/web` e `/doc` escolhem o destino sem tirar a mão do teclado. Os mesmos dois estão
 *   como botão acima do campo, para quem não sabe que existem;
 * - `Enter` envia, `Shift+Enter` quebra linha — o que qualquer chat faz. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Globe, FolderOpen, Menu, Sparkles } from "lucide-react";

import { Aviso, Botao, Selo } from "@/components/ui/Basicos";
import estilos from "@/components/chat/Chat.module.css";
import HistoricoDeSessoes from "@/components/chat/HistoricoDeSessoes";
import MensagemDaConversa from "@/components/chat/MensagemDaConversa";
import { filtrarCasos, inicioDaMencao } from "@/lib/atalhoDeCaso";
import {
  abrirSessao,
  apagarSessao,
  buscarSessao,
  estadoDoChat,
  listarSessoes,
  perguntar,
  type EstadoDoChat,
  type MensagemDoChat,
  type ModoDoChat,
  type ResumoDeSessao,
  type SessaoCompleta,
} from "@/lib/chat";
import type { Caso } from "@/lib/types";
import * as api from "@/lib/api";

/* As sugestões são as quatro coisas que esta tela sabe fazer, uma por destino. Ler as
 * quatro ensina o alcance do chat mais rápido do que qualquer texto de ajuda. */
const SUGESTOES = [
  {
    titulo: "Perguntar sobre um caso",
    exemplo: "Como está o caso do #cliente? O que falta para peticionar?",
  },
  {
    titulo: "Ver os documentos de um caso",
    exemplo: "Quais documentos o caso do #cliente já tem?",
  },
  {
    titulo: "Pesquisar na internet",
    exemplo: "/web o que diz a NR-12 sobre proteção de máquinas?",
  },
  {
    titulo: "Ler o escritório inteiro",
    exemplo: "Quais casos estão parados esperando documento?",
  },
];

interface Props {
  /** Leva ao dossiê do caso — é o que faz a resposta valer como caminho. */
  onAbrirCaso: (casoId: string) => void;
  /** Leva a qualquer outra tela do sistema (Panorama, checklist, documentação). */
  onNavegar: (tela: string, casoId?: string | null) => void;
}

export default function Chat({ onAbrirCaso, onNavegar }: Props) {
  const [sessoes, setSessoes] = useState<ResumoDeSessao[]>([]);
  const [teto, setTeto] = useState(8);
  const [atual, setAtual] = useState<SessaoCompleta | null>(null);
  const [estado, setEstado] = useState<EstadoDoChat | null>(null);
  const [casos, setCasos] = useState<Caso[]>([]);
  const [texto, setTexto] = useState("");
  const [modo, setModo] = useState<ModoDoChat>("AUTO");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  const [aConfirmar, setAConfirmar] = useState<string | null>(null);
  const [gavetaAberta, setGavetaAberta] = useState(false);
  /* O atalho `#` sendo digitado: onde começa e o que já foi escrito depois dele. `null`
   * quando não há nenhum — o seletor só existe enquanto o cursor está dentro da menção. */
  const [mencao, setMencao] = useState<{ inicio: number; termo: string } | null>(null);
  const [indiceDoAtalho, setIndiceDoAtalho] = useState(0);

  const fim = useRef<HTMLDivElement>(null);
  const campo = useRef<HTMLTextAreaElement>(null);

  const recarregarHistorico = useCallback(async () => {
    try {
      const { sessoes: lista, teto: limite } = await listarSessoes();
      setSessoes(lista);
      setTeto(limite);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível abrir o histórico.");
    }
  }, []);

  useEffect(() => {
    void recarregarHistorico();
    // O estado dos serviços externos: é o que permite avisar ANTES da pergunta que a
    // pesquisa na web está desligada, em vez de depois de trinta segundos de espera.
    void estadoDoChat().then(setEstado).catch(() => undefined);
    // A lista de casos serve ao atalho `#`. Falha aqui não é erro de tela: sem ela o
    // seletor some e citar o cliente pelo nome continua funcionando.
    void api.listarCasos().then(setCasos).catch(() => undefined);
  }, [recarregarHistorico]);

  const casosDoAtalho = useMemo(
    () => (mencao ? filtrarCasos(casos, mencao.termo) : []),
    [casos, mencao],
  );

  async function abrir(sessaoId: string) {
    setErro("");
    setGavetaAberta(false);
    try {
      setAtual(await buscarSessao(sessaoId));
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível abrir a conversa.");
    }
  }

  async function comecarNova() {
    setErro("");
    setTexto("");
    setModo("AUTO");
    setGavetaAberta(false);
    try {
      const { sessao, apagadas } = await abrirSessao();
      setAtual(sessao);
      // O que a poda levou é dito em voz alta: barra lateral que encolhe sozinha parece
      // defeito, e a conversa apagada não volta.
      setAviso(
        apagadas.length
          ? `A conversa mais antiga saiu para caber no limite de ${teto}.`
          : "",
      );
      await recarregarHistorico();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível abrir a conversa.");
    }
  }

  async function apagar(sessaoId: string) {
    setAConfirmar(null);
    try {
      await apagarSessao(sessaoId);
      if (atual?.id === sessaoId) setAtual(null);
      await recarregarHistorico();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível apagar a conversa.");
    }
  }

  const enviar = useCallback(
    async (pergunta: string, opcoes: { modo?: ModoDoChat; casoId?: string } = {}) => {
      const limpa = pergunta.trim();
      if (!limpa || enviando) return;

      setErro("");
      setAviso("");
      setTexto("");
      setMencao(null);
      setEnviando(true);

      // A pergunta aparece antes de a resposta chegar: esperar a ida e a volta para
      // mostrar o que a própria pessoa escreveu faz a tela parecer travada.
      const provisoria: MensagemDoChat = {
        id: `local-${Date.now()}`,
        papel: "USER",
        conteudo: limpa,
        natureza: "PERGUNTA",
        criadaEm: new Date().toISOString(),
        atalhos: [],
        fontes: [],
        temFonteOficial: null,
        afirmacoes: [],
        pendencias: [],
        falta: [],
        candidatos: [],
        consultas: [],
        documentos: null,
      };

      try {
        let sessao = atual;
        if (!sessao) {
          const nova = await abrirSessao();
          sessao = nova.sessao;
          setAtual({ ...nova.sessao, mensagens: [provisoria] });
        } else {
          setAtual({ ...sessao, mensagens: [...sessao.mensagens, provisoria] });
        }

        const resposta = await perguntar(sessao.id, limpa, {
          modo: opcoes.modo ?? modo,
          casoId: opcoes.casoId ?? null,
        });
        setAtual((anterior) =>
          anterior
            ? {
                ...anterior,
                ...resposta.sessao,
                mensagens: [...anterior.mensagens, resposta.mensagem],
              }
            : anterior,
        );
        // O modo é de UMA pergunta, não da conversa: quem pesquisou na web uma vez não
        // quer que a próxima pergunta, sobre um cliente, também vá para a internet.
        setModo("AUTO");
        await recarregarHistorico();
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : "Não foi possível perguntar.");
      } finally {
        setEnviando(false);
        fim.current?.scrollIntoView({ behavior: "smooth" });
      }
    },
    [atual, enviando, modo, recarregarHistorico],
  );

  /* ------------------------------------------------------------ o atalho `#` */

  function aoDigitar(valor: string, cursor: number) {
    setTexto(valor);
    const inicio = inicioDaMencao(valor, cursor);
    if (inicio < 0) {
      setMencao(null);
      return;
    }
    setMencao({ inicio, termo: valor.slice(inicio + 1, cursor) });
    setIndiceDoAtalho(0);
  }

  function escolherDoAtalho(caso: Caso) {
    if (!mencao) return;
    const antes = texto.slice(0, mencao.inicio);
    const depois = texto.slice(mencao.inicio + 1 + mencao.termo.length);
    // O nome entra no texto para quem lê; o identificador vai junto da pergunta porque
    // é ele que o servidor reconhece sem ambiguidade.
    const novo = `${antes}${caso.cliente}${depois}`;
    setTexto(novo);
    setMencao(null);
    campo.current?.focus();
  }

  function aoTeclar(evento: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (mencao && casosDoAtalho.length > 0) {
      if (evento.key === "ArrowDown") {
        evento.preventDefault();
        setIndiceDoAtalho((i) => (i + 1) % casosDoAtalho.length);
        return;
      }
      if (evento.key === "ArrowUp") {
        evento.preventDefault();
        setIndiceDoAtalho((i) => (i - 1 + casosDoAtalho.length) % casosDoAtalho.length);
        return;
      }
      if (evento.key === "Enter" || evento.key === "Tab") {
        evento.preventDefault();
        escolherDoAtalho(casosDoAtalho[indiceDoAtalho]);
        return;
      }
      if (evento.key === "Escape") {
        setMencao(null);
        return;
      }
    }

    if (evento.key === "Enter" && !evento.shiftKey) {
      evento.preventDefault();
      void enviar(texto);
    }
  }

  /* ------------------------------------------------------------------ desenho */

  const mensagens = atual?.mensagens ?? [];
  const webDesligada = estado !== null && !estado.web;
  /* A última coisa que a pessoa perguntou. É o que o clique num candidato reenvia. */
  const ultimaPergunta =
    [...mensagens].reverse().find((m) => m.papel === "USER")?.conteudo ?? "";

  return (
    <div className={estilos.pagina}>
      <aside
        className={`${estilos.historico} ${gavetaAberta ? estilos.historicoAberto : ""}`}
      >
        <HistoricoDeSessoes
          sessoes={sessoes}
          teto={teto}
          abertaId={atual?.id ?? null}
          aConfirmar={aConfirmar}
          onAbrir={(id) => void abrir(id)}
          onNova={() => void comecarNova()}
          onPedirExclusao={setAConfirmar}
          onApagar={(id) => void apagar(id)}
        />
      </aside>

      <section className={estilos.conversa}>
        <header className={estilos.cabecalho}>
          <span className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              className={`${estilos.botaoDaGaveta} ${estilos.modo}`}
              onClick={() => setGavetaAberta((aberta) => !aberta)}
              aria-label="Abrir o histórico de conversas"
            >
              <Menu size={15} aria-hidden />
            </button>
            <span className={estilos.tituloDaConversa}>
              {atual?.titulo ?? "Nova conversa"}
            </span>
          </span>
          <span className={estilos.selosDoCabecalho}>
            {/* O assunto em curso, dito em voz alta. É ele que faz "videos sobre" ser
                entendido — e quem lê precisa saber dentro de que assunto está
                perguntando, senão a resposta parece adivinhação. */}
            {atual?.assunto && (
              <Selo tom="info" simbolo="•">
                {atual.assunto.length > 48
                  ? `${atual.assunto.slice(0, 47)}…`
                  : atual.assunto}
              </Selo>
            )}
            {atual?.resumo && <Selo tom="neutro">{atual.resumo}</Selo>}
            {webDesligada && <Selo tom="atencao">pesquisa na web desligada</Selo>}
          </span>
        </header>

        <div className={estilos.mensagens}>
          {mensagens.length === 0 ? (
            <div className={estilos.abertura}>
              <h2 className={estilos.saudacao}>O que você precisa saber?</h2>
              <p className={estilos.explicacao}>
                Pergunte sobre um caso do escritório, sobre a papelada de um cliente ou
                sobre a lei. Eu decido onde procurar e digo de onde veio a resposta.
              </p>
              <div className={estilos.sugestoes}>
                {SUGESTOES.map((sugestao) => (
                  <button
                    key={sugestao.titulo}
                    type="button"
                    className={estilos.sugestao}
                    onClick={() => {
                      setTexto(sugestao.exemplo);
                      campo.current?.focus();
                    }}
                  >
                    <span className={estilos.tituloDaSugestao}>{sugestao.titulo}</span>
                    <span className={estilos.exemploDaSugestao}>{sugestao.exemplo}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className={estilos.fio}>
              {mensagens.map((mensagem) => (
                <MensagemDaConversa
                  key={mensagem.id}
                  mensagem={mensagem}
                  onAbrirCaso={onAbrirCaso}
                  onNavegar={onNavegar}
                  /* Clicar num candidato repete a PERGUNTA que gerou a lista, agora
                     com o caso escolhido — e não o que por acaso sobrou no campo.
                     Reenviar outro texto responderia a uma pergunta que ninguém fez. */
                  onEscolherCaso={(casoId) =>
                    void enviar(ultimaPergunta || "Responda sobre este caso.", { casoId })
                  }
                />
              ))}
              {enviando && (
                <p className={estilos.exemploDaSugestao}>
                  Procurando… consultas ao acervo e à internet levam alguns segundos.
                </p>
              )}
              <div ref={fim} />
            </div>
          )}
        </div>

        <div className={estilos.rodape}>
          <form
            className={estilos.formulario}
            onSubmit={(evento) => {
              evento.preventDefault();
              void enviar(texto);
            }}
          >
            {(erro || aviso) && (
              <Aviso tom={erro ? "critico" : "info"}>{erro || aviso}</Aviso>
            )}

            <div className={estilos.modos}>
              <button
                type="button"
                className={`${estilos.modo} ${modo === "WEB" ? estilos.modoLigado : ""}`}
                onClick={() => setModo((atualModo) => (atualModo === "WEB" ? "AUTO" : "WEB"))}
                disabled={webDesligada}
                title={
                  webDesligada
                    ? "A pesquisa na web está desligada (falta OPENROUTER_API_KEY no .env)."
                    : "Manda esta pergunta para a internet, com as fontes."
                }
              >
                <Globe size={14} aria-hidden />
                Pesquisar na web
              </button>
              <button
                type="button"
                className={`${estilos.modo} ${modo === "DOCUMENTOS" ? estilos.modoLigado : ""}`}
                onClick={() =>
                  setModo((atualModo) => (atualModo === "DOCUMENTOS" ? "AUTO" : "DOCUMENTOS"))
                }
                title="Mostra os documentos do caso citado, do jeito que estão guardados."
              >
                <FolderOpen size={14} aria-hidden />
                Documentos do caso
              </button>
              {modo !== "AUTO" && (
                <span className={estilos.dicaDoRodape}>
                  vale só para a próxima pergunta
                </span>
              )}
            </div>

            <div className={estilos.caixaDeTexto}>
              {mencao && casosDoAtalho.length > 0 && (
                <div className={estilos.seletorDeCaso} role="listbox">
                  {casosDoAtalho.map((caso, indice) => (
                    <button
                      key={caso.id}
                      type="button"
                      className={`${estilos.opcaoDeCaso} ${
                        indice === indiceDoAtalho ? estilos.opcaoAtiva : ""
                      }`}
                      onClick={() => escolherDoAtalho(caso)}
                    >
                      <span className={estilos.nomeDaOpcao}>{caso.cliente}</span>
                      <span className={estilos.detalheDaOpcao}>
                        {String(caso.categoria ?? "").replace(/_/g, " ")}
                      </span>
                    </button>
                  ))}
                </div>
              )}

              <textarea
                ref={campo}
                className={estilos.entrada}
                rows={1}
                value={texto}
                placeholder="Pergunte qualquer coisa. Use # para citar um caso, /web para a internet."
                onChange={(evento) =>
                  aoDigitar(evento.target.value, evento.target.selectionStart ?? 0)
                }
                onKeyDown={aoTeclar}
              />
              <Botao
                variante="primario"
                type="submit"
                carregando={enviando}
                textoCarregando="Procurando"
                disabled={!texto.trim()}
              >
                <Sparkles size={15} aria-hidden />
                Perguntar
              </Botao>
            </div>

            <span className={estilos.dicaDoRodape}>
              Enter envia · Shift+Enter quebra linha · respostas da internet pedem
              conferência na fonte oficial antes de irem para a peça.
            </span>
          </form>
        </div>
      </section>
    </div>
  );
}
