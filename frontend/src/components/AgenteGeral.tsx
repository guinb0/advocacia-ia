"use client";

/* O agente fora do caso — chat com histórico, acessível da Carteira.
 *
 * A tela existe para uma pergunta que o painel do caso não atende: a que se faz antes de
 * saber qual caso abrir. Por isso ela tem histórico de verdade (conversas persistidas,
 * agrupadas por dia, com busca) e não uma sessão que morre ao trocar de tela.
 *
 * O limite que ela NÃO esconde: o chat do backend é por caso. Pergunta que atravessa o
 * acervo inteiro — "quais casos estão parados esperando documento?" — não tem quem
 * responda ainda, e a tela diz isso, com o que faltaria para passar a ter. Melhor uma
 * tela que declara o que ainda não sabe do que uma que responde por aproximação: este
 * sistema inteiro é construído sobre a diferença entre o que foi apurado e o que é
 * plausível.
 *
 * O roteamento não mora aqui, e sim no backend (`app/agente/conversa_geral.py`): ele é
 * determinístico, e precisa ser o mesmo para qualquer tela que venha depois desta. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Aviso, Selo } from "@/components/ui/Basicos";
import estilos from "@/components/AgenteGeral.module.css";
import { CartaoDeProposta, LastroDaResposta } from "@/components/RespostaDoAgente";
import { useSessao } from "@/lib/auth";
import { confirmarProposta, type PropostaDoAgente } from "@/lib/agente";
import { filtrarCasos, inicioDaMencao } from "@/lib/atalhoDeCaso";
import {
  abrirConversa,
  apagarConversa,
  buscarConversa,
  fixarCaso,
  listarConversas,
  perguntar,
  type ConsultaDoAnalista,
  type ConversaCompleta,
  type MensagemDaConversa,
  type ResumoDeConversa,
} from "@/lib/conversas";
import type { Caso } from "@/lib/types";
import * as api from "@/lib/api";

/* As três primeiras são o que a tela sabe fazer; a última é deliberada.
 *
 * Deixar uma pergunta de acervo entre as sugestões parece contraditório, e não é: quem
 * chega aqui vai fazê-la de qualquer jeito, e é melhor que descubra o limite pela
 * resposta honesta — que diz o que falta — do que depois de formular três perguntas e
 * receber a mesma recusa sem entender por quê. */
const SUGESTOES = [
  "O que é um fato alegado?",
  "Quando a petição pode ser gerada?",
  "Como funciona a entrevista guiada?",
  "Quais casos estão parados esperando documento?",
];

interface Props {
  onVoltar: () => void;
  /** Leva ao dossiê do caso citado. É o que faz a resposta valer como caminho. */
  onAbrirCaso: (casoId: string) => void;
}

