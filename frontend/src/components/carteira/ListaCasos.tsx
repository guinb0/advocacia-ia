"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, FolderOpen, Plus, SlidersHorizontal, Trash2 } from "lucide-react";

import type { Caso, CasoCriado, Categoria } from "@/lib/types";
import {
  sugerirCategoriaPorDocumentos,
  sugerirCategoriaPorZip,
  type SugestaoCategoriaPorDocumentos,
} from "@/lib/api";
import { Aviso, Botao, Campo, CampoSeletor, Cartao, RotuloCampo, Selo, Vazio } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import CredenciaisPortal from "@/components/portal/CredenciaisPortal";
import { formatarTelefone, telefonePreenchido } from "@/lib/formato";

interface Props {
  casos: Caso[];
  categorias: Categoria[];
  carregando: boolean;
  erro: string | null;
  onAbrir: (casoId: string) => void;
  onCriar: (cliente: string, categoria: string, observacao?: string, telefone?: string) => Promise<CasoCriado>;
  onExcluir: (casoId: string) => Promise<void>;
  /* Contador, não booleano: cada clique em "Novo caso" na Mesa do dia é um
   * pedido novo, inclusive o segundo seguido. Um booleano só dispararia uma
   * vez e o atalho passaria a não fazer nada no celular. */
  pedidoNovoCaso?: number;
}

