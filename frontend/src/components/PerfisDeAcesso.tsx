"use client";

/**
 * Perfis de acesso: o que cada um alcança, módulo a módulo.
 *
 * POR QUE ESTA TELA EXISTE
 *
 * Os perfis eram três, cravados no código do servidor, e o motivo estava escrito
 * lá: papel novo sem código que o entenda vira acesso que ninguém sabe explicar.
 * A objeção era certa. Esta tela a resolve pelo outro lado — perfil novo nasce
 * declarando os módulos que alcança, e é essa declaração que as rotas conferem.
 *
 * A MATRIZ É O DOCUMENTO
 *
 * Uma linha por perfil, uma coluna por módulo, uma caixa em cada cruzamento. Não
 * é a forma mais bonita de mostrar isso, é a que permite responder de relance a
 * pergunta que se faz de verdade: "quem enxerga as entrevistas de todo mundo?".
 * Uma lista de perfis com um detalhe por vez esconderia justamente a comparação.
 *
 * NADA É SALVO SOZINHO
 *
 * Marcar caixa não grava. Cada linha guarda o que mudou e só vai ao servidor no
 * "Salvar" — porque desmarcar um módulo tira acesso de gente que está usando o
 * sistema neste momento, e isso não pode acontecer por um clique errado de quem
 * estava só olhando.
 *
 * E QUEM SÃO ESSAS PESSOAS APARECE ANTES
 *
 * A coluna de contas e o aviso de impacto existem porque a matriz sozinha mostra
 * o desenho do acesso e esconde quem depende dele. Retirar um módulo de um
 * perfil com quatro contas ativas é uma decisão sobre quatro pessoas, e quem
 * decide precisa ver isso na hora — não descobrir depois pelo suporte.
 */

import { useCallback, useEffect, useState } from "react";
import { History, ShieldCheck, UserRoundCog } from "lucide-react";

import {
  AjudaCampo,
  Aviso,
  Botao,
  Campo,
  Cartao,
  RotuloCampo,
  Selo,
  Tabela,
  Td,
  Th,
  TrZebra,
  Vazio,
} from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import {
  ApiError,
  listarHistoricoPerfis,
  listarMatrizPerfis,
  removerPerfil,
  salvarPerfil,
} from "@/lib/api";
import type {
  AlteracaoDePerfil,
  ModuloDeAcesso,
  PerfilComAcesso,
} from "@/lib/api";

/** O que a tela guarda de uma linha ainda não salva. */
interface Rascunho {
  rotulo: string;
  descricao: string;
  modulos: string[];
}

/** Código a partir do rótulo: minúsculas, sem acento, sem espaço.
 *
 * O código vai no claim `perfil` do token e é comparado como texto exato;
 * acento e espaço só criam jeito de errar. Gerar aqui evita pedir à pessoa um
 * dado técnico que ela não tem como saber que importa. */
function codigoDe(rotulo: string): string {
  return rotulo
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 60);
}

/** O módulo `agente` é ferramenta comum do escritório e o servidor o devolve
 *  marcado para todo perfil interno (ver `_liberar_agente_para_perfis_internos`).
 *  A caixa fica travada para a tela não oferecer uma escolha que não existe. */
function travado(perfil: PerfilComAcesso, modulo: ModuloDeAcesso): boolean {
  return modulo.codigo === "agente" && perfil.codigo !== "cliente";
}

function mesmaLista(a: string[], b: string[]): boolean {
  return a.length === b.length && [...a].sort().every((v, i) => v === [...b].sort()[i]);
}