export default function AgenteGeral({ onVoltar, onAbrirCaso }: Props) {
  const sessao = useSessao();
  const [conversas, setConversas] = useState<ResumoDeConversa[]>([]);
  const [busca, setBusca] = useState("");
  const [atual, setAtual] = useState<ConversaCompleta | null>(null);
  const [casos, setCasos] = useState<Caso[]>([]);
  const [propostas, setPropostas] = useState<PropostaDoAgente[]>([]);
  const [texto, setTexto] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [aConfirmarExclusao, setAConfirmarExclusao] = useState<string | null>(null);
  /* O atalho `#` sendo digitado: onde ele começa no texto e o que já foi escrito depois
   * dele. `null` quando não há nenhum — o seletor só existe enquanto o cursor está
   * dentro da menção. */
  const [mencao, setMencao] = useState<{ inicio: number; termo: string } | null>(null);
  const [indiceDoAtalho, setIndiceDoAtalho] = useState(0);
  /* O caso ESCOLHIDO da lista. Guardado à parte do texto de propósito: o que vai para o
   * servidor é o identificador, não o nome — é o que faz a pergunta chegar ao caso certo
   * mesmo com homônimo, grafia diferente ou nome incompleto. */
  const [casoDaMencao, setCasoDaMencao] = useState<{ id: string; cliente: string } | null>(
    null,
  );
  const fim = useRef<HTMLDivElement>(null);
  const campo = useRef<HTMLTextAreaElement>(null);

  const recarregarHistorico = useCallback(async (termo: string) => {
    try {
      setConversas(await listarConversas(termo));
      setErro("");
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível abrir o histórico.");
    }
  }, []);

  /* A busca espera o dedo parar. Sem isso, "documento" dispara nove consultas e as
   * respostas voltam fora de ordem — a lista pisca com o resultado de "docum". */
  useEffect(() => {
    const relogio = setTimeout(() => void recarregarHistorico(busca), 250);
    return () => clearTimeout(relogio);
  }, [busca, recarregarHistorico]);

  useEffect(() => {
    // A lista de casos serve ao seletor "responder sobre". Falha aqui não é erro de tela:
    // sem ela o seletor some, e a citação pelo nome continua funcionando.
    void api
      .listarCasos()
      .then(setCasos)
      .catch(() => undefined);
  }, []);

  const grupos = useMemo(() => agrupar(conversas), [conversas]);

  async function abrir(conversaId: string) {
    setErro("");
    setPropostas([]);
    try {
      setAtual(await buscarConversa(conversaId));
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível abrir a conversa.");
    }
  }

  function comecarNova() {
    // A conversa só nasce no banco com a primeira pergunta: uma tela em branco não é
    // conversa, e o histórico ficaria cheio de "Nova conversa" que ninguém abriu.
    setAtual(null);
    setPropostas([]);
    setErro("");
    setTexto("");
  }

  const enviar = useCallback(
    async (pergunta: string, casoEscolhido?: string) => {
      const limpa = pergunta.trim();
      if (!limpa || carregando) return;

      setErro("");
      setTexto("");
      setMencao(null);
      setCasoDaMencao(null);
      setCarregando(true);

      // A pergunta aparece antes de a resposta chegar: esperar a ida e a volta para
      // mostrar o que o próprio usuário escreveu faz a tela parecer travada.
      const provisoria: MensagemDaConversa = {
        id: `local-${Date.now()}`,
        papel: "USER",
        conteudo: limpa,
        natureza: "PERGUNTA",
        criadaEm: new Date().toISOString(),
        citacoes: [],
        afirmacoes: [],
        pendencias: [],
        falta: [],
        candidatos: [],
        consultas: [],
        casos: [],
      };
      setAtual((anterior) =>
        anterior ? { ...anterior, mensagens: [...anterior.mensagens, provisoria] } : anterior,
      );

      try {
        const conversa = atual ?? (await abrirConversa());
        if (!atual) setAtual({ ...conversa, mensagens: [provisoria] });

        const resposta = await perguntar(conversa.id, limpa, casoEscolhido);
        setAtual((anterior) =>
          anterior
            ? {
                ...anterior,
                ...resposta.conversa,
                mensagens: [...anterior.mensagens, resposta.mensagem],
              }
            : anterior,
        );
        setPropostas(resposta.propostas.filter((item) => item.estado === "PENDING"));
        void recarregarHistorico(busca);
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : "Não foi possível perguntar.");
      } finally {
        setCarregando(false);
        fim.current?.scrollIntoView({ behavior: "smooth" });
      }
    },
    [atual, busca, carregando, recarregarHistorico],
  );

  async function trocarCaso(casoId: string | null) {
    if (!atual) {
      // Sem conversa aberta ainda não há o que fixar; a próxima pergunta abre uma, e o
      // caso vem do nome citado nela.
      return;
    }
    try {
      setAtual(await fixarCaso(atual.id, casoId));
      void recarregarHistorico(busca);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível trocar o caso.");
    }
  }

  async function apagar(conversaId: string) {
    try {
      await apagarConversa(conversaId);
      setAConfirmarExclusao(null);
      if (atual?.id === conversaId) comecarNova();
      void recarregarHistorico(busca);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível apagar a conversa.");
    }
  }

  async function aplicar(proposta: PropostaDoAgente, casoId?: string) {
    if (!casoId) return;
    setErro("");
    try {
      const aplicada = await confirmarProposta(casoId, proposta.id);
      setPropostas((atuais) => atuais.filter((item) => item.id !== aplicada.id));
    } catch (falha) {
      // A recusa mais comum é a proposta obsoleta — o caso mudou desde que ela foi feita.
      // O texto do agente já diz isso e o que fazer, então ele chega como está.
      setErro(falha instanceof Error ? falha.message : "Não foi possível aplicar.");
    }
  }

  /** A pergunta que gerou uma resposta: a mensagem do usuário imediatamente anterior.
   *
   *  É o que o clique num caso da lista de desambiguação reenvia — a pessoa não deveria ter
   *  de digitar de novo o que acabou de perguntar. */
  function perguntaAnterior(idDaResposta: string): string {
    const mensagens = atual?.mensagens ?? [];
    const posicao = mensagens.findIndex((item) => item.id === idDaResposta);
    for (let i = posicao - 1; i >= 0; i -= 1) {
      if (mensagens[i].papel === "USER") return mensagens[i].conteudo;
    }
    return "";
  }

  const candidatos = useMemo(
    () => (mencao ? filtrarCasos(casos, mencao.termo) : []),
    [casos, mencao],
  );

  /** Reavalia a menção a cada mudança de texto OU de cursor.
   *
   * O cursor entra na conta porque ele se move sem o texto mudar — seta, clique, `Home`.
   * Sem isso a lista continuaria aberta depois de o advogado sair da menção para corrigir
   * o começo da frase, e a próxima tecla seria capturada por um seletor invisível. */
  function sincronizarMencao(elemento: HTMLTextAreaElement) {
    const cursor = elemento.selectionStart ?? elemento.value.length;
    const inicio = inicioDaMencao(elemento.value, cursor);
    if (inicio < 0) {
      setMencao(null);
      return;
    }
    setMencao({ inicio, termo: elemento.value.slice(inicio + 1, cursor) });
    setIndiceDoAtalho(0);
  }

  function escolherNoAtalho(caso: Caso) {
    if (!mencao) return;
    const antes = texto.slice(0, mencao.inicio);
    const depois = texto.slice(mencao.inicio + 1 + mencao.termo.length);
    // O espaço depois do nome é o que permite continuar a frase sem reabrir a lista.
    const separador = depois.startsWith(" ") ? "" : " ";
    const escrito = `${antes}#${caso.cliente}${separador}`;
    setTexto(escrito + depois);
    setCasoDaMencao({ id: caso.id, cliente: caso.cliente });
    setMencao(null);
    // O foco volta ao campo e o cursor fica DEPOIS da menção: escolher da lista é meio da
    // frase, não fim dela — quem escolheu ainda vai escrever a pergunta.
    window.requestAnimationFrame(() => {
      const elemento = campo.current;
      if (!elemento) return;
      elemento.focus();
      elemento.setSelectionRange(escrito.length, escrito.length);
    });
  }

  /* A menção só vale enquanto o nome continua escrito. Apagá-la desfaz a amarração — do
   * contrário a pergunta seguinte iria para um caso que não está mais na frase. */
  const casoAmarrado =
    casoDaMencao && texto.includes(`#${casoDaMencao.cliente}`) ? casoDaMencao : null;

  const casoDaConversa = casos.find((caso) => caso.id === atual?.casoId);
  const ultimoCasoCitado = [...(atual?.mensagens ?? [])].reverse().find((m) => m.casoId)?.casoId;

  return (
    <div className={estilos.pagina}>
      <aside className={estilos.historico} aria-label="Histórico de conversas">
        <div className={estilos.blocoDoTopo}>
          <button
            type="button"
            className="botao botao--primario botao--bloco"
            onClick={comecarNova}
          >
            <IconeMais />
            Nova conversa
          </button>
        </div>

        <div className={estilos.blocoDaBusca}>
          <label className={estilos.campoDeBusca}>
            <IconeLupa />
            {/* Rótulo invisível, e não `placeholder` sozinho: o campo continua nomeado
              * para quem usa leitor de tela, sem uma segunda linha de texto empurrando o
              * histórico para baixo. */}
            <span className="somenteLeitor">Buscar nas conversas</span>
            <input
              type="search"
              className={estilos.entradaDeBusca}
              placeholder="Buscar nas conversas"
              value={busca}
              onChange={(evento) => setBusca(evento.target.value)}
            />
          </label>
        </div>

        <div className={estilos.lista}>
          {conversas.length === 0 && (
            <p className={estilos.vazioDoHistorico}>
              {busca.trim()
                ? "Nenhuma conversa com esse texto."
                : "As conversas que você tiver aparecem aqui."}
            </p>
          )}

          {grupos.map((grupo) => (
            <div key={grupo.titulo}>
              <div className={estilos.tituloDoGrupo}>{grupo.titulo}</div>
              {grupo.conversas.map((conversa) => (
                <ItemDoHistorico
                  key={conversa.id}
                  conversa={conversa}
                  aberta={atual?.id === conversa.id}
                  aConfirmar={aConfirmarExclusao === conversa.id}
                  aoAbrir={() => void abrir(conversa.id)}
                  aoPedirExclusao={() => setAConfirmarExclusao(conversa.id)}
                  aoCancelar={() => setAConfirmarExclusao(null)}
                  aoApagar={() => void apagar(conversa.id)}
                />
              ))}
            </div>
          ))}
        </div>

        <div className={estilos.rodapeDoHistorico}>
          <span className={estilos.iniciais} aria-hidden>
            {iniciaisDe(sessao.nome || sessao.usuario)}
          </span>
          <span className={estilos.nomeDoUsuario}>{sessao.nome || sessao.usuario || "Sessão local"}</span>
        </div>
      </aside>

      <div className={estilos.coluna}>
        <header className={estilos.cabecalho}>
          <div className={estilos.tituloDaConversa}>
            <button type="button" className="botao botao--secundario botao--pequeno" onClick={onVoltar}>
              ← Carteira
            </button>
            <span className={estilos.nomeDaConversa}>{atual?.titulo ?? "Agente"}</span>
            {/* Em tela estreita o histórico sai da frente, e com ele o "Nova conversa" —
              * este botão o devolve, em vez de deixar a pessoa presa na conversa aberta. */}
            <button
              type="button"
              className={`botao botao--secundario botao--pequeno ${estilos.novaNoCabecalho}`}
              onClick={comecarNova}
            >
              Nova conversa
            </button>
          </div>

          {casos.length > 0 && (
            <label className={estilos.escolhaDeCaso}>
              <span className={estilos.rotuloDaEscolha}>Responder sobre</span>
              <select
                className="campo campo--seletor"
                value={atual?.casoId ?? ""}
                disabled={!atual}
                onChange={(evento) => void trocarCaso(evento.target.value || null)}
                title={
                  atual
                    ? "Fixa a conversa em um caso"
                    : "Escolha um caso depois da primeira pergunta, ou cite o cliente pelo nome"
                }
              >
                <option value="">Nenhum caso — sobre o sistema</option>
                {casos.map((caso) => (
                  <option key={caso.id} value={caso.id}>
                    {caso.cliente}
                  </option>
                ))}
              </select>
            </label>
          )}
        </header>

        <div className={estilos.conversa}>
          <div className={estilos.leitura}>
            {!atual && <Abertura aoSugerir={(sugestao) => void enviar(sugestao)} />}

            {casoDaConversa && (
              <p className={estilos.contexto}>
                Esta conversa está sobre o caso de <strong>{casoDaConversa.cliente}</strong>.{" "}
                <button
                  type="button"
                  className="botao botao--texto"
                  onClick={() => void trocarCaso(null)}
                >
                  Perguntar sem caso
                </button>
              </p>
            )}

            {atual?.mensagens.map((mensagem) =>
              mensagem.papel === "USER" ? (
                <div key={mensagem.id} className={estilos.pergunta}>
                  {mensagem.conteudo}
                </div>
              ) : (
                <Resposta
                  key={mensagem.id}
                  mensagem={mensagem}
                  onAbrirCaso={onAbrirCaso}
                  // Escolher um caso da lista REFAZ a pergunta sobre ele. Só fixar o caso
                  // deixaria a pessoa com a pergunta ainda sem resposta e um clique
                  // aparentemente sem efeito.
                  aoEscolherCaso={(casoId) => void enviar(perguntaAnterior(mensagem.id), casoId)}
                />
              ),
            )}

            {propostas.map((proposta) => (
              <CartaoDeProposta
                key={proposta.id}
                proposta={proposta}
                aoAplicar={() => void aplicar(proposta, atual?.casoId ?? ultimoCasoCitado)}
              />
            ))}

            {carregando && <p className={estilos.pensando}>Lendo…</p>}
            {erro && <Aviso tom="critico">{erro}</Aviso>}
            <div ref={fim} />
          </div>
        </div>

        <div className={estilos.composicao}>
          <div className={estilos.leitura}>
            <div className={estilos.ancoraDoAtalho}>
              {mencao && (
                <div className={estilos.atalho} role="listbox" aria-label="Casos do acervo">
                  <div className={estilos.atalhoTitulo}>
                    {mencao.termo ? `Casos com “${mencao.termo}”` : "Casos do acervo"}
                  </div>
                  {candidatos.length === 0 ? (
                    <p className={estilos.atalhoVazio}>
                      Nenhum caso com esse nome. Apague o <code>#</code> para perguntar
                      assim mesmo.
                    </p>
                  ) : (
                    candidatos.map((caso, posicao) => (
                      <button
                        key={caso.id}
                        type="button"
                        role="option"
                        aria-selected={posicao === indiceDoAtalho}
                        data-ativo={posicao === indiceDoAtalho ? "sim" : "nao"}
                        className={estilos.atalhoItem}
                        // `onMouseDown` e não `onClick`: o clique tira o foco do campo
                        // antes, e a lista fecharia com a escolha pela metade.
                        onMouseDown={(evento) => {
                          evento.preventDefault();
                          escolherNoAtalho(caso);
                        }}
                        onMouseEnter={() => setIndiceDoAtalho(posicao)}
                      >
                        <span className={estilos.atalhoCliente}>{caso.cliente}</span>
                        <span className={estilos.atalhoDetalhe}>
                          {String(caso.categoria ?? "").replace(/_/g, " ")} ·{" "}
                          {dataCurta(caso.criado_em)}
                        </span>
                      </button>
                    ))
                  )}
                </div>
              )}

              <div className={estilos.linhaDeEnvio}>
                <textarea
                  ref={campo}
                  className={`campo campo--area ${estilos.campoDaPergunta}`}
                  aria-label="Pergunta ao agente"
                  placeholder="Pergunte sobre um caso, sobre o acervo ou sobre o sistema… (# para um cliente)"
                  value={texto}
                  rows={1}
                  aria-expanded={mencao !== null}
                  onChange={(evento) => {
                    setTexto(evento.target.value);
                    sincronizarMencao(evento.target);
                  }}
                  onKeyUp={(evento) => sincronizarMencao(evento.currentTarget)}
                  onClick={(evento) => sincronizarMencao(evento.currentTarget)}
                  onBlur={() => setMencao(null)}
                  onKeyDown={(evento) => {
                    // Com a lista aberta, as teclas são DELA: seta anda pelos casos e
                    // Enter escolhe. Deixar o Enter enviar aqui mandaria a pergunta com o
                    // nome pela metade, que é exatamente o que o atalho existe para evitar.
                    if (mencao && candidatos.length > 0) {
                      if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
                        evento.preventDefault();
                        const passo = evento.key === "ArrowDown" ? 1 : -1;
                        setIndiceDoAtalho(
                          (atual) =>
                            (atual + passo + candidatos.length) % candidatos.length,
                        );
                        return;
                      }
                      if (evento.key === "Enter" || evento.key === "Tab") {
                        evento.preventDefault();
                        escolherNoAtalho(candidatos[indiceDoAtalho]);
                        return;
                      }
                    }
                    if (mencao && evento.key === "Escape") {
                      evento.preventDefault();
                      setMencao(null);
                      return;
                    }
                    // Enter envia, Shift+Enter quebra linha — o hábito de qualquer chat.
                    if (evento.key === "Enter" && !evento.shiftKey) {
                      evento.preventDefault();
                      void enviar(texto, casoAmarrado?.id);
                    }
                  }}
                />
                <button
                  type="button"
                  className={`botao botao--primario ${estilos.enviar}`}
                  onClick={() => void enviar(texto, casoAmarrado?.id)}
                  disabled={carregando || !texto.trim()}
                  aria-label="Enviar pergunta"
                >
                  ↑
                </button>
              </div>
            </div>

            <p className={estilos.rodape}>
              {casoAmarrado ? (
                <>
                  <span className={estilos.mencaoAtiva}>
                    Sobre {casoAmarrado.cliente}
                    <button
                      type="button"
                      className={estilos.soltarMencao}
                      onClick={() => setCasoDaMencao(null)}
                      aria-label="Perguntar sem amarrar a este caso"
                      title="Perguntar sem amarrar a este caso"
                    >
                      ×
                    </button>
                  </span>{" "}
                  A pergunta vai para este caso, sem depender de como o nome foi escrito.
                </>
              ) : (
                <>
                  Responde com o que o escritório registra, e mostra em que se apoiou.
                  Escreva <code>#</code> para escolher um cliente.
                </>
              )}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ histórico */

