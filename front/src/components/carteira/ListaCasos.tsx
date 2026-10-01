"use client";

import { useEffect, useMemo, useState } from "react";
import { Download, FolderOpen, Loader2, Plus, Trash2 } from "lucide-react";

import type { Caso, Categoria } from "@/lib/types";
import { Aviso, Botao, Campo, Cartao, RotuloCampo, Selo, Vazio } from "@/components/ui/Basicos";
import { baixarDocumentosDoCaso } from "@/lib/api";
import { baixarArquivo } from "@/lib/baixar";

interface Props {
  casos: Caso[];
  categorias: Categoria[];
  carregando: boolean;
  erro: string | null;
  onAbrir: (casoId: string) => void;
  onNovoCaso: () => void;
  onExcluir: (casoId: string) => Promise<void>;
}

function dataCurta(iso: string | null | undefined): string {
  if (!iso) return "";
  const data = new Date(iso);
  return Number.isNaN(data.getTime()) ? "" : data.toLocaleDateString("pt-BR");
}

function normalizarFiltro(valor: string): string {
  return valor.normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().toLowerCase();
}

/** Tipos distintos que cabem na linha antes de virarem "+N". */
const TIPOS_VISIVEIS = 2;

/**
 * Tipos de ação de um cliente com vários casos: um selo por tipo, com a
 * quantidade, e não um por caso. Um selo por caso fazia 12 casos de 3 tipos
 * virarem 12 selos repetidos, e a linha crescia até ocupar a tela.
 */
