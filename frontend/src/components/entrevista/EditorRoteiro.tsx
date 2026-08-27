"use client";

/**
 * Editar o roteiro DURANTE o atendimento.
 *
 * O roteiro do escritório foi escrito para um tipo de causa. No meio de uma
 * conversa aparece o caso que ele não previu — a pergunta que não faz sentido
 * para este cliente, a que faltou, a opção que ninguém lembrou de listar. Até
 * aqui a saída era anotar à parte e corrigir o código depois; o atendimento
 * seguia com o roteiro errado na tela.
 *
 * O que este painel faz é deixar o advogado corrigir na hora, sem perder a
 * conversa: ele abre POR CIMA da entrevista, e o que já foi respondido continua
 * intacto atrás — as respostas são guardadas por `id` de pergunta, então mudar o
 * enunciado de uma pergunta não apaga a resposta dela.
 *
 * DUAS SAÍDAS, e a diferença importa:
 *
 *     "Usar neste atendimento"  vale só para esta sessão, não grava nada
 *     "Salvar no catálogo"      vira o roteiro do escritório, para todo mundo
 *
 * Sem essa separação, consertar uma pergunta para um cliente específico mudaria
 * o roteiro de todos os atendimentos seguintes — que é o contrário do que quem
 * está no meio de uma entrevista quer.
 */

import { useState } from "react";

import { salvarRoteiro } from "@/lib/api";
import type { Bloco, Pergunta, RoteiroCompleto, TipoResposta } from "@/lib/types";

const T_BOTAO =
  "border-[1.5px] border-tinta bg-transparent text-tinta text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-[14px] py-[10px] cursor-pointer disabled:opacity-40 disabled:cursor-default " +
  "enabled:hover:bg-tinta enabled:hover:text-papel";
const T_SECUNDARIO =
  "border border-borda-forte bg-transparent text-tinta text-[10px] font-semibold leading-none font-ui " +
  "tracking-[0.08em] uppercase px-3 py-[9px] cursor-pointer enabled:hover:bg-papel-2";
const T_MINI =
  "border border-borda bg-transparent text-tinta-3 text-[10px] font-semibold leading-none font-ui " +
  "px-2 py-[5px] cursor-pointer hover:bg-papel-2 hover:text-tinta disabled:opacity-30 disabled:cursor-default";
const T_ERRO =
  "border-[1.5px] border-critico text-critico p-[10px] font-normal text-[12px] leading-[1.5] font-ui";
const T_ROTULO =
  "block text-[10px] font-semibold tracking-[0.08em] uppercase font-ui text-tinta-3 mb-[3px]";
const T_CAMPO =
  "w-full border border-borda bg-papel text-tinta text-[13px] leading-[1.45] font-ui px-2 py-[6px] " +
  "focus:outline-none focus:border-tinta";

const TIPOS: { valor: TipoResposta; rotulo: string }[] = [
  { valor: "dado", rotulo: "Dado digitado" },
  { valor: "data", rotulo: "Data" },
  { valor: "sim_nao", rotulo: "Sim ou não" },
  { valor: "escolha", rotulo: "Escolha (botões)" },
  { valor: "lista", rotulo: "Lista (seletor)" },
  { valor: "documentos", rotulo: "Documentos" },
  { valor: "relato", rotulo: "Relato (gravador)" },
];

const PRECISA_DE_OPCOES: TipoResposta[] = ["escolha", "lista"];

function perguntaNova(): Pergunta {
  return {
    // Vazio de propósito: o backend gera o id a partir do enunciado, e um id
    // inventado aqui sobreviveria como "p_2" no meio de ids que dizem algo.
    id: "",
    texto: "",
    tipo: "relato",
    transcrever: true,
    opcoes: [],
    dica: "",
    obrigatoria: false,
    validacao: "",
    busca: "",
    preenche: "",
    depende_de: "",
    depende_valor: "",
    fala: {},
    impedimento: "",
  };
}

function blocoNovo(): Bloco {
  return {
    id: "",
    titulo: "",
    perguntas: [perguntaNova()],
    modulo: null,
    objetivo: "",
    abertura: "",
    instrucao: "",
    delegado_a: "",
  };
}