function ItemDoHistorico({
  conversa,
  aberta,
  aConfirmar,
  aoAbrir,
  aoPedirExclusao,
  aoCancelar,
  aoApagar,
}: {
  conversa: ResumoDeConversa;
  aberta: boolean;
  aConfirmar: boolean;
  aoAbrir: () => void;
  aoPedirExclusao: () => void;
  aoCancelar: () => void;
  aoApagar: () => void;
}) {
  if (aConfirmar) {
    return (
      <div className={`${estilos.item} ${estilos.itemAConfirmar}`}>
        <span className={estilos.perguntaDeExclusao}>Apagar esta conversa?</span>
        <div className={estilos.acoesDaExclusao}>
          <button type="button" className="botao botao--perigo botao--pequeno" onClick={aoApagar}>
            Apagar
          </button>
          <button
            type="button"
            className="botao botao--secundario botao--pequeno"
            onClick={aoCancelar}
          >
            Manter
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`${estilos.item} ${aberta ? estilos.itemAberto : ""}`}>
      <button type="button" className={estilos.abrirItem} onClick={aoAbrir}>
        <span className={estilos.tituloDoItem}>{conversa.titulo}</span>
        <span className={estilos.contextoDoItem}>
          {conversa.resumo ? `${conversa.resumo} · ` : ""}
          {horaOuData(conversa.atualizadoEm)}
        </span>
      </button>
      <button
        type="button"
        className={estilos.apagarItem}
        onClick={aoPedirExclusao}
        aria-label={`Apagar a conversa "${conversa.titulo}"`}
        title="Apagar"
      >
        ✕
      </button>
    </div>
  );
}