function TiposDoGrupo({ nomes }: { nomes: string[] }) {
  const contagem = new Map<string, number>();
  for (const nome of nomes) contagem.set(nome, (contagem.get(nome) ?? 0) + 1);
  const tipos = [...contagem.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const visiveis = tipos.slice(0, TIPOS_VISIVEIS);
  const restantes = tipos.length - visiveis.length;

  return (
    <span
      className="flex min-w-0 flex-wrap gap-1"
      title={tipos.map(([nome, total]) => `${nome} (${total})`).join("\n")}
    >
      {visiveis.map(([nome, total]) => (
        // A contagem vai no `simbolo`, que não encolhe: no texto ela sumiria no
        // "…" de nomes longos como "Acidente do Trabalho (Correios)".
        <Selo key={nome} tom="info" simbolo={total > 1 ? `${total}×` : undefined}>
          {nome}
        </Selo>
      ))}
      {restantes > 0 && (
        <Selo tom="neutro">
          +{restantes} {restantes === 1 ? "tipo" : "tipos"}
        </Selo>
      )}
    </span>
  );
}

const ACAO_ICONE =
  "inline-flex h-9 w-9 items-center justify-center rounded-campo border transition-colors " +
  "duration-[120ms] ease-out disabled:cursor-not-allowed disabled:opacity-60";

export default function ListaCasos({
  casos,
  categorias,
  carregando,
  erro,
  onAbrir,
  onNovoCaso,
  onExcluir,
}: Props) {
  const [filtroCliente, setFiltroCliente] = useState("");
  /* A lista chega inteira do servidor (podem ser centenas). Aqui ela é paginada
   * de 5 em 5 só para exibição — nada é buscado por página. `pagina` pode ficar
   * maior que o total depois de uma exclusão; `paginaAtual` reancora. */
  const POR_PAGINA = 5;
  const [pagina, setPagina] = useState(1);
  const filtroNormalizado = normalizarFiltro(filtroCliente);
  const casosOrdenados = useMemo(
    () =>
      [...casos].sort((a, b) => {
        const dataA = Date.parse(a.criado_em || "");
        const dataB = Date.parse(b.criado_em || "");
        if (Number.isNaN(dataA) && Number.isNaN(dataB)) return a.cliente.localeCompare(b.cliente, "pt-BR");
        if (Number.isNaN(dataA)) return 1;
        if (Number.isNaN(dataB)) return -1;
        return dataB - dataA;
      }),
    [casos],
  );
  const casosFiltrados = useMemo(
    () =>
      filtroNormalizado
        ? casosOrdenados.filter((caso) => normalizarFiltro(caso.cliente).includes(filtroNormalizado))
        : casosOrdenados,
    [casosOrdenados, filtroNormalizado],
  );

  useEffect(() => {
    setPagina(1);
  }, [filtroNormalizado]);

  const nomeCategoria = (codigo: string) =>
    categorias.find((c) => c.codigo === codigo)?.nome ?? codigo;

  /* Mesmo pacote do botão dentro do caso (`BaixarDocumentos`): tudo que o
   * cliente enviou, na ordem do checklist. Só um download por vez — o ZIP é
   * montado no servidor a cada pedido e pode passar de centenas de MB. */
  const [baixandoId, setBaixandoId] = useState<string | null>(null);
  const [avisoDownload, setAvisoDownload] = useState<{ tom: "atencao" | "critico"; titulo: string; texto: string } | null>(null);

  async function baixarDocumentos(caso: Caso) {
    if (baixandoId) return;
    setBaixandoId(caso.id);
    setAvisoDownload(null);
    try {
      const pacote = await baixarDocumentosDoCaso(caso.id);
      baixarArquivo(pacote.arquivo, pacote.nome);
      /* Pacote incompleto que desce calado é pior que erro: ninguém confere o
       * que não sabe que faltou. */
      if (pacote.faltando > 0) {
        setAvisoDownload({
          tom: "atencao",
          titulo: `O pacote de ${caso.cliente} saiu incompleto`,
          texto: `${pacote.faltando} ${pacote.faltando === 1 ? "arquivo constava" : "arquivos constavam"} no caso mas não ${pacote.faltando === 1 ? "está" : "estão"} mais no disco. Abra o caso e confira o checklist.`,
        });
      }
    } catch (e) {
      setAvisoDownload({
        tom: "critico",
        titulo: `Não foi possível baixar os documentos de ${caso.cliente}`,
        texto: e instanceof Error ? e.message : "Não foi possível montar o pacote.",
      });
    } finally {
      setBaixandoId(null);
    }
  }

  function botaoBaixar(caso: Caso) {
    const arquivos = caso.total_entregas ?? 0;
    const baixando = baixandoId === caso.id;
    return (
      <button
        type="button"
        className={`${ACAO_ICONE} border-borda-campo bg-papel text-acao hover:border-acao hover:bg-acao-clara`}
        onClick={() => void baixarDocumentos(caso)}
        disabled={arquivos === 0 || baixandoId !== null}
        title={arquivos === 0 ? "Sem documentos enviados" : baixando ? "Montando o pacote…" : `Baixar os ${arquivos} documentos (.zip)`}
        aria-label={`Baixar os documentos de ${caso.cliente} em .zip`}
      >
        {baixando
          ? <Loader2 size={17} strokeWidth={2.1} className="animate-spin" aria-hidden />
          : <Download size={17} strokeWidth={2.1} aria-hidden />}
      </button>
    );
  }

  async function excluirCaso(caso: Caso) {
    const confirmado = window.confirm(
      `Apagar o caso de ${caso.cliente} (${nomeCategoria(caso.categoria)})?\n\nEssa ação remove o caso e os arquivos vinculados. Não continue se clicou sem querer.`,
    );
    if (!confirmado) return;
    await onExcluir(caso.id);
  }

  const [clienteAberto, setClienteAberto] = useState<string | null>(null);
  const grupos = useMemo(() => {
    const mapa = new Map<string, Caso[]>();
    for (const caso of casosFiltrados) {
      const chave = normalizarFiltro(caso.cliente);
      mapa.set(chave, [...(mapa.get(chave) ?? []), caso]);
    }
    return [...mapa.entries()].map(([chave, lista]) => ({ chave, cliente: lista[0].cliente, casos: lista }));
  }, [casosFiltrados]);

  const totalPaginas = Math.max(1, Math.ceil(grupos.length / POR_PAGINA));
  const paginaAtual = Math.min(Math.max(1, pagina), totalPaginas);
  const gruposVisiveis = grupos.slice((paginaAtual - 1) * POR_PAGINA, paginaAtual * POR_PAGINA);

  return (
    <div className="grid min-w-0 gap-5">
      <Cartao className="min-w-0 overflow-hidden">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="mb-1 font-titulo text-lg font-semibold leading-[1.25] text-tinta">Casos cadastrados</h2>
            <p className="m-0 text-sm leading-[1.5] text-tinta-3">
              {casos.length === 0
                ? "Nenhum caso ainda."
                : `${casosFiltrados.length} de ${casos.length} ${casos.length === 1 ? "caso" : "casos"} — mais recentes primeiro.`}
            </p>
          </div>
          <Botao variante="primario" onClick={onNovoCaso}>
            <Plus className="h-4 w-4" aria-hidden />
            Novo caso
          </Botao>
        </div>
        {erro && (
          <div className="mb-[14px]">
            <Aviso tom="critico" titulo="Não foi possível carregar os casos">
              {erro}
            </Aviso>
          </div>
        )}

        {avisoDownload && (
          <div className="mb-[14px]">
            <Aviso tom={avisoDownload.tom} titulo={avisoDownload.titulo}>
              {avisoDownload.texto}
            </Aviso>
          </div>
        )}

        <div className="mb-4">
          <RotuloCampo htmlFor="filtro-casos-cliente">Filtrar por nome do caso</RotuloCampo>
          <Campo
            id="filtro-casos-cliente"
            value={filtroCliente}
            onChange={(e) => setFiltroCliente(e.target.value)}
            placeholder="Digite o nome do cliente"
            autoComplete="off"
          />
        </div>

        {carregando && casos.length === 0 ? (
          <Vazio>Carregando…</Vazio>
        ) : casos.length === 0 ? (
          <Vazio>
            Ainda não há casos. Clique em <strong>Novo caso</strong> para cadastrar o primeiro cliente.
          </Vazio>
        ) : casosFiltrados.length === 0 ? (
          <Vazio>Nenhum caso encontrado com esse nome.</Vazio>
        ) : (
          <>
          <div className="min-w-0 overflow-hidden rounded-campo border border-borda">
            <div className="hidden grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_112px_136px] gap-3 border-b border-borda bg-papel-2 px-4 py-3 text-[11px] font-bold uppercase tracking-[0.08em] text-tinta-3 min-[780px]:grid">
              <span>Cliente</span>
              <span>Tipo de ação</span>
              <span>Arquivos</span>
              <span className="text-right">Ações</span>
            </div>

            <ul className="m-0 list-none divide-y divide-borda p-0">
              {gruposVisiveis.map((grupo) => {
                const unico = grupo.casos.length === 1 ? grupo.casos[0] : null;
                const aberto = clienteAberto === grupo.chave;
                const totalEntregas = grupo.casos.reduce((soma, caso) => soma + (caso.total_entregas ?? 0), 0);
                const abrirGrupo = () => (unico ? onAbrir(unico.id) : setClienteAberto(aberto ? null : grupo.chave));

                return (
                  <li key={grupo.chave} className="min-w-0 bg-papel">
                    <div className="grid min-w-0 gap-3 px-3 py-3 min-[780px]:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_112px_136px] min-[780px]:items-center min-[780px]:px-4">
                      <button
                        type="button"
                        className="min-w-0 rounded-campo border-none bg-transparent p-1 text-left text-inherit [font:inherit] transition-colors hover:bg-papel-3"
                        onClick={abrirGrupo}
                        title={grupo.cliente}
                      >
                        <span className="block truncate text-base font-semibold text-tinta">
                          {grupo.cliente}
                        </span>
                        <span className="mt-1 block truncate text-xs text-tinta-3">
                          {unico
                            ? dataCurta(unico.criado_em) && `criado em ${dataCurta(unico.criado_em)}`
                            : `${grupo.casos.length} casos — clique para escolher a ação`}
                        </span>
                      </button>

                      <div className="min-w-0">
                        <span className="mb-1 block text-[11px] font-bold uppercase tracking-[0.08em] text-tinta-3 min-[780px]:hidden">
                          Tipo de ação
                        </span>
                        {unico ? (
                          <span className="block truncate text-sm text-tinta-2" title={nomeCategoria(unico.categoria)}>
                            {nomeCategoria(unico.categoria)}
                          </span>
                        ) : (
                          <TiposDoGrupo nomes={grupo.casos.map((caso) => nomeCategoria(caso.categoria))} />
                        )}
                      </div>

                      <div className="min-w-0">
                        <span className="mb-1 block text-[11px] font-bold uppercase tracking-[0.08em] text-tinta-3 min-[780px]:hidden">
                          Arquivos
                        </span>
                        <Selo tom={totalEntregas > 0 ? "info" : "neutro"}>
                          {totalEntregas} {totalEntregas === 1 ? "arquivo" : "arquivos"}
                        </Selo>
                      </div>

                      <div className="flex min-w-0 items-center justify-start gap-2 min-[780px]:justify-end">
                        <button
                          type="button"
                          className={`${ACAO_ICONE} border-borda-campo bg-papel text-acao hover:border-acao hover:bg-acao-clara`}
                          onClick={abrirGrupo}
                          title={unico ? "Abrir caso" : "Escolher a ação"}
                          aria-label={unico ? `Abrir caso de ${grupo.cliente}` : `Escolher a ação de ${grupo.cliente}`}
                        >
                          <FolderOpen size={17} strokeWidth={2.1} aria-hidden />
                        </button>
                        {unico && botaoBaixar(unico)}
                        {unico && (
                          <button
                            type="button"
                            className={`${ACAO_ICONE} border-transparent bg-transparent text-tinta-2 hover:border-critico-borda hover:bg-critico-claro hover:text-critico`}
                            onClick={() => void excluirCaso(unico)}
                            title="Apagar caso"
                            aria-label={`Apagar caso de ${grupo.cliente}`}
                          >
                            <Trash2 size={17} strokeWidth={2.1} aria-hidden />
                          </button>
                        )}
                      </div>
                    </div>

                    {aberto && (
                      <div className="border-t border-borda bg-papel-2 px-3 py-3 min-[780px]:px-4">
                        <span className="mb-2 block text-[11px] font-bold uppercase tracking-[0.08em] text-tinta-3">
                          Qual ação você quer abrir?
                        </span>
                        <ul className="m-0 grid list-none gap-2 p-0">
                          {grupo.casos.map((caso) => {
                            const arquivos = caso.total_entregas ?? 0;
                            return (
                              <li
                                key={caso.id}
                                className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-campo border border-borda bg-papel px-3 py-2"
                              >
                                <button
                                  type="button"
                                  className="min-w-0 flex-1 cursor-pointer border-none bg-transparent p-0 text-left [font:inherit]"
                                  onClick={() => onAbrir(caso.id)}
                                >
                                  <span className="block truncate text-sm font-semibold text-tinta">
                                    {nomeCategoria(caso.categoria)}
                                  </span>
                                  <span className="block truncate text-xs text-tinta-3">
                                    {arquivos} {arquivos === 1 ? "arquivo" : "arquivos"}
                                    {dataCurta(caso.criado_em) ? ` · criado em ${dataCurta(caso.criado_em)}` : ""}
                                  </span>
                                </button>
                                <div className="flex items-center gap-2">
                                  <button
                                    type="button"
                                    className={`${ACAO_ICONE} border-borda-campo bg-papel text-acao hover:border-acao hover:bg-acao-clara`}
                                    onClick={() => onAbrir(caso.id)}
                                    title="Abrir caso"
                                    aria-label={`Abrir ${nomeCategoria(caso.categoria)} de ${caso.cliente}`}
                                  >
                                    <FolderOpen size={17} strokeWidth={2.1} aria-hidden />
                                  </button>
                                  {botaoBaixar(caso)}
                                  <button
                                    type="button"
                                    className={`${ACAO_ICONE} border-transparent bg-transparent text-tinta-2 hover:border-critico-borda hover:bg-critico-claro hover:text-critico`}
                                    onClick={() => void excluirCaso(caso)}
                                    title="Apagar caso"
                                    aria-label={`Apagar ${nomeCategoria(caso.categoria)} de ${caso.cliente}`}
                                  >
                                    <Trash2 size={17} strokeWidth={2.1} aria-hidden />
                                  </button>
                                </div>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>

          {grupos.length > POR_PAGINA && (
            <div className="mt-3 flex min-w-0 items-center justify-between gap-3 border-t border-borda pt-3">
              <Botao
                variante="discreto"
                pequeno
                disabled={paginaAtual <= 1}
                onClick={() => setPagina(paginaAtual - 1)}
              >
                ← Anterior
              </Botao>
              <span className="min-w-0 truncate text-center text-xs tabular-nums text-tinta-3">
                Página {paginaAtual} de {totalPaginas}
              </span>
              <Botao
                variante="discreto"
                pequeno
                disabled={paginaAtual >= totalPaginas}
                onClick={() => setPagina(paginaAtual + 1)}
              >
                Próximo →
              </Botao>
            </div>
          )}
          </>
        )}
      </Cartao>
    </div>
  );
}