function normalizarFiltro(valor: string): string {
  return valor.normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().toLowerCase();
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
  pedidoNovoCaso = 0,
}: Props) {
  const [cliente, setCliente] = useState("");
  const [telefone, setTelefone] = useState("");
  const [categoria, setCategoria] = useState("");
  const [criando, setCriando] = useState(false);
  const [confirmando, setConfirmando] = useState<string | null>(null);
  const [busca, setBusca] = useState("");
  const [tipoFiltro, setTipoFiltro] = useState("");
  const [dataInicial, setDataInicial] = useState("");
  const [dataFinal, setDataFinal] = useState("");
  const [ordem, setOrdem] = useState<"recentes" | "antigos" | "nome">("recentes");
  const [sugerindo, setSugerindo] = useState(false);
  const [sugestao, setSugestao] = useState<SugestaoCategoriaPorDocumentos | null>(null);
  const [erroSugestao, setErroSugestao] = useState<string | null>(null);
  const inputSugestaoRef = useRef<HTMLInputElement>(null);
  const [tentouCriar, setTentouCriar] = useState(false);
  /* Só vale abaixo de 980px, onde as duas colunas viram uma. Acima disso o
   * cadastro é a coluna fixa da esquerda e nunca fecha. */
  const [formularioAberto, setFormularioAberto] = useState(false);
  const [filtrosAbertos, setFiltrosAbertos] = useState(false);
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
  async function criar(evento: React.FormEvent) {
    evento.preventDefault();
    if (!cliente.trim() || !categoriaSelecionada) return;
    if (telefoneVazio && !tentouCriar) {
      setTentouCriar(true);
      return;
    }
    setCriando(true);
    try {
      setNovoPortal(await onCriar(cliente.trim(), categoriaSelecionada, "", formatarTelefone(telefone)));
      setCliente("");
      setTelefone("");
      setTentouCriar(false);
    } finally {
      setCriando(false);
    }
  }

  const nomeCategoria = (codigo: string) =>
    categorias.find((c) => c.codigo === codigo)?.nome ?? codigo;

  const casosFiltrados = useMemo(() => {
    const termo = normalizarFiltro(busca);
    const somenteNumeros = busca.trim() && /^\D*\d[\d.\-/\s]*$/.test(busca);
    return casos
      .filter((caso) => {
        const texto = normalizarFiltro(`${caso.cliente} ${caso.id} ${caso.observacao ?? ""}`);
        const corresponde = !busca.trim() || (somenteNumeros ? texto.replace(/\D/g, "").includes(termo.replace(/\D/g, "")) : texto.includes(termo));
        const dia = (caso.criado_em ?? "").slice(0, 10);
        return corresponde && (!tipoFiltro || caso.categoria === tipoFiltro)
          && (!dataInicial || dia >= dataInicial) && (!dataFinal || dia <= dataFinal);
      })
      .sort((a, b) => ordem === "nome"
        ? a.cliente.localeCompare(b.cliente, "pt-BR")
        : ordem === "antigos"
          ? a.criado_em.localeCompare(b.criado_em)
          : b.criado_em.localeCompare(a.criado_em));
  }, [casos, busca, tipoFiltro, dataInicial, dataFinal, ordem]);

  useEffect(() => setPagina(1), [busca, tipoFiltro, dataInicial, dataFinal, ordem]);

  useEffect(() => {
    if (pedidoNovoCaso) setFormularioAberto(true);
  }, [pedidoNovoCaso]);

  /* Abrir o cadastro é sempre um pedido explícito. Levar o foco ao primeiro
   * campo evita que o operador role a tela procurando onde digitar — e é o que
   * faz o atalho da Mesa do dia continuar valendo no celular. */
  useEffect(() => {
    if (!formularioAberto) return;
    const campo = document.getElementById("cliente");
    if (!(campo instanceof HTMLInputElement)) return;
    campo.scrollIntoView({ block: "center", behavior: "smooth" });
    campo.focus({ preventScroll: true });
  }, [formularioAberto]);

  async function sugerirPelosDocumentos(arquivos: File[]) {
    if (!arquivos.length) return;
    setSugerindo(true);
    setErroSugestao(null);
    setSugestao(null);
    try {
      const resultado =
        arquivos.length === 1 && arquivos[0].name.toLowerCase().endsWith(".zip")
          ? await sugerirCategoriaPorZip(arquivos[0])
          : await sugerirCategoriaPorDocumentos(arquivos);
      setSugestao(resultado);
      const melhor = resultado.sugestoes[0];
      if (melhor && categorias.some((c) => c.codigo === melhor.codigo)) {
        setCategoria(melhor.codigo);
      }
    } catch (e) {
      setErroSugestao(e instanceof Error ? e.message : "Falha ao ler os documentos.");
    } finally {
      setSugerindo(false);
    }
  }

  /* Só o que estreita a lista conta como filtro: a ordenação reordena, não
   * esconde, e a busca continua visível mesmo com o bloco recolhido. */
  const filtrosAtivos = [tipoFiltro, dataInicial, dataFinal].filter(Boolean).length;
  const filtrosOcultos = filtrosAbertos ? "" : "max-sm:hidden";

  const totalPaginas = Math.max(1, Math.ceil(casosFiltrados.length / POR_PAGINA));
  const paginaAtual = Math.min(Math.max(1, pagina), totalPaginas);
  const casosVisiveis = casosFiltrados.slice((paginaAtual - 1) * POR_PAGINA, paginaAtual * POR_PAGINA);

  return (
    <div className="grid min-w-0 grid-cols-[minmax(280px,340px)_minmax(0,1fr)] items-start gap-6 max-[980px]:grid-cols-1">
      {/* No estreito, o formulário empurrava a lista inteira para baixo da
        * dobra: quem vinha "ver meus casos" rolava um cadastro completo antes
        * de achar qualquer caso. Aqui ele começa fechado atrás de um botão; no
        * layout de duas colunas nada muda. */}
      <Botao
        type="button"
        variante="primario"
        bloco
        className="min-[980px]:hidden"
        aria-expanded={formularioAberto}
        aria-controls="formulario-novo-caso"
        onClick={() => setFormularioAberto((aberto) => !aberto)}
      >
        <Plus size={16} aria-hidden />
        {formularioAberto ? "Fechar cadastro" : "Novo caso"}
      </Botao>

      <Cartao
        id="formulario-novo-caso"
        titulo="Novo caso"
        subtitulo="Escolher o tipo de ação é o que monta o checklist de documentos do cliente."
        className={`min-w-0 lg:sticky lg:top-6 ${formularioAberto ? "" : "max-[980px]:hidden"}`}
      >
        <form onSubmit={criar}>
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

          <div className="mb-4 px-[14px] py-[13px] border border-borda rounded-campo bg-papel-2">
            <div className="flex justify-between items-center gap-3 flex-wrap">
              <div>
                <strong className="block text-tinta text-sm">Não sabe o tipo de ação?</strong>
                <p className="mt-1 mb-0 text-tinta-2 text-xs leading-[1.5]">
                  Envie os documentos do cliente (ou um .zip da pasta) e o sistema lê e sugere.
                  A escolha final continua sendo sua.
                </p>
              </div>
              <Botao
                type="button"
                variante="secundario"
                pequeno
                disabled={sugerindo}
                onClick={() => inputSugestaoRef.current?.click()}
              >
                {sugerindo ? "Lendo…" : "Escolher documentos"}
              </Botao>
              <input
                ref={inputSugestaoRef}
                type="file"
                multiple
                hidden
                onChange={(e) => {
                  void sugerirPelosDocumentos(Array.from(e.target.files ?? []));
                  e.target.value = "";
                }}
              />
            </div>

            {sugerindo && (
              <p className="mt-[10px] mb-0 text-tinta-3 text-xs">
                Lendo os documentos por OCR — um lote com várias dezenas de arquivos pode levar
                alguns minutos.
              </p>
            )}

            {erroSugestao && (
              <div className="mt-[10px]">
                <Aviso tom="critico" titulo="Não foi possível sugerir">
                  {erroSugestao}
                </Aviso>
              </div>
            )}

            {sugestao && (
              <div className="mt-[10px]">
                {sugestao.sugestoes.length === 0 ? (
                  <p className="m-0 text-tinta-2 text-xs leading-[1.5]">{sugestao.motivo}</p>
                ) : (
                  <>
                    <p className="m-0 text-tinta-2 text-xs leading-[1.5]">
                      {sugestao.confiante ? "Sugestão: " : "Sugestão (confira antes de aceitar): "}
                      <strong>{sugestao.sugestoes[0].nome}</strong> — {sugestao.motivo}
                    </p>
                    {sugestao.sugestoes[0].evidencias.length > 0 && (
                      <ul className="mt-[6px] mb-0 pl-4 text-tinta-3 text-xs leading-[1.5]">
                        {sugestao.sugestoes[0].evidencias.slice(0, 3).map((ev, i) => (
                          <li key={i}>{ev}</li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
                <p className="mt-[6px] mb-0 text-tinta-3 text-xs">
                  {sugestao.documentos.length} documento(s) lido(s).
                </p>
              </div>
            )}
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
                : !categoriaSelecionada
                  ? "Escolha o tipo de ação."
                  : null
            }
            onPendencia={() => document.getElementById(cliente.trim() ? "categoria" : "cliente")?.focus()}
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
            : `${casosFiltrados.length} de ${casos.length} ${casos.length === 1 ? "caso" : "casos"}.`
        }
      >
        {erro && (
          <div className="mb-[14px]">
            <Aviso tom="critico" titulo="Não foi possível carregar os casos">
              {erro}
            </Aviso>
          </div>
        )}

          {/* A busca fica sempre à vista. O resto dos filtros só ocupa a tela
            * estreita quando pedido: empilhados, eles somavam mais de uma tela
            * de celular antes do primeiro caso da lista. Em `sm` para cima tudo
            * aparece de uma vez, como antes. O contador no botão evita o pior
            * caso do recolhido — filtrar sem lembrar que filtrou. */}
          <div className="mb-4 grid gap-3 rounded-campo border border-borda bg-papel-2 p-3 sm:grid-cols-2 2xl:grid-cols-4">
            <Campo
              className="sm:col-span-2"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              placeholder="Buscar por nome, CPF ou ID"
              aria-label="Buscar casos"
            />
            <Botao
              type="button"
              variante="secundario"
              className="min-h-[42px] justify-between sm:hidden"
              aria-expanded={filtrosAbertos}
              aria-controls="filtros-de-casos"
              onClick={() => setFiltrosAbertos((aberto) => !aberto)}
            >
              <span className="inline-flex items-center gap-2">
                <SlidersHorizontal size={15} aria-hidden />
                Filtros
                {filtrosAtivos > 0 && <Selo tom="info">{filtrosAtivos}</Selo>}
              </span>
              <ChevronDown size={15} aria-hidden className={filtrosAbertos ? "rotate-180" : ""} />
            </Botao>
            <CampoSeletor
              id="filtros-de-casos"
              className={filtrosOcultos}
              value={tipoFiltro}
              onChange={(e) => setTipoFiltro(e.target.value)}
              aria-label="Filtrar por tipo de caso"
            >
              <option value="">Todos os tipos</option>
              {categorias.map((c) => <option key={c.codigo} value={c.codigo}>{c.nome}</option>)}
            </CampoSeletor>
            <CampoSeletor
              className={filtrosOcultos}
              value={ordem}
              onChange={(e) => setOrdem(e.target.value as typeof ordem)}
              aria-label="Ordenar casos"
            >
              <option value="recentes">Mais recentes</option>
              <option value="antigos">Mais antigos</option>
              <option value="nome">Nome A–Z</option>
            </CampoSeletor>
            <label className={`text-xs text-tinta-3 ${filtrosOcultos}`}>
              De
              <Campo type="date" className="mt-1 px-2 text-sm" value={dataInicial} onChange={(e) => setDataInicial(e.target.value)} />
            </label>
            <label className={`text-xs text-tinta-3 ${filtrosOcultos}`}>
              Até
              <Campo type="date" className="mt-1 px-2 text-sm" value={dataFinal} onChange={(e) => setDataFinal(e.target.value)} />
            </label>
            <Botao
              type="button"
              variante="secundario"
              className={`min-h-[42px] ${filtrosOcultos}`}
              onClick={() => { setBusca(""); setTipoFiltro(""); setDataInicial(""); setDataFinal(""); setOrdem("recentes"); }}
            >
              Limpar filtros
            </Botao>
            <p className="m-0 self-center text-xs text-tinta-3">{casosFiltrados.length} resultado(s)</p>
          </div>

        {carregando && casos.length === 0 ? (
          <Vazio>Carregando…</Vazio>
        ) : casos.length === 0 ? (
          <Vazio>Nenhum caso cadastrado ainda. Use “Novo caso” para montar o checklist de documentos do cliente.</Vazio>
        ) : casosFiltrados.length === 0 ? (
          <Vazio>Nenhum caso corresponde aos filtros. Altere a busca ou use “Limpar filtros”.</Vazio>
        ) : (
          <>
          <div className="min-w-0 overflow-hidden rounded-campo border border-borda">
            <div className="hidden grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_112px_136px] gap-3 border-b border-borda bg-papel-2 px-4 py-3 text-xs font-bold uppercase tracking-[0.08em] text-tinta-3 min-[780px]:grid">
              <span>Cliente</span>
              <span>Tipo de ação</span>
              <span>Arquivos</span>
              <span className="text-right">Ações</span>
            </div>

            <ul className="m-0 list-none divide-y divide-borda p-0">
              {casosVisiveis.map((caso) => {
                const totalEntregas = caso.total_entregas ?? 0;
                const categoriaNome = nomeCategoria(caso.categoria);

                return (
                  <li key={caso.id} className="min-w-0 bg-papel">
                    <div className="grid min-w-0 gap-3 px-3 py-3 min-[780px]:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_112px_136px] min-[780px]:items-center min-[780px]:px-4">
                      <button
                        type="button"
                        className="min-w-0 rounded-campo border-none bg-transparent p-1 text-left text-inherit [font:inherit] transition-colors hover:bg-papel-3"
                        onClick={() => onAbrir(caso.id)}
                        title={caso.cliente}
                      >
                        <span className="block truncate text-base font-semibold text-tinta">
                          {caso.cliente}
                        </span>
                        <span className="mt-1 block truncate font-codigo text-xs text-tinta-3">
                          {caso.id}
                        </span>
                      </button>

                      <div className="min-w-0">
                        <span className="mb-1 block text-xs font-bold uppercase tracking-[0.08em] text-tinta-3 min-[780px]:hidden">
                          Tipo de ação
                        </span>
                        <span className="block truncate text-sm text-tinta-2" title={categoriaNome}>
                          {categoriaNome}
                        </span>
                      </div>

                      <div className="min-w-0">
                        <span className="mb-1 block text-xs font-bold uppercase tracking-[0.08em] text-tinta-3 min-[780px]:hidden">
                          Arquivos
                        </span>
                        <Selo tom={totalEntregas > 0 ? "info" : "neutro"}>
                          {totalEntregas} {totalEntregas === 1 ? "arquivo" : "arquivos"}
                        </Selo>
                      </div>

                      <div className="flex min-w-0 items-center justify-start gap-2 min-[780px]:justify-end">
                        <button
                          type="button"
                          className={`${ACAO_ICONE} border-borda-campo bg-papel text-acao-texto hover:border-acao hover:bg-acao-clara`}
                          onClick={() => onAbrir(caso.id)}
                          title="Abrir caso"
                          aria-label={`Abrir caso de ${caso.cliente}`}
                        >
                          <FolderOpen size={17} strokeWidth={2.1} aria-hidden />
                        </button>
                        <button
                          type="button"
                          className={`${ACAO_ICONE} border-transparent bg-transparent text-tinta-2 hover:border-critico-borda hover:bg-critico-claro hover:text-critico`}
                          onClick={async () => {
                            const confirmado = window.confirm(
                              `Apagar o caso de ${caso.cliente}?\n\nEssa ação remove o caso e os arquivos vinculados. Não continue se clicou sem querer.`,
                            );
                            if (!confirmado) return;
                            await onExcluir(caso.id);
                          }}
                          title="Apagar caso"
                          aria-label={`Apagar caso de ${caso.cliente}`}
                        >
                          <Trash2 size={17} strokeWidth={2.1} aria-hidden />
                        </button>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>

          {casosFiltrados.length > POR_PAGINA && (
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