/* -------------------------------------------------------------------- resposta */

function Resposta({
  mensagem,
  onAbrirCaso,
  aoEscolherCaso,
}: {
  mensagem: MensagemDaConversa;
  onAbrirCaso: (casoId: string) => void;
  aoEscolherCaso: (casoId: string) => void;
}) {
  return (
    <div className={estilos.blocoDaResposta}>
      <div className={estilos.avatar} aria-hidden>
        <IconeConversa />
      </div>
      <div className={estilos.corpoDaResposta}>
        {/* O selo vem ANTES do texto, e não depois: quem lê precisa saber o que está
          * lendo antes de ler — explicação de produto e dado de caso apurado não podem
          * chegar com o mesmo peso. */}
        {mensagem.natureza === "SISTEMA" && (
          <div className={estilos.marcador}>
            <Selo tom="neutro">Sobre o sistema</Selo>
            {mensagem.tituloDoVerbete && (
              <span className={estilos.tituloDoVerbete}>{mensagem.tituloDoVerbete}</span>
            )}
          </div>
        )}

        {mensagem.natureza === "CASO" && mensagem.cliente && (
          <div className={estilos.marcador}>
            <Selo tom="info" simbolo="•">
              {mensagem.cliente}
            </Selo>
            {mensagem.casoId && (
              <button
                type="button"
                className="botao botao--texto"
                onClick={() => onAbrirCaso(mensagem.casoId as string)}
              >
                Abrir o caso →
              </button>
            )}
          </div>
        )}

        {/* O analista se anuncia: a resposta dele NÃO vem do agente jurídico nem de um
          * texto escrito à mão — foi medida agora, neste sistema, pelas consultas que
          * aparecem logo abaixo. Sem o selo, ela chegaria com a mesma cara de uma
          * explicação de produto, e as duas valem coisas diferentes. */}
        {mensagem.natureza === "ANALISE" && (
          <div className={estilos.marcador}>
            <Selo tom="info" simbolo="~">
              Analisado agora
            </Selo>
          </div>
        )}

        {mensagem.natureza === "ACERVO" ? (
          <Aviso tom="atencao" titulo="Esta eu ainda não sei responder">
            <span className={estilos.textoDaRecusa}>{mensagem.conteudo}</span>
          </Aviso>
        ) : mensagem.natureza === "INDISPONIVEL" ? (
          <Aviso tom="critico" titulo="O agente não respondeu">
            <span className={estilos.textoDaRecusa}>{mensagem.conteudo}</span>
          </Aviso>
        ) : (
          <p className={estilos.textoDaResposta}>{mensagem.conteudo}</p>
        )}

        {mensagem.falta.length > 0 && (
          <div className={estilos.oQueFalta}>
            <span className={estilos.rotuloDoQueFalta}>O que falta para isto funcionar</span>
            <ul className={estilos.itensDoQueFalta}>
              {mensagem.falta.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        {mensagem.candidatos.length > 0 && (
          <div className={estilos.candidatos}>
            {mensagem.candidatos.map((candidato) => (
              <button
                key={candidato.casoId}
                type="button"
                className={estilos.candidato}
                onClick={() => aoEscolherCaso(candidato.casoId)}
              >
                <span className={estilos.clienteDoCandidato}>{candidato.cliente}</span>
                {/* A categoria e a data são o que distingue dois casos do mesmo cliente —
                  * sem elas, a escolha seria um clique no escuro. */}
                <span className={estilos.detalheDoCandidato}>
                  {[
                    candidato.categoria,
                    dataCurta(candidato.criadoEm),
                    candidato.desempate && `nº ${candidato.desempate}`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </button>
            ))}
          </div>
        )}

        <LastroDaResposta
          afirmacoes={mensagem.afirmacoes}
          pendencias={mensagem.pendencias}
          rotuloDaReferencia="abrir no dossiê"
          // Duas origens, dois jeitos de seguir a referência. A do agente jurídico aponta
          // para um fato DENTRO do caso da conversa; a do analista aponta para o caso, e
          // pode citar vários numa resposta só — seguir sempre o caso da mensagem levaria
          // ao caso errado.
          aoAbrirReferencia={
            mensagem.natureza === "ANALISE"
              ? (referencia) => {
                  if (referencia.startsWith("caso:")) onAbrirCaso(referencia.slice(5));
                }
              : mensagem.casoId
                ? () => onAbrirCaso(mensagem.casoId as string)
                : undefined
          }
          referenciaNavegavel={(referencia) =>
            mensagem.natureza !== "ANALISE" || referencia.startsWith("caso:")
          }
        />

        {mensagem.consultas.length > 0 && <ComoChegouAqui consultas={mensagem.consultas} />}

        {mensagem.natureza === "SISTEMA" && (
          <p className={estilos.notaDoSistema}>
            Explicação do próprio sistema — não é uma consulta ao acervo.
          </p>
        )}
      </div>
    </div>
  );
}

/* O caminho que a resposta percorreu, recolhido.
 *
 * Fechado por padrão porque a resposta é o que se lê; o caminho é o que se confere quando
 * ela surpreende. Mas ele PRECISA estar ali: uma leitura crítica do acervo é
 * indistinguível de um palpite bem escrito, e a diferença entre as duas é justamente
 * poder ver que consultas a sustentam. */
function ComoChegouAqui({ consultas }: { consultas: ConsultaDoAnalista[] }) {
  const nomes: Record<string, string> = {
    panorama_do_escritorio: "Panorama do escritório",
    listar_casos: "Busca de casos",
    dossie_do_caso: "Dossiê do caso",
    documentos_do_caso: "Documentos do caso",
    entrevistas_do_caso: "Entrevistas do caso",
    jurimetria_do_acervo: "Jurimetria do acervo",
    glossario_do_sistema: "Glossário do sistema",
  };

  return (
    <details className={estilos.comoCheguei}>
      <summary className={estilos.resumoDoCaminho}>
        Como cheguei nisso · {consultas.length} consulta{consultas.length > 1 ? "s" : ""}
      </summary>
      <ol className={estilos.listaDoCaminho}>
        {consultas.map((consulta, indice) => {
          const argumentos = Object.entries(consulta.argumentos)
            .filter(([, valor]) => valor !== "" && valor !== null && valor !== undefined)
            .map(([chave, valor]) => `${chave}: ${String(valor).slice(0, 40)}`)
            .join(", ");
          return (
            <li key={`${consulta.ferramenta}-${indice}`} className={estilos.passoDoCaminho}>
              <span className={estilos.nomeDaConsulta}>
                {nomes[consulta.ferramenta] ?? consulta.ferramenta}
              </span>
              {argumentos && <span className={estilos.argumentosDaConsulta}>{argumentos}</span>}
            </li>
          );
        })}
      </ol>
    </details>
  );
}

function Abertura({ aoSugerir }: { aoSugerir: (sugestao: string) => void }) {
  return (
    <div className={estilos.abertura}>
      <h1 className={estilos.tituloDaAbertura}>Em que posso ajudar?</h1>
      <p className={estilos.textoDaAbertura}>
        Cite o cliente pelo nome e eu respondo sobre o caso dele, com a origem de cada
        afirmação. Também explico como o sistema funciona.
      </p>
      <div className={estilos.sugestoes}>
        {SUGESTOES.map((sugestao) => (
          <button
            key={sugestao}
            type="button"
            className={estilos.sugestao}
            onClick={() => aoSugerir(sugestao)}
          >
            {sugestao}
          </button>
        ))}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------- datas */

interface GrupoDeConversas {
  titulo: string;
  conversas: ResumoDeConversa[];
}

/** Agrupa como qualquer histórico de chat: Hoje, Ontem, Semana passada, Mais antigas.
 *
 * Por dia de calendário, e não por "24 horas atrás": às 9h de terça, a conversa das 22h de
 * segunda é de ontem, e não de hoje. */
function agrupar(conversas: ResumoDeConversa[]): GrupoDeConversas[] {
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const inicioDeHoje = hoje.getTime();
  const dia = 86_400_000;

  const grupos: GrupoDeConversas[] = [
    { titulo: "Hoje", conversas: [] },
    { titulo: "Ontem", conversas: [] },
    { titulo: "Semana passada", conversas: [] },
    { titulo: "Mais antigas", conversas: [] },
  ];

  for (const conversa of conversas) {
    const quando = new Date(conversa.atualizadoEm).getTime();
    if (Number.isNaN(quando)) {
      grupos[3].conversas.push(conversa);
    } else if (quando >= inicioDeHoje) {
      grupos[0].conversas.push(conversa);
    } else if (quando >= inicioDeHoje - dia) {
      grupos[1].conversas.push(conversa);
    } else if (quando >= inicioDeHoje - 7 * dia) {
      grupos[2].conversas.push(conversa);
    } else {
      grupos[3].conversas.push(conversa);
    }
  }

  return grupos.filter((grupo) => grupo.conversas.length > 0);
}

/** Hora para o que é de hoje, data para o resto — como no desenho ("14:20", "18/08"). */
function horaOuData(iso: string): string {
  const quando = new Date(iso);
  if (Number.isNaN(quando.getTime())) return "";

  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  if (quando.getTime() >= hoje.getTime()) {
    return quando.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  return quando.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

/** Dia, mês e hora da abertura, no fuso de quem lê.
 *
 * O ano ficaria de fora por ser ruído — mas a hora entra: dois casos do mesmo cliente
 * abertos no mesmo dia são o motivo de esta lista existir, e sem ela as duas linhas
 * ficariam idênticas. O servidor manda o instante em UTC justamente para a conversão
 * acontecer aqui, onde se sabe o fuso. */
function dataCurta(iso: string): string {
  const quando = new Date(iso);
  if (Number.isNaN(quando.getTime())) return "";
  return quando.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function iniciaisDe(nome: string): string {
  const pedacos = nome.trim().split(/\s+/).filter(Boolean);
  if (pedacos.length === 0) return "··";
  if (pedacos.length === 1) return pedacos[0].slice(0, 2).toUpperCase();
  return (pedacos[0][0] + pedacos[pedacos.length - 1][0]).toUpperCase();
}

/* --------------------------------------------------------------------- ícones */

function IconeConversa() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function IconeMais() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
  );
}

function IconeLupa() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}