/** Data legível. O servidor grava ISO em UTC; a tela mostra no fuso de quem lê. */
function quando(iso: string): string {
  const data = new Date(iso);
  return Number.isNaN(data.getTime())
    ? iso
    : data.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export default function PerfisDeAcesso() {
  const [perfis, setPerfis] = useState<PerfilComAcesso[]>([]);
  const [modulos, setModulos] = useState<ModuloDeAcesso[]>([]);
  const [historico, setHistorico] = useState<AlteracaoDePerfil[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [feito, setFeito] = useState<string | null>(null);
  const [salvando, setSalvando] = useState<string | null>(null);

  /* O que mudou desde a última leitura, por perfil. Só o que está aqui é
   * enviado — e é o que acende o botão "Salvar" de cada linha. */
  const [rascunhos, setRascunhos] = useState<Record<string, Rascunho>>({});
  /* Qual linha está com os campos de texto abertos. Um de cada vez: dois
   * formulários abertos na mesma matriz tiram da tela justamente a comparação
   * entre perfis, que é o motivo de a matriz existir. */
  const [editando, setEditando] = useState<string | null>(null);
  const [novoRotulo, setNovoRotulo] = useState("");

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const r = await listarMatrizPerfis();
      setPerfis(r.perfis);
      setModulos(r.modulos);
      setRascunhos({});
      setEditando(null);
      setErro(null);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível ler os perfis.");
    } finally {
      setCarregando(false);
    }
  }, []);

  const carregarHistorico = useCallback(async () => {
    /* Falhar aqui não derruba a matriz: o histórico é leitura de apoio, e sem
     * ele ainda se administra perfil. O silêncio é proposital — uma faixa de
     * erro para isto competiria com a que importa, a de salvar. */
    try {
      setHistorico(await listarHistoricoPerfis(20));
    } catch {
      setHistorico([]);
    }
  }, []);

  useEffect(() => {
    void carregar();
    void carregarHistorico();
  }, [carregar, carregarHistorico]);

  const rascunhoDe = (perfil: PerfilComAcesso): Rascunho =>
    rascunhos[perfil.codigo] ?? {
      rotulo: perfil.rotulo,
      descricao: perfil.descricao,
      modulos: perfil.modulos,
    };

  function mudou(perfil: PerfilComAcesso): boolean {
    const r = rascunhos[perfil.codigo];
    if (!r) return false;
    return (
      r.rotulo !== perfil.rotulo ||
      r.descricao !== perfil.descricao ||
      !mesmaLista(r.modulos, perfil.modulos)
    );
  }

  function ajustar(perfil: PerfilComAcesso, mudanca: Partial<Rascunho>) {
    setRascunhos((atual) => ({
      ...atual,
      [perfil.codigo]: { ...rascunhoDe(perfil), ...mudanca },
    }));
  }

  function alternar(perfil: PerfilComAcesso, modulo: string) {
    const atual = rascunhoDe(perfil).modulos;
    ajustar(perfil, {
      modulos: atual.includes(modulo)
        ? atual.filter((m) => m !== modulo)
        : [...atual, modulo],
    });
  }

  /** Os módulos que esta alteração RETIRA, com o rótulo que a pessoa vê. */
  function retirados(perfil: PerfilComAcesso): string[] {
    const marcados = rascunhoDe(perfil).modulos;
    return perfil.modulos
      .filter((codigo) => !marcados.includes(codigo))
      .map((codigo) => modulos.find((m) => m.codigo === codigo)?.rotulo ?? codigo);
  }

  async function salvar(perfil: PerfilComAcesso) {
    const rascunho = rascunhoDe(perfil);
    const perdidos = retirados(perfil);
    const contas = perfil.usuarios?.ativos ?? 0;

    /* A confirmação só aparece quando há gente para perder acesso. Pedir
     * confirmação de tudo ensina a clicar em "OK" sem ler, e aí ela deixa de
     * proteger exatamente o caso em que era necessária. */
    if (perdidos.length > 0 && contas > 0) {
      const texto =
        `Retirar ${perdidos.join(", ")} de "${perfil.rotulo}" tira esse acesso de ` +
        `${contas} conta(s) ativa(s), sem esperar novo login. Confirmar?`;
      if (!confirm(texto)) return;
    }

    setSalvando(perfil.codigo);
    setFeito(null);
    try {
      const r = await salvarPerfil(
        perfil.codigo,
        rascunho.rotulo.trim() || perfil.rotulo,
        rascunho.descricao,
        rascunho.modulos,
      );
      /* O servidor devolve o que ENTENDEU da alteração, e é isso que a tela
       * repete. Quando ele não gravou nada — porque nada mudou de fato — dizer
       * "salvo" seria mentira pequena e cara: some a diferença entre a
       * alteração que pegou e a que não pegou. */
      setFeito(
        r.alteracao
          ? `${perfil.rotulo}: ${r.alteracao.resumo}`
          : `${perfil.rotulo} continua como estava — nada a alterar.`,
      );
      await carregar();
      await carregarHistorico();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível salvar.");
    } finally {
      setSalvando(null);
    }
  }

  async function criar() {
    const rotulo = novoRotulo.trim();
    const codigo = codigoDe(rotulo);
    if (!codigo) return;
    setSalvando(codigo);
    setFeito(null);
    try {
      // Nasce sem módulo nenhum, de propósito: quem cria escolhe o que abrir, em
      // vez de sair fechando o que não devia ter vindo aberto.
      await salvarPerfil(codigo, rotulo, "", []);
      setNovoRotulo("");
      setFeito(`Perfil "${rotulo}" criado. Marque os módulos que ele alcança.`);
      await carregar();
      await carregarHistorico();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível criar o perfil.");
    } finally {
      setSalvando(null);
    }
  }

  async function remover(perfil: PerfilComAcesso) {
    if (!confirm(`Apagar o perfil "${perfil.rotulo}"?`)) return;
    setSalvando(perfil.codigo);
    setFeito(null);
    try {
      await removerPerfil(perfil.codigo);
      setFeito(`Perfil "${perfil.rotulo}" apagado.`);
      await carregar();
      await carregarHistorico();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível apagar.");
    } finally {
      setSalvando(null);
    }
  }

  return (
    <div className="min-w-0 space-y-5">
      <Cartao
        titulo={
          <span className="inline-flex min-w-0 items-center gap-2">
            <UserRoundCog size={18} className="text-acao" aria-hidden />
            <span className="truncate">Perfis de acesso</span>
          </span>
        }
        subtitulo="O que cada perfil alcança no sistema. Módulo desmarcado fica fora — quem tiver só esse perfil recebe recusa ao tentar entrar nele."
        className="min-w-0 overflow-hidden"
      >
        {(erro || feito) && (
          <div className="mb-4 space-y-3">
            {erro && (
              <Aviso tom="critico" titulo="Não deu para concluir">
                {erro}
              </Aviso>
            )}
            {feito && (
              <Aviso tom="ok" titulo="Alteração registrada">
                {feito}
              </Aviso>
            )}
          </div>
        )}

        {carregando ? (
          <p className="m-0 text-tinta-3">Carregando…</p>
        ) : perfis.length === 0 ? (
          <Vazio>Nenhum perfil cadastrado.</Vazio>
        ) : (
          <div className="max-w-full overflow-x-auto rounded-campo border border-borda">
            <Tabela className="min-w-[860px]">
              <thead>
                <tr>
                  <Th className="sticky left-0 z-[1] bg-papel-2">Perfil</Th>
                  <Th className="whitespace-nowrap">Contas</Th>
                  {modulos.map((m) => (
                    /* O `title` carrega a descrição: a coluna é estreita e o
                     * rótulo sozinho não diz o que "Entrevistas no geral" cobre. */
                    <Th
                      key={m.codigo}
                      title={m.descricao}
                      className="min-w-[132px] cursor-help text-center align-middle"
                    >
                      <span className="inline-block whitespace-normal leading-[1.3]">
                        {m.rotulo}
                      </span>
                    </Th>
                  ))}
                  <Th className="min-w-[150px] whitespace-nowrap text-right">Ação</Th>
                </tr>
              </thead>
              <tbody>
                {perfis.map((perfil) => {
                  const rascunho = rascunhoDe(perfil);
                  const alterado = mudou(perfil);
                  const perdidos = retirados(perfil);
                  const ativos = perfil.usuarios?.ativos ?? 0;
                  const emUso = (perfil.usuarios?.total ?? 0) > 0;

                  return (
                    <TrZebra key={perfil.codigo} className={alterado ? "bg-atencao-claro" : ""}>
                      <Td className="sticky left-0 z-[1] min-w-[240px] bg-inherit">
                        <strong className="block">{perfil.rotulo}</strong>
                        <span className="mt-[3px] block font-codigo text-xs text-tinta-3">
                          {perfil.codigo}
                        </span>
                        {perfil.sistema && (
                          <span className="mt-[5px] inline-block">
                            <Selo tom="neutro" simbolo="•">
                              sistema
                            </Selo>
                          </span>
                        )}
                        {perfil.descricao && (
                          <span className="mt-[5px] block text-xs leading-[1.45] text-tinta-3">
                            {perfil.descricao}
                          </span>
                        )}

                        {editando === perfil.codigo && (
                          <div className="mt-3 space-y-3 border-t border-borda pt-3">
                            <div>
                              <RotuloCampo>Rótulo</RotuloCampo>
                              <Campo
                                value={rascunho.rotulo}
                                maxLength={120}
                                onChange={(e) => ajustar(perfil, { rotulo: e.target.value })}
                              />
                              <AjudaCampo>
                                É o nome que aparece no cadastro de usuários. O código
                                (<code className="font-codigo">{perfil.codigo}</code>) não muda:
                                ele já está nas sessões abertas.
                              </AjudaCampo>
                            </div>
                            <div>
                              <RotuloCampo>Descrição</RotuloCampo>
                              <Campo
                                area
                                rows={3}
                                value={rascunho.descricao}
                                maxLength={400}
                                onChange={(e) => ajustar(perfil, { descricao: e.target.value })}
                              />
                            </div>
                          </div>
                        )}
                      </Td>

                      <Td className="whitespace-nowrap tabular-nums">
                        {emUso ? (
                          <Selo tom="info" simbolo="•">
                            {ativos} ativa(s)
                          </Selo>
                        ) : (
                          <span className="text-tinta-3">nenhuma</span>
                        )}
                      </Td>

                      {modulos.map((m) => (
                        <Td key={m.codigo} className="text-center">
                          <input
                            type="checkbox"
                            className="size-[17px] cursor-pointer accent-acao disabled:cursor-not-allowed"
                            checked={rascunho.modulos.includes(m.codigo)}
                            onChange={() => alternar(perfil, m.codigo)}
                            disabled={travado(perfil, m) || salvando === perfil.codigo}
                            title={
                              travado(perfil, m)
                                ? "Acesso padrão para toda a equipe do escritório"
                                : undefined
                            }
                            aria-label={`${perfil.rotulo} acessa ${m.rotulo}`}
                          />
                        </Td>
                      ))}

                      <Td className="min-w-[150px] whitespace-nowrap text-right">
                        <div className="flex flex-wrap justify-end gap-2">
                          <BotaoProcesso
                            pequeno
                            variante="secundario"
                            onClick={() =>
                              setEditando(editando === perfil.codigo ? null : perfil.codigo)
                            }
                            aguardando={salvando === perfil.codigo}
                          >
                            {editando === perfil.codigo ? "Fechar" : "Editar"}
                          </BotaoProcesso>
                          {alterado && (
                            <BotaoProcesso
                              pequeno
                              variante="primario"
                              onClick={() => salvar(perfil)}
                              textoProcessando="Salvando…"
                              aguardando={salvando === perfil.codigo}
                            >
                              Salvar
                            </BotaoProcesso>
                          )}
                          {/* Perfil de sistema não some: um Acervo sem ninguém capaz
                            * de administrar usuários só se conserta no banco, à mão.
                            * Perfil em uso também não — o servidor recusa, e esconder
                            * o botão evita oferecer o que vai dar erro. */}
                          {!perfil.sistema && !alterado && !emUso && (
                            <BotaoProcesso
                              pequeno
                              variante="secundario"
                              onClick={() => remover(perfil)}
                              textoProcessando="Apagando…"
                              aguardando={salvando === perfil.codigo}
                            >
                              Apagar
                            </BotaoProcesso>
                          )}
                        </div>

                        {alterado && perdidos.length > 0 && ativos > 0 && (
                          <div className="mt-2 text-left text-xs leading-[1.45] text-atencao">
                            Tira {perdidos.join(", ")} de {ativos} conta(s) ativa(s).
                          </div>
                        )}
                      </Td>
                    </TrZebra>
                  );
                })}
              </tbody>
            </Tabela>
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-end gap-3">
          <div className="min-w-[260px]">
            <RotuloCampo>Novo perfil</RotuloCampo>
            <Campo
              value={novoRotulo}
              onChange={(e) => setNovoRotulo(e.target.value)}
              placeholder="Analista, Estagiário, Financeiro…"
              maxLength={120}
            />
            {novoRotulo.trim() && (
              <AjudaCampo>
                código: <code className="font-codigo text-tinta">{codigoDe(novoRotulo)}</code>
              </AjudaCampo>
            )}
          </div>
          <BotaoProcesso
            variante="primario"
            onClick={() => criar()}
            textoProcessando="Criando o perfil…"
            pendencia={novoRotulo.trim() ? null : "Digite ao lado o nome do novo perfil."}
            pendenciaAoClicar
            aguardando={salvando !== null}
          >
            <ShieldCheck size={16} aria-hidden />
            Criar perfil
          </BotaoProcesso>
        </div>
      </Cartao>

      <Cartao
        titulo={
          <span className="inline-flex min-w-0 items-center gap-2">
            <History size={18} className="text-acao" aria-hidden />
            <span className="truncate">Últimas alterações</span>
          </span>
        }
        subtitulo="Quem mexeu em qual perfil, quando e o que mudou."
        className="min-w-0 overflow-hidden"
      >
        {historico.length === 0 ? (
          <Vazio>Nenhuma alteração registrada ainda.</Vazio>
        ) : (
          <div className="max-w-full overflow-x-auto rounded-campo border border-borda">
            <Tabela className="min-w-[720px]">
              <thead>
                <tr>
                  <Th className="whitespace-nowrap">Quando</Th>
                  <Th>Perfil</Th>
                  <Th>Autor</Th>
                  <Th>O que mudou</Th>
                </tr>
              </thead>
              <tbody>
                {historico.map((linha) => (
                  <TrZebra key={linha.id}>
                    <Td className="whitespace-nowrap tabular-nums">{quando(linha.criado_em)}</Td>
                    <Td>
                      <strong className="font-codigo text-xs">{linha.perfil}</strong>
                      <div className="mt-1">
                        <Selo
                          tom={linha.acao === "removido" ? "critico" : "info"}
                          simbolo={linha.acao === "removido" ? "✕" : "•"}
                        >
                          {linha.acao}
                        </Selo>
                      </div>
                    </Td>
                    <Td className="break-words">{linha.autor}</Td>
                    <Td className="leading-[1.5]">{linha.resumo}</Td>
                  </TrZebra>
                ))}
              </tbody>
            </Tabela>
          </div>
        )}
      </Cartao>
    </div>
  );
}
