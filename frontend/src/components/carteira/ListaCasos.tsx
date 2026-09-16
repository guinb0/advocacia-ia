"use client";

import { useEffect, useMemo, useState } from "react";
import { FolderOpen, Trash2 } from "lucide-react";

import type { Caso, CasoCriado, Categoria } from "@/lib/types";
import { Aviso, Botao, Campo, CampoSeletor, Cartao, RotuloCampo, Selo, Vazio } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import CredenciaisPortal from "@/components/portal/CredenciaisPortal";
import { formatarTelefone, telefonePreenchido } from "@/lib/formato";
import { enviarTranscricaoEntrevista, triarEntrevista } from "@/lib/api";

interface Props {
  casos: Caso[];
  categorias: Categoria[];
  carregando: boolean;
  erro: string | null;
  onAbrir: (casoId: string) => void;
  onCriar: (cliente: string, categoria: string, observacao?: string, telefone?: string) => Promise<CasoCriado>;
  onExcluir: (casoId: string) => Promise<void>;
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
  onCriar,
  onExcluir,
}: Props) {
  const [cliente, setCliente] = useState("");
  const [telefone, setTelefone] = useState("");
  const [categoria, setCategoria] = useState("");
  const [entrevistaArquivo, setEntrevistaArquivo] = useState<File | null>(null);
  const [analisandoEntrevista, setAnalisandoEntrevista] = useState(false);
  const [resultadoTriagem, setResultadoTriagem] = useState<string | null>(null);
  const [filtroCliente, setFiltroCliente] = useState("");
  const [criando, setCriando] = useState(false);
  const [tentouCriar, setTentouCriar] = useState(false);
  /* A lista chega inteira do servidor (podem ser centenas). Aqui ela é paginada
   * de 5 em 5 só para exibição — nada é buscado por página. `pagina` pode ficar
   * maior que o total depois de uma exclusão; `paginaAtual` reancora. */
  const POR_PAGINA = 5;
  const [pagina, setPagina] = useState(1);
  /* Credenciais do caso recém-criado. Ficam só em memória: a senha existe em
   * texto claro apenas nesta resposta, e some ao sair da tela. */
  const [novoPortal, setNovoPortal] = useState<CasoCriado | null>(null);
  const categoriaSelecionada = categoria || categorias[0]?.codigo || "";
  const categoriaEscolhida = categorias.find((item) => item.codigo === categoriaSelecionada);
  const telefoneVazio = !telefonePreenchido(telefone);
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

  async function criar(evento: React.FormEvent) {
    evento.preventDefault();
    if (!cliente.trim() || !categoriaSelecionada || !entrevistaArquivo) return;
    if (telefoneVazio && !tentouCriar) {
      setTentouCriar(true);
      return;
    }
    setCriando(true);
    try {
      const novo = await onCriar(cliente.trim(), categoriaSelecionada, "", formatarTelefone(telefone));
      await enviarTranscricaoEntrevista(novo.id, entrevistaArquivo);
      setNovoPortal(novo);
      setCliente("");
      setTelefone("");
      setEntrevistaArquivo(null);
      setResultadoTriagem(null);
      setTentouCriar(false);
    } finally {
      setCriando(false);
    }
  }

  async function selecionarEntrevista(arquivo: File | null) {
    setEntrevistaArquivo(arquivo);
    setResultadoTriagem(null);
    if (!arquivo) return;
    setAnalisandoEntrevista(true);
    try {
      const triagem = await triarEntrevista("", arquivo);
      const sugestao = triagem.sugestoes[0];
      if (sugestao) setCategoria(sugestao.codigo);
      if (!cliente.trim() && triagem.dados.cliente) setCliente(triagem.dados.cliente);
      setResultadoTriagem(
        sugestao
          ? `A IA sugere: ${sugestao.nome}. Você pode alterar a escolha abaixo.`
          : "A entrevista foi salva para o caso; escolha o tipo de ação abaixo.",
      );
    } catch (erro) {
      setResultadoTriagem(erro instanceof Error ? erro.message : "Não foi possível analisar a entrevista.");
    } finally {
      setAnalisandoEntrevista(false);
    }
  }

  const nomeCategoria = (codigo: string) =>
    categorias.find((c) => c.codigo === codigo)?.nome ?? codigo;

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
    <div className="grid min-w-0 grid-cols-[minmax(280px,380px)_minmax(0,1fr)] items-start gap-5 max-[980px]:grid-cols-1">
      <Cartao
        titulo="Novo caso"
        subtitulo="Escolher o tipo de ação é o que monta o checklist de documentos do cliente."
        className="min-w-0"
      >
        <form onSubmit={criar}>
          <div className="mb-4">
            <RotuloCampo htmlFor="entrevista-inicial">Entrevista do cliente (.txt)</RotuloCampo>
            <input
              id="entrevista-inicial"
              type="file"
              accept=".txt,text/plain"
              onChange={(e) => void selecionarEntrevista(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-tinta-2"
            />
            <p className="mt-1 text-xs leading-[1.5] text-tinta-3">
              A IA lê a entrevista, sugere o tipo de ação e gera o resumo do atendimento. A sugestão pode ser alterada.
            </p>
            {analisandoEntrevista && <p className="mt-1 text-xs text-tinta-3">Analisando entrevista…</p>}
            {resultadoTriagem && <p className="mt-1 text-xs text-tinta-2">{resultadoTriagem}</p>}
          </div>
          <div className="mb-4">
            <RotuloCampo htmlFor="cliente">Nome do cliente</RotuloCampo>
            <Campo
              id="cliente"
              value={cliente}
              onChange={(e) => setCliente(e.target.value)}
              placeholder="Ex.: Maria Aparecida da Silva"
              autoComplete="off"
            />
          </div>

          <div className="mb-4">
            <RotuloCampo htmlFor="telefone">Telefone / WhatsApp do cliente</RotuloCampo>
            <Campo
              id="telefone"
              type="tel"
              inputMode="tel"
              value={formatarTelefone(telefone)}
              onChange={(e) => setTelefone(formatarTelefone(e.target.value))}
              placeholder="(61) 98180-8863"
              autoComplete="off"
              aria-invalid={tentouCriar && telefoneVazio}
              className={tentouCriar && telefoneVazio ? "border-atencao" : undefined}
            />
            {tentouCriar && telefoneVazio && (
              <p className="mt-[6px] text-xs leading-[1.5] text-atencao">
                Telefone vazio. Clique em criar novamente para seguir sem WhatsApp automático.
              </p>
            )}
          </div>

          <div className="mb-4">
            <RotuloCampo htmlFor="categoria">Tipo de ação</RotuloCampo>
            <CampoSeletor
              id="categoria"
              value={categoriaSelecionada}
              onChange={(e) => setCategoria(e.target.value)}
              aria-describedby={categoriaEscolhida ? "resumo-categoria" : undefined}
            >
              {categorias.map((c) => (
                <option key={c.codigo} value={c.codigo}>
                  {c.nome}
                </option>
              ))}
            </CampoSeletor>

            {categoriaEscolhida && (
              <div
                id="resumo-categoria"
                className="mt-[10px] px-[14px] py-[13px] border border-acao-borda rounded-campo bg-acao-clara"
              >
                <strong className="block text-tinta text-sm">{categoriaEscolhida.nome}</strong>
                <p className="mt-1 text-tinta-2 text-xs leading-[1.5]">
                  {categoriaEscolhida.descricao}
                </p>
                <div className="flex gap-2 mt-[10px] flex-wrap">
                  <Selo tom="info">{categoriaEscolhida.total_obrigatorios} obrigatórios</Selo>
                  <Selo tom="neutro">{categoriaEscolhida.total_documentos} no total</Selo>
                </div>
              </div>
            )}
          </div>

          <BotaoProcesso
            type="submit"
            variante="primario"
            bloco
            processando={criando}
            textoProcessando="Criando o caso…"
            pendencia={
              !cliente.trim()
                ? "Digite o nome do cliente para criar o caso."
                : !entrevistaArquivo
                  ? "Adicione o TXT da entrevista para a IA analisar o caso."
                : !categoriaSelecionada
                  ? "Escolha o tipo de ação."
                  : null
            }
            onPendencia={() => document.getElementById(!entrevistaArquivo ? "entrevista-inicial" : cliente.trim() ? "categoria" : "cliente")?.focus()}
          >
            Criar o caso
          </BotaoProcesso>
        </form>

        {categorias.length === 0 && (
          <div className="mt-[14px]">
            <Aviso tom="critico" titulo="Nenhum tipo de ação disponível">
              Verifique se o servidor do sistema está no ar — sem os tipos de ação não é possível
              criar um caso.
            </Aviso>
          </div>
        )}

        {novoPortal && (
          <CredenciaisPortal
            cliente={novoPortal.cliente}
            portal={novoPortal.portal}
            casoId={novoPortal.id}
            telefone={novoPortal.telefone}
            onAbrirCaso={() => onAbrir(novoPortal.id)}
            onFechar={() => setNovoPortal(null)}
          />
        )}
      </Cartao>

      <Cartao
        titulo="Casos cadastrados"
        className="min-w-0 overflow-hidden"
        subtitulo={
          casos.length === 0
            ? "Nenhum caso ainda."
            : `${casosFiltrados.length} de ${casos.length} ${casos.length === 1 ? "caso" : "casos"} — mais recentes primeiro.`
        }
      >
        {erro && (
          <div className="mb-[14px]">
            <Aviso tom="critico" titulo="Não foi possível carregar os casos">
              {erro}
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
          <Vazio>Crie o primeiro caso ao lado para começar a cobrar os documentos do cliente.</Vazio>
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
                        <span className="mt-1 block truncate font-codigo text-xs text-tinta-3">
                          {unico ? unico.id : `${grupo.casos.length} casos — clique para escolher a ação`}
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
                                    {caso.criado_em ? ` · criado em ${new Date(caso.criado_em).toLocaleDateString("pt-BR")}` : ""}
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