/** Troca dois itens de lugar, devolvendo uma lista nova. */
function mover<T>(itens: T[], de: number, para: number): T[] {
  if (para < 0 || para >= itens.length) return itens;
  const copia = [...itens];
  [copia[de], copia[para]] = [copia[para], copia[de]];
  return copia;
}

interface Props {
  roteiro: RoteiroCompleto;
  /** De onde ele veio, quando veio de um arquivo. Vai junto ao salvar. */
  origem?: string;
  /** Aplica o roteiro editado só nesta sessão. */
  aoUsar: (roteiro: RoteiroCompleto) => void;
  /** Gravado no catálogo: o servidor devolve a versão canônica, já validada. */
  aoSalvar?: (roteiro: RoteiroCompleto) => void;
  aoFechar: () => void;
}

export default function EditorRoteiro({ roteiro, origem = "", aoUsar, aoSalvar, aoFechar }: Props) {
  const [rascunho, setRascunho] = useState<RoteiroCompleto>(roteiro);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [abertos, setAbertos] = useState<string[]>([]);

  function alterar(campos: Partial<RoteiroCompleto>) {
    setRascunho((atual) => ({ ...atual, ...campos }));
    setErro(null);
  }

  function alterarBloco(indice: number, campos: Partial<Bloco>) {
    setRascunho((atual) => ({
      ...atual,
      blocos: atual.blocos.map((b, i) => (i === indice ? { ...b, ...campos } : b)),
    }));
    setErro(null);
  }

  function alterarPergunta(iBloco: number, iPergunta: number, campos: Partial<Pergunta>) {
    setRascunho((atual) => ({
      ...atual,
      blocos: atual.blocos.map((b, i) =>
        i !== iBloco
          ? b
          : {
              ...b,
              perguntas: b.perguntas.map((p, j) => (j === iPergunta ? { ...p, ...campos } : p)),
            },
      ),
    }));
    setErro(null);
  }

  /* A regra do gravador é do roteiro, não do editor: quem CONTA é relato, quem
   * INFORMA é campo digitado. Trocar o tipo reposiciona o gravador sozinho — mas
   * a caixa continua lá para o caso raro em que o advogado quer o contrário. */
  function trocarTipo(iBloco: number, iPergunta: number, tipo: TipoResposta) {
    alterarPergunta(iBloco, iPergunta, {
      tipo,
      transcrever: tipo === "relato",
      opcoes: PRECISA_DE_OPCOES.includes(tipo)
        ? rascunho.blocos[iBloco].perguntas[iPergunta].opcoes
        : [],
    });
  }

  const perguntasDisponiveis = rascunho.blocos.flatMap((b) =>
    b.perguntas.filter((p) => p.id && p.tipo === "sim_nao").map((p) => ({ id: p.id, texto: p.texto })),
  );

  async function gravarNoCatalogo() {
    setSalvando(true);
    setErro(null);
    try {
      const salvo = await salvarRoteiro(rascunho, origem);
      aoSalvar?.(salvo);
      aoFechar();
    } catch (e) {
      // O 422 do backend traz a frase exata ("A pergunta X é de escolha e não
      // tem nenhuma opção"). Mostrar isso é mais útil que "erro ao salvar".
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setSalvando(false);
    }
  }

  const totalPerguntas = rascunho.blocos.reduce((soma, b) => soma + b.perguntas.length, 0);

  return (
    <div
      className="fixed inset-0 z-50 bg-tinta/40 flex items-start justify-center overflow-y-auto p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Editar o roteiro"
    >
      <div className="w-full max-w-[900px] bg-papel border border-borda-forte my-4">
        <div className="sticky top-0 z-10 bg-papel flex justify-between items-center gap-4 flex-wrap px-4 py-3 border-b border-borda-forte">
          <div>
            <h2 className="m-0 font-semibold text-[19px] leading-[1.15] font-titulo">
              Editar o roteiro
            </h2>
            <p className="m-0 mt-[3px] text-[11.5px] leading-[1.4] font-ui text-tinta-3">
              {rascunho.blocos.length} blocos · {totalPerguntas} perguntas
              {origem ? ` · de ${origem}` : ""}
            </p>
          </div>
          <div className="flex gap-[10px] items-center flex-wrap">
            <button type="button" className={T_SECUNDARIO} onClick={aoFechar} disabled={salvando}>
              Cancelar
            </button>
            {/* Primeiro botão porque é o caso comum no meio de um atendimento:
                consertar para ESTE cliente sem mexer no roteiro de todos. */}
            <button
              type="button"
              className={T_SECUNDARIO}
              onClick={() => {
                aoUsar(rascunho);
                aoFechar();
              }}
              disabled={salvando}
            >
              Usar neste atendimento
            </button>
            <button
              type="button"
              className={T_BOTAO}
              onClick={() => void gravarNoCatalogo()}
              disabled={salvando}
            >
              {salvando ? "Salvando…" : "Salvar no catálogo"}
            </button>
          </div>
        </div>

        <div className="px-4 py-4">
          {erro && <div className={`${T_ERRO} mb-4`}>{erro}</div>}

          <div className="grid gap-3 sm:grid-cols-2 mb-5">
            <label className="block">
              <span className={T_ROTULO}>Nome do roteiro</span>
              <input
                className={T_CAMPO}
                value={rascunho.nome}
                onChange={(e) => alterar({ nome: e.target.value })}
              />
            </label>
            <label className="block">
              <span className={T_ROTULO}>Descrição</span>
              <input
                className={T_CAMPO}
                value={rascunho.descricao}
                onChange={(e) => alterar({ descricao: e.target.value })}
              />
            </label>
          </div>

          <Paragrafos
            rotulo="Saudação — lida em voz alta antes da primeira pergunta"
            valores={rascunho.saudacao}
            aoMudar={(saudacao) => alterar({ saudacao })}
          />
          <Paragrafos
            rotulo="Encerramento — lido depois da última"
            valores={rascunho.encerramento}
            aoMudar={(encerramento) => alterar({ encerramento })}
          />

          <div className="mt-6 pt-4 border-t border-borda-forte">
            {rascunho.blocos.map((bloco, iBloco) => {
              const chave = `bloco-${iBloco}`;
              const aberto = abertos.includes(chave);
              return (
                <div key={chave} className="mb-3 border border-borda bg-papel-2">
                  <div className="flex justify-between items-center gap-3 px-3 py-[10px]">
                    <button
                      type="button"
                      className="flex-1 text-left bg-transparent border-0 cursor-pointer p-0"
                      onClick={() =>
                        setAbertos((a) =>
                          a.includes(chave) ? a.filter((x) => x !== chave) : [...a, chave],
                        )
                      }
                    >
                      <span className="font-semibold text-[14px] font-titulo text-tinta">
                        {aberto ? "▾" : "▸"} {bloco.titulo || "(bloco sem título)"}
                      </span>
                      <span className="ml-2 text-[11px] font-ui text-tinta-3">
                        {bloco.perguntas.length} perguntas
                        {bloco.modulo ? ` · só com rastreio “${bloco.modulo}”` : ""}
                      </span>
                    </button>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        className={T_MINI}
                        title="Subir bloco"
                        disabled={iBloco === 0}
                        onClick={() =>
                          alterar({ blocos: mover(rascunho.blocos, iBloco, iBloco - 1) })
                        }
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className={T_MINI}
                        title="Descer bloco"
                        disabled={iBloco === rascunho.blocos.length - 1}
                        onClick={() =>
                          alterar({ blocos: mover(rascunho.blocos, iBloco, iBloco + 1) })
                        }
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        className={T_MINI}
                        title="Remover bloco"
                        onClick={() =>
                          alterar({ blocos: rascunho.blocos.filter((_, i) => i !== iBloco) })
                        }
                      >
                        Remover
                      </button>
                    </div>
                  </div>

                  {aberto && (
                    <div className="px-3 pb-3 border-t border-borda">
                      <div className="grid gap-3 sm:grid-cols-2 my-3">
                        <label className="block">
                          <span className={T_ROTULO}>Título</span>
                          <input
                            className={T_CAMPO}
                            value={bloco.titulo}
                            onChange={(e) => alterarBloco(iBloco, { titulo: e.target.value })}
                          />
                        </label>
                        <label className="block">
                          <span className={T_ROTULO}>
                            Módulo — vazio = sempre visível
                          </span>
                          <input
                            className={T_CAMPO}
                            value={bloco.modulo ?? ""}
                            onChange={(e) =>
                              alterarBloco(iBloco, { modulo: e.target.value.trim() || null })
                            }
                          />
                        </label>
                        <label className="block sm:col-span-2">
                          <span className={T_ROTULO}>
                            Abertura — LIDA em voz alta ao entrar no bloco
                          </span>
                          <textarea
                            className={`${T_CAMPO} min-h-[54px]`}
                            value={bloco.abertura}
                            onChange={(e) => alterarBloco(iBloco, { abertura: e.target.value })}
                          />
                        </label>
                        <label className="block sm:col-span-2">
                          <span className={T_ROTULO}>
                            Instrução — orientação interna, NUNCA lida ao cliente
                          </span>
                          <textarea
                            className={`${T_CAMPO} min-h-[54px]`}
                            value={bloco.instrucao}
                            onChange={(e) => alterarBloco(iBloco, { instrucao: e.target.value })}
                          />
                        </label>
                      </div>

                      {bloco.perguntas.map((pergunta, iPergunta) => (
                        <EditorPergunta
                          key={`${chave}-p-${iPergunta}`}
                          pergunta={pergunta}
                          posicao={iPergunta}
                          total={bloco.perguntas.length}
                          candidatasPai={perguntasDisponiveis.filter((c) => c.id !== pergunta.id)}
                          aoAlterar={(campos) => alterarPergunta(iBloco, iPergunta, campos)}
                          aoTrocarTipo={(tipo) => trocarTipo(iBloco, iPergunta, tipo)}
                          aoMover={(destino) =>
                            alterarBloco(iBloco, {
                              perguntas: mover(bloco.perguntas, iPergunta, destino),
                            })
                          }
                          aoRemover={() =>
                            alterarBloco(iBloco, {
                              perguntas: bloco.perguntas.filter((_, j) => j !== iPergunta),
                            })
                          }
                        />
                      ))}

                      <button
                        type="button"
                        className={T_SECUNDARIO}
                        onClick={() =>
                          alterarBloco(iBloco, { perguntas: [...bloco.perguntas, perguntaNova()] })
                        }
                      >
                        + Pergunta
                      </button>
                    </div>
                  )}
                </div>
              );
            })}

            <button
              type="button"
              className={T_SECUNDARIO}
              onClick={() => {
                alterar({ blocos: [...rascunho.blocos, blocoNovo()] });
                setAbertos((a) => [...a, `bloco-${rascunho.blocos.length}`]);
              }}
            >
              + Bloco
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ uma pergunta */

interface PropsPergunta {
  pergunta: Pergunta;
  posicao: number;
  total: number;
  /** Perguntas de sim/não que podem condicionar esta. */
  candidatasPai: { id: string; texto: string }[];
  aoAlterar: (campos: Partial<Pergunta>) => void;
  aoTrocarTipo: (tipo: TipoResposta) => void;
  aoMover: (destino: number) => void;
  aoRemover: () => void;
}

function EditorPergunta({
  pergunta,
  posicao,
  total,
  candidatasPai,
  aoAlterar,
  aoTrocarTipo,
  aoMover,
  aoRemover,
}: PropsPergunta) {
  const precisaDeOpcoes = PRECISA_DE_OPCOES.includes(pergunta.tipo);

  return (
    <div className="mb-2 border border-borda bg-papel p-3">
      <div className="flex gap-2 items-start">
        <textarea
          className={`${T_CAMPO} min-h-[42px] flex-1`}
          placeholder="Enunciado da pergunta, como ela é feita ao cliente"
          value={pergunta.texto}
          onChange={(e) => aoAlterar({ texto: e.target.value })}
        />
        <div className="flex flex-col gap-1">
          <button
            type="button"
            className={T_MINI}
            title="Subir"
            disabled={posicao === 0}
            onClick={() => aoMover(posicao - 1)}
          >
            ↑
          </button>
          <button
            type="button"
            className={T_MINI}
            title="Descer"
            disabled={posicao === total - 1}
            onClick={() => aoMover(posicao + 1)}
          >
            ↓
          </button>
          <button type="button" className={T_MINI} title="Remover pergunta" onClick={aoRemover}>
            ✕
          </button>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-3 mt-2">
        <label className="block">
          <span className={T_ROTULO}>Tipo de resposta</span>
          <select
            className={T_CAMPO}
            value={pergunta.tipo}
            onChange={(e) => aoTrocarTipo(e.target.value as TipoResposta)}
          >
            {TIPOS.map((t) => (
              <option key={t.valor} value={t.valor}>
                {t.rotulo}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className={T_ROTULO}>Conferência</span>
          <select
            className={T_CAMPO}
            value={pergunta.validacao}
            onChange={(e) => aoAlterar({ validacao: e.target.value as Pergunta["validacao"] })}
          >
            <option value="">Nenhuma</option>
            <option value="cpf">Dígito do CPF</option>
          </select>
        </label>
        <label className="block">
          <span className={T_ROTULO}>Preenchida por</span>
          <select
            className={T_CAMPO}
            value={pergunta.busca}
            onChange={(e) => aoAlterar({ busca: e.target.value as Pergunta["busca"] })}
          >
            <option value="">Digitação</option>
            <option value="cep">Busca de CEP</option>
          </select>
        </label>
      </div>

      {precisaDeOpcoes && (
        <label className="block mt-2">
          <span className={T_ROTULO}>Opções — uma por linha</span>
          <textarea
            className={`${T_CAMPO} min-h-[64px]`}
            value={pergunta.opcoes.join("\n")}
            onChange={(e) =>
              aoAlterar({
                opcoes: e.target.value
                  .split("\n")
                  .map((o) => o.trim())
                  .filter(Boolean),
              })
            }
          />
        </label>
      )}

      <label className="block mt-2">
        <span className={T_ROTULO}>Dica — orientação interna, não lida ao cliente</span>
        <input
          className={T_CAMPO}
          value={pergunta.dica}
          onChange={(e) => aoAlterar({ dica: e.target.value })}
        />
      </label>

      {/* Só aparece quando existe uma pergunta de sim/não para ser o pai: sem
          candidata, o campo seria um seletor vazio pedindo o impossível. */}
      {candidatasPai.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2 mt-2">
          <label className="block">
            <span className={T_ROTULO}>Só perguntar depois de</span>
            <select
              className={T_CAMPO}
              value={pergunta.depende_de}
              onChange={(e) =>
                aoAlterar({
                  depende_de: e.target.value,
                  depende_valor: e.target.value ? pergunta.depende_valor || "sim" : "",
                })
              }
            >
              <option value="">Sempre perguntar</option>
              {candidatasPai.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.texto.slice(0, 60)}
                </option>
              ))}
            </select>
          </label>
          {pergunta.depende_de && (
            <label className="block">
              <span className={T_ROTULO}>…quando a resposta for</span>
              <select
                className={T_CAMPO}
                value={pergunta.depende_valor}
                onChange={(e) => aoAlterar({ depende_valor: e.target.value })}
              >
                <option value="sim">sim</option>
                <option value="não">não</option>
              </select>
            </label>
          )}
        </div>
      )}

      <div className="flex gap-4 flex-wrap mt-2 text-[11.5px] font-ui text-tinta">
        <label className="flex gap-[6px] items-center cursor-pointer">
          <input
            type="checkbox"
            checked={pergunta.obrigatoria}
            onChange={(e) => aoAlterar({ obrigatoria: e.target.checked })}
          />
          Obrigatória
        </label>
        <label className="flex gap-[6px] items-center cursor-pointer">
          <input
            type="checkbox"
            checked={pergunta.transcrever}
            onChange={(e) => aoAlterar({ transcrever: e.target.checked })}
          />
          Abre o gravador
        </label>
        <label className="flex gap-[6px] items-center cursor-pointer">
          <input
            type="checkbox"
            checked={Boolean(pergunta.impedimento)}
            onChange={(e) => aoAlterar({ impedimento: e.target.checked ? "sim" : "" })}
          />
          Responder “sim” impede o caso
        </label>
      </div>
    </div>
  );
}

/* -------------------------------------------- lista de parágrafos lidos */

function Paragrafos({
  rotulo,
  valores,
  aoMudar,
}: {
  rotulo: string;
  valores: string[];
  aoMudar: (valores: string[]) => void;
}) {
  return (
    <label className="block mt-3">
      <span className={T_ROTULO}>{rotulo} — um parágrafo por linha em branco</span>
      <textarea
        className={`${T_CAMPO} min-h-[72px]`}
        value={valores.join("\n\n")}
        onChange={(e) =>
          aoMudar(
            e.target.value
              .split(/\n\s*\n/)
              .map((p) => p.trim())
              .filter(Boolean),
          )
        }
      />
    </label>
  );
}
