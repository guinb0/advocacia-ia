"use client";

/**
 * Tipos de caso — as ações que o escritório aceita e o checklist de cada uma.
 *
 * QUEM ENTRA AQUI
 *
 * A tela pede o módulo `tipos_caso` (de fábrica: Advogado e Secretário, ver
 * `app/perfis.py`). Consultar não pede nada: a criação do caso lê a mesma lista.
 *
 * AS CINCO DO CÓDIGO SÃO SÓ DE LEITURA
 *
 * Acidente nos Correios, acidente geral, doença ocupacional, assalto a carteiro e
 * auxílio-acidente vêm dos checklists em `.docx` do escritório, conferidos por
 * `tests/test_categorias.py`. Aqui elas aparecem marcadas como "do sistema" e só dá
 * para ligar e desligar — reescrever o checklist delas pela tela faria o cadastro
 * divergir do documento assinado.
 *
 * O CÓDIGO DO ITEM NÃO É DA TELA
 *
 * Item novo vai sem código e o servidor dá um que nunca se repete. É esse código que
 * fica gravado em cada documento entregue: se a tela renumerasse os itens ao remover
 * um do meio, os documentos passariam a responder pelo item errado.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  History,
  Layers,
  PencilLine,
  Plus,
  Trash2,
} from "lucide-react";

import {
  AjudaCampo,
  Aviso,
  Botao,
  Cartao,
  Marcacao,
  Selo,
  Vazio,
} from "@/components/ui/Basicos";
import {
  ApiError,
  criarTipoCaso,
  editarTipoCaso,
  historicoTipoCaso,
  impactoTipoCaso,
  listarTiposCaso,
  listarTiposDocumento,
} from "@/lib/api";
import { AUTH_ATIVA, useSessao } from "@/lib/auth";
import type {
  EventoHistorico,
  ImpactoTipoCaso,
  ItemTipoCaso,
  TipoCaso,
  TipoDocumentoGlossario,
} from "@/lib/types";

const CAMPO =
  "block w-full min-h-10 mt-1 px-3 border border-borda-campo rounded-campo bg-papel text-tinta text-sm";

type Painel =
  | { modo: "novo" }
  | { modo: "editar"; tipo: TipoCaso }
  | { modo: "historico"; tipo: TipoCaso };

/** Um item enquanto está sendo editado: `codigo` vazio é item que ainda não existe. */
type ItemEmEdicao = {
  codigo: string;
  nome: string;
  obrigatorio: boolean;
  tipo_documento: string;
  observacao: string;
};

const FORMULARIO_VAZIO = {
  nome: "",
  codigo: "",
  descricao: "",
  quando_usar: "",
  /** Uma pista por linha, no formato "expressão | peso". */
  pistas: "",
  itens: [] as ItemEmEdicao[],
  ativo: true,
  motivo: "",
};

const ROTULO_ACAO: Record<string, string> = {
  criado: "Criada",
  editado: "Editada",
  desativado: "Desativada",
  reativado: "Reativada",
};

const PESO_PADRAO = 6;

function semAcento(texto: string): string {
  return texto.normalize("NFD").replace(/[̀-ͯ]/g, "");
}

/** O mesmo código que o servidor gera quando o campo fica vazio. */
function sugerirCodigo(nome: string): string {
  const base = semAcento(nome.toLowerCase())
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const codigo = base && /^[a-z]/.test(base) ? base : `caso_${base}`.replace(/_+$/, "");
  return codigo.slice(0, 60).replace(/_+$/, "");
}

function quando(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("pt-BR");
}

/** "carreta | 14" por linha — é como quem cadastra lista as palavras do relato. */
function pistasComoTexto(tipo: TipoCaso): string {
  return tipo.pistas.map((p) => `${p.expressao} | ${p.peso}`).join("\n");
}

function lerPistas(texto: string): { expressao: string; peso: number }[] {
  return texto
    .split("\n")
    .map((linha) => {
      const [expressao, peso] = linha.split("|");
      return {
        expressao: (expressao ?? "").trim(),
        peso: Number.parseInt((peso ?? "").trim(), 10) || PESO_PADRAO,
      };
    })
    .filter((p) => p.expressao.length > 0);
}

function comoItensEmEdicao(itens: ItemTipoCaso[]): ItemEmEdicao[] {
  return itens.map((i) => ({
    codigo: i.codigo,
    nome: i.nome,
    obrigatorio: i.obrigatorio,
    tipo_documento: i.tipo_documento ?? "",
    observacao: i.observacao,
  }));
}

function mudancas(evento: EventoHistorico): string[] {
  const antes = evento.antes;
  const depois = evento.depois;
  if (!depois) return [];
  const lista = (registro: Record<string, unknown>, campo: string) =>
    ((registro[campo] as string[] | undefined) ?? []).join(", ");
  if (!antes) {
    const linhas = [`Nome: “${String(depois.nome ?? "")}”`];
    const itens = (depois.itens as string[] | undefined) ?? [];
    linhas.push(`Checklist: ${itens.length} item(ns)`);
    return linhas;
  }
  const linhas: string[] = [];
  if (antes.nome !== depois.nome) {
    linhas.push(`Nome: “${String(antes.nome)}” → “${String(depois.nome)}”`);
  }
  if (antes.descricao !== depois.descricao) linhas.push("Descrição alterada");
  if (antes.quando_usar !== depois.quando_usar) linhas.push("“Quando usar” alterado");
  if (lista(antes, "pistas") !== lista(depois, "pistas")) {
    const quantas = (registro: Record<string, unknown>) =>
      ((registro.pistas as string[] | undefined) ?? []).length;
    linhas.push(`Pistas da triagem: ${quantas(antes)} → ${quantas(depois)}`);
  }
  if (lista(antes, "itens") !== lista(depois, "itens")) {
    const itensAntes = (antes.itens as string[] | undefined) ?? [];
    const itensDepois = (depois.itens as string[] | undefined) ?? [];
    const entraram = itensDepois.filter((i) => !itensAntes.includes(i));
    const sairam = itensAntes.filter((i) => !itensDepois.includes(i));
    if (entraram.length) linhas.push(`Entraram no checklist: ${entraram.join("; ")}`);
    if (sairam.length) linhas.push(`Saíram do checklist: ${sairam.join("; ")}`);
  }
  return linhas;
}

export default function TiposDeCaso({ onVoltar }: { onVoltar: () => void }) {
  const sessao = useSessao();
  const podeEditar = !AUTH_ATIVA || sessao.modulos.includes("tipos_caso");

  const [tipos, setTipos] = useState<TipoCaso[]>([]);
  const [glossario, setGlossario] = useState<TipoDocumentoGlossario[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [recado, setRecado] = useState<string | null>(null);
  const [busca, setBusca] = useState("");
  const [mostrarDesativados, setMostrarDesativados] = useState(false);

  const [painel, setPainel] = useState<Painel>({ modo: "novo" });
  const [formulario, setFormulario] = useState(FORMULARIO_VAZIO);
  const [impacto, setImpacto] = useState<ImpactoTipoCaso | null>(null);
  const [eventos, setEventos] = useState<EventoHistorico[] | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [erroPainel, setErroPainel] = useState<string | null>(null);

  const recarregar = useCallback(async () => {
    setCarregando(true);
    try {
      setTipos(await listarTiposCaso(true));
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void recarregar();
    /* O checklist aponta para o glossário: sem a lista, o campo de tipo do item não
     * teria o que oferecer — e o servidor recusaria um código inventado. */
    listarTiposDocumento()
      .then(setGlossario)
      .catch(() => setGlossario([]));
  }, [recarregar]);

  const visiveis = useMemo(() => {
    const termo = semAcento(busca.trim().toLowerCase());
    return tipos
      .filter((t) => mostrarDesativados || t.ativo)
      .filter(
        (t) =>
          !termo ||
          [t.nome, t.codigo, t.descricao].some((valor) =>
            semAcento(valor.toLowerCase()).includes(termo),
          ),
      );
  }, [tipos, busca, mostrarDesativados]);

  const ativos = tipos.filter((t) => t.ativo).length;
  const doEscritorio = tipos.filter((t) => !t.sistema).length;

  function abrirNovo() {
    setPainel({ modo: "novo" });
    setFormulario(FORMULARIO_VAZIO);
    setImpacto(null);
    setErroPainel(null);
  }

  async function abrirEdicao(tipo: TipoCaso) {
    setPainel({ modo: "editar", tipo });
    setFormulario({
      nome: tipo.nome,
      codigo: tipo.codigo,
      descricao: tipo.descricao,
      quando_usar: tipo.quando_usar,
      pistas: pistasComoTexto(tipo),
      itens: comoItensEmEdicao(tipo.itens),
      ativo: tipo.ativo,
      motivo: "",
    });
    setImpacto(null);
    setErroPainel(null);
    try {
      setImpacto(await impactoTipoCaso(tipo.codigo));
    } catch (e) {
      setErroPainel(e instanceof Error ? e.message : String(e));
    }
  }

  async function abrirHistorico(tipo: TipoCaso) {
    setPainel({ modo: "historico", tipo });
    setEventos(null);
    setErroPainel(null);
    try {
      setEventos(await historicoTipoCaso(tipo.codigo));
    } catch (e) {
      setErroPainel(e instanceof Error ? e.message : String(e));
    }
  }

  // ------------------------------------------------------------ checklist

  function alterarItem(posicao: number, mudanca: Partial<ItemEmEdicao>) {
    setFormulario((atual) => ({
      ...atual,
      itens: atual.itens.map((item, i) => (i === posicao ? { ...item, ...mudanca } : item)),
    }));
  }

  function acrescentarItem() {
    setFormulario((atual) => ({
      ...atual,
      itens: [
        ...atual.itens,
        { codigo: "", nome: "", obrigatorio: false, tipo_documento: "", observacao: "" },
      ],
    }));
  }

  function removerItem(posicao: number) {
    const item = formulario.itens[posicao];
    const comDocumento = impacto?.itens_com_documento.find((i) => i.codigo === item?.codigo);
    if (
      comDocumento &&
      !window.confirm(
        `“${comDocumento.nome}” já tem ${comDocumento.documentos} documento(s) entregue(s). ` +
          "O servidor vai recusar a remoção. Tirar da lista mesmo assim?",
      )
    ) {
      return;
    }
    setFormulario((atual) => ({
      ...atual,
      itens: atual.itens.filter((_, i) => i !== posicao),
    }));
  }

  function moverItem(posicao: number, direcao: -1 | 1) {
    const destino = posicao + direcao;
    setFormulario((atual) => {
      if (destino < 0 || destino >= atual.itens.length) return atual;
      const itens = [...atual.itens];
      [itens[posicao], itens[destino]] = [itens[destino], itens[posicao]];
      return { ...atual, itens };
    });
  }

  // --------------------------------------------------------------- salvar

  function dadosDoFormulario() {
    return {
      nome: formulario.nome,
      descricao: formulario.descricao,
      quando_usar: formulario.quando_usar,
      pistas: lerPistas(formulario.pistas),
      itens: formulario.itens.map((item) => ({
        codigo: item.codigo,
        nome: item.nome,
        obrigatorio: item.obrigatorio,
        tipo_documento: item.tipo_documento || null,
        observacao: item.observacao,
      })),
    };
  }

  async function salvar() {
    if (painel.modo === "historico") return;
    setErroPainel(null);

    if (painel.modo === "editar" && impacto) {
      const avisos: string[] = [];
      if (impacto.casos > 0 && formulario.itens.length !== painel.tipo.itens.length) {
        avisos.push(impacto.efeitos.checklist);
      }
      if (painel.tipo.ativo && !formulario.ativo) avisos.push(impacto.efeitos.desativar);
      if (avisos.length > 0 && !window.confirm(`${avisos.join("\n\n")}\n\nSalvar a alteração?`)) {
        return;
      }
    }

    setSalvando(true);
    try {
      if (painel.modo === "novo") {
        const criado = await criarTipoCaso({
          ...dadosDoFormulario(),
          codigo: formulario.codigo.trim() || undefined,
        });
        setRecado(
          `“${criado.nome}” entrou no catálogo com o código ${criado.codigo}. ` +
            `Já aparece na criação de casos, com ${criado.itens.length} item(ns) no checklist.`,
        );
        setFormulario(FORMULARIO_VAZIO);
      } else {
        const salvo = await editarTipoCaso(painel.tipo.codigo, {
          ...dadosDoFormulario(),
          ativo: formulario.ativo,
          versao: painel.tipo.versao,
          motivo: formulario.motivo,
        });
        setRecado(`“${salvo.nome}” foi atualizada.`);
        setPainel({ modo: "editar", tipo: salvo });
        setFormulario((atual) => ({
          ...atual,
          itens: comoItensEmEdicao(salvo.itens),
          motivo: "",
        }));
        setImpacto(await impactoTipoCaso(salvo.codigo).catch(() => null));
      }
      await recarregar();
    } catch (e) {
      setErroPainel(e instanceof Error ? e.message : String(e));
      // Versão desatualizada: a lista recarrega, e reabrir a ação traz a atual.
      if (e instanceof ApiError && e.status === 409) void recarregar();
    } finally {
      setSalvando(false);
    }
  }

  const doSistema = painel.modo === "editar" && painel.tipo.sistema;
  const podeSalvar =
    formulario.nome.trim().length >= 2 &&
    (doSistema || formulario.itens.every((item) => item.nome.trim().length > 0));

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-5">
      <section className="overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-4 border-b border-borda bg-papel-2 px-5 py-4">
          <div className="min-w-0">
            <Botao variante="texto" onClick={onVoltar}>
              <ArrowLeft size={15} aria-hidden /> Voltar
            </Botao>
            <p className="mt-3 text-xs font-semibold uppercase tracking-[0.14em] text-tinta-3">
              Escritório
            </p>
            <div className="mt-1 flex min-w-0 items-center gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-campo border border-acao-borda bg-acao-clara text-acao">
                <Layers size={20} aria-hidden />
              </span>
              <h1 className="m-0 min-w-0 truncate text-[26px] font-semibold leading-[1.15] font-titulo text-tinta">
                Tipos de caso
              </h1>
            </div>
            <p className="mt-2 mb-0 max-w-[70ch] text-tinta-3 text-sm leading-[1.55]">
              As ações que o escritório aceita. Cada uma traz o checklist de documentos que o
              cliente vai receber e as pistas que a triagem usa para reconhecê-la no relato. O
              código fica gravado em cada caso e não muda.
            </p>
          </div>
          <div className="grid min-w-[240px] grid-cols-3 gap-2 rounded-campo border border-borda bg-papel p-2 text-center">
            <div className="min-w-0 px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Total</span>
              <strong className="block font-codigo text-lg text-tinta">{tipos.length}</strong>
            </div>
            <div className="min-w-0 border-x border-borda px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Ativas</span>
              <strong className="block font-codigo text-lg text-tinta">{ativos}</strong>
            </div>
            <div className="min-w-0 px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Criadas aqui</span>
              <strong className="block font-codigo text-lg text-tinta">{doEscritorio}</strong>
            </div>
          </div>
        </div>
      </section>

      {erro && <Aviso tom="critico">{erro}</Aviso>}
      {recado && <Aviso tom="ok">{recado}</Aviso>}

      <div className="grid min-w-0 grid-cols-[minmax(280px,360px)_minmax(0,1fr)] items-start gap-4 max-[920px]:grid-cols-1">
        <Cartao titulo="Ações cadastradas" className="min-w-0 overflow-hidden">
          <div className="mt-2 flex min-w-0 flex-col gap-3">
            <label className="min-w-0 text-xs text-tinta-3">
              Buscar por nome ou código
              <input
                type="search"
                className={CAMPO}
                value={busca}
                onChange={(evento) => setBusca(evento.target.value)}
              />
            </label>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Marcacao>
                <input
                  type="checkbox"
                  checked={mostrarDesativados}
                  onChange={(evento) => setMostrarDesativados(evento.target.checked)}
                />
                <span>Mostrar desativadas</span>
              </Marcacao>
              {podeEditar && painel.modo !== "novo" && (
                <Botao pequeno onClick={abrirNovo}>
                  <Plus size={14} aria-hidden /> Nova ação
                </Botao>
              )}
            </div>
          </div>

          {carregando && (
            <div
              className="mt-3 rounded-campo border border-borda bg-papel-2 px-4 py-5 text-center text-sm text-tinta-3"
              aria-live="polite"
            >
              Carregando o catálogo…
            </div>
          )}

          {!carregando && visiveis.length === 0 && (
            <Vazio className="mt-3">
              {tipos.length === 0 ? "O catálogo ainda não tem ações." : "Nenhuma ação encontrada."}
            </Vazio>
          )}

          <div className="mt-3 flex min-w-0 flex-col gap-2" aria-busy={carregando}>
            {visiveis.map((t) => (
              <div
                key={t.codigo}
                className="min-w-0 rounded-campo border border-borda bg-papel px-3 py-3"
              >
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <strong className="min-w-0 truncate text-tinta text-sm" title={t.nome}>
                    {t.nome}
                  </strong>
                  {t.sistema ? (
                    <Selo tom="neutro">do sistema</Selo>
                  ) : (
                    <Selo tom="info">do escritório</Selo>
                  )}
                  {!t.ativo && (
                    <Selo tom="atencao" simbolo="⏸">
                      desativada
                    </Selo>
                  )}
                </div>
                <p className="mt-1 mb-0 truncate font-codigo text-[11px] text-tinta-3" title={t.codigo}>
                  {t.codigo}
                </p>
                {!t.sistema && (
                  <p className="mt-1 mb-0 text-tinta-3 text-xs leading-[1.5]">
                    {t.itens.length} item(ns) no checklist · {t.total_obrigatorios} obrigatório(s)
                    {t.pistas.length > 0 ? ` · ${t.pistas.length} pista(s) de triagem` : ""}
                  </p>
                )}
                {t.descricao && (
                  <p className="mt-1 mb-0 line-clamp-2 text-tinta-3 text-xs leading-[1.5]" title={t.descricao}>
                    {t.descricao}
                  </p>
                )}
                <div className="mt-2 flex shrink-0 flex-wrap items-center gap-2">
                  {podeEditar && (
                    <Botao pequeno onClick={() => void abrirEdicao(t)}>
                      <PencilLine size={14} aria-hidden /> {t.sistema ? "Ligar/desligar" : "Editar"}
                    </Botao>
                  )}
                  <Botao pequeno variante="texto" onClick={() => void abrirHistorico(t)}>
                    <History size={14} aria-hidden /> Histórico
                  </Botao>
                </div>
              </div>
            ))}
          </div>
        </Cartao>

        <aside className="flex min-w-0 flex-col gap-4">
          {painel.modo === "historico" ? (
            <Cartao titulo={`Histórico — ${painel.tipo.nome}`} className="min-w-0 overflow-hidden">
              {erroPainel && <Aviso tom="critico">{erroPainel}</Aviso>}
              {!eventos && !erroPainel && <p className="text-sm text-tinta-3">Carregando…</p>}
              {eventos && eventos.length === 0 && (
                <p className="text-sm text-tinta-3">
                  Nenhuma alteração registrada — a ação está como o sistema a criou.
                </p>
              )}
              {eventos && eventos.length > 0 && (
                <ol className="list-none m-0 mt-2 p-0">
                  {eventos.map((evento) => (
                    <li
                      key={evento.id}
                      className="py-2 border-b border-borda last:border-b-0 text-xs leading-[1.5] text-tinta-2"
                    >
                      <strong className="text-tinta">{ROTULO_ACAO[evento.acao] ?? evento.acao}</strong>
                      {" · "}
                      {quando(evento.criado_em)}
                      {" · "}
                      {evento.usuario}
                      {mudancas(evento).map((linha) => (
                        <span key={linha} className="block">
                          {linha}
                        </span>
                      ))}
                      {evento.motivo && <span className="block text-tinta-3">Motivo: {evento.motivo}</span>}
                    </li>
                  ))}
                </ol>
              )}
              <div className="mt-3">
                <Botao variante="texto" pequeno onClick={abrirNovo}>
                  Fechar histórico
                </Botao>
              </div>
            </Cartao>
          ) : !podeEditar ? (
            <Cartao titulo="Somente consulta" className="min-w-0 overflow-hidden">
              <p className="m-0 text-sm leading-[1.55] text-tinta-2">
                Seu perfil consulta o catálogo. Criar e editar ações é de quem tem o módulo “Tipos
                de caso” — de fábrica, Advogado e Secretário.
              </p>
            </Cartao>
          ) : (
            <Cartao
              titulo={painel.modo === "novo" ? "Nova ação" : `Editar — ${painel.tipo.nome}`}
              subtitulo={
                painel.modo === "novo"
                  ? "A ação passa a aparecer na criação de casos e na triagem assim que for criada."
                  : undefined
              }
              className="min-w-0 overflow-hidden"
            >
              {doSistema && (
                <Aviso tom="info">
                  “{painel.tipo.nome}” vem do checklist em .docx do escritório. Aqui só dá para
                  ligar e desligar: o nome, o checklist e as pistas dela são conferidos contra o
                  documento original.
                </Aviso>
              )}

              <div className="mt-2 flex flex-col gap-3">
                <label className="text-xs text-tinta-3">
                  Nome da ação
                  <input
                    className={CAMPO}
                    maxLength={120}
                    value={formulario.nome}
                    disabled={salvando || doSistema}
                    onChange={(evento) =>
                      setFormulario((atual) => ({ ...atual, nome: evento.target.value }))
                    }
                  />
                </label>

                {painel.modo === "novo" ? (
                  <label className="text-xs text-tinta-3">
                    Código (opcional)
                    <input
                      className={`${CAMPO} font-codigo`}
                      maxLength={60}
                      value={formulario.codigo}
                      placeholder={sugerirCodigo(formulario.nome) || "gerado a partir do nome"}
                      disabled={salvando}
                      onChange={(evento) =>
                        setFormulario((atual) => ({ ...atual, codigo: evento.target.value }))
                      }
                    />
                    <AjudaCampo>
                      Fica gravado em cada caso e não muda depois. Vazio: gerado a partir do nome.
                    </AjudaCampo>
                  </label>
                ) : (
                  <p className="m-0 text-xs text-tinta-3">
                    Código <span className="font-codigo text-tinta">{painel.tipo.codigo}</span> —
                    não muda.
                  </p>
                )}

                <label className="text-xs text-tinta-3">
                  Descrição
                  <textarea
                    className={`${CAMPO} min-h-[72px] py-2 leading-[1.5]`}
                    maxLength={600}
                    value={formulario.descricao}
                    disabled={salvando || doSistema}
                    onChange={(evento) =>
                      setFormulario((atual) => ({ ...atual, descricao: evento.target.value }))
                    }
                  />
                  <AjudaCampo>O que o cliente lê ao abrir o caso.</AjudaCampo>
                </label>

                {!doSistema && (
                  <>
                    <label className="text-xs text-tinta-3">
                      Quando usar esta ação
                      <textarea
                        className={`${CAMPO} min-h-[72px] py-2 leading-[1.5]`}
                        maxLength={1200}
                        value={formulario.quando_usar}
                        disabled={salvando}
                        onChange={(evento) =>
                          setFormulario((atual) => ({ ...atual, quando_usar: evento.target.value }))
                        }
                      />
                      <AjudaCampo>
                        Vai para a instrução do modelo que lê o relato da entrevista. Escreva o que
                        separa esta ação das vizinhas — o empregador, o tipo de evento, o pedido.
                      </AjudaCampo>
                    </label>

                    <label className="text-xs text-tinta-3">
                      Pistas da triagem — uma por linha, no formato “expressão | peso”
                      <textarea
                        className={`${CAMPO} min-h-[96px] py-2 font-codigo leading-[1.5]`}
                        value={formulario.pistas}
                        disabled={salvando}
                        placeholder={"carreta | 14\nmotorista carreteiro | 12\ncapotou | 8"}
                        onChange={(evento) =>
                          setFormulario((atual) => ({ ...atual, pistas: evento.target.value }))
                        }
                      />
                      <AjudaCampo>
                        A triagem soma o peso de cada expressão encontrada no relato. Peso de 1 a
                        20; sem peso, vale {PESO_PADRAO}. Valem para as próximas triagens — as
                        entrevistas já enquadradas não mudam de categoria sozinhas.
                      </AjudaCampo>
                    </label>

                    <div className="text-xs text-tinta-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>Checklist de documentos</span>
                        <Botao pequeno onClick={acrescentarItem} disabled={salvando}>
                          <Plus size={14} aria-hidden /> Acrescentar item
                        </Botao>
                      </div>

                      {formulario.itens.length === 0 ? (
                        <Vazio className="mt-2">
                          Sem itens: o caso nasceria sem nenhum documento a pedir.
                        </Vazio>
                      ) : (
                        <div className="mt-2 flex flex-col gap-2">
                          {formulario.itens.map((item, posicao) => (
                            <div
                              key={item.codigo || `novo-${posicao}`}
                              className="min-w-0 rounded-campo border border-borda bg-papel-2 px-3 py-2"
                            >
                              <div className="flex min-w-0 items-center gap-2">
                                <span className="shrink-0 font-codigo text-[11px] text-tinta-3">
                                  {item.codigo || `#${posicao + 1}`}
                                </span>
                                <input
                                  className={`${CAMPO} mt-0`}
                                  maxLength={160}
                                  placeholder="Nome do documento pedido"
                                  value={item.nome}
                                  disabled={salvando}
                                  onChange={(evento) =>
                                    alterarItem(posicao, { nome: evento.target.value })
                                  }
                                />
                                <div className="flex shrink-0 items-center gap-1">
                                  <Botao
                                    pequeno
                                    variante="texto"
                                    aria-label="Subir item"
                                    disabled={salvando || posicao === 0}
                                    onClick={() => moverItem(posicao, -1)}
                                  >
                                    <ChevronUp size={14} aria-hidden />
                                  </Botao>
                                  <Botao
                                    pequeno
                                    variante="texto"
                                    aria-label="Descer item"
                                    disabled={salvando || posicao === formulario.itens.length - 1}
                                    onClick={() => moverItem(posicao, 1)}
                                  >
                                    <ChevronDown size={14} aria-hidden />
                                  </Botao>
                                  <Botao
                                    pequeno
                                    variante="texto"
                                    aria-label="Remover item"
                                    disabled={salvando}
                                    onClick={() => removerItem(posicao)}
                                  >
                                    <Trash2 size={14} aria-hidden />
                                  </Botao>
                                </div>
                              </div>

                              <div className="mt-2 flex min-w-0 flex-wrap items-center gap-3">
                                <Marcacao>
                                  <input
                                    type="checkbox"
                                    checked={item.obrigatorio}
                                    disabled={salvando}
                                    onChange={(evento) =>
                                      alterarItem(posicao, { obrigatorio: evento.target.checked })
                                    }
                                  />
                                  <span>Obrigatório</span>
                                </Marcacao>
                                <label className="min-w-[200px] flex-1 text-xs text-tinta-3">
                                  Tipo do glossário
                                  <select
                                    className={CAMPO}
                                    value={item.tipo_documento}
                                    disabled={salvando}
                                    onChange={(evento) =>
                                      alterarItem(posicao, { tipo_documento: evento.target.value })
                                    }
                                  >
                                    <option value="">sem tipo — conferência manual</option>
                                    {glossario.map((tipo) => (
                                      <option key={tipo.codigo} value={tipo.codigo}>
                                        {tipo.nome}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                              </div>

                              <input
                                className={CAMPO}
                                maxLength={600}
                                placeholder="Observação para quem envia o documento (opcional)"
                                value={item.observacao}
                                disabled={salvando}
                                onChange={(evento) =>
                                  alterarItem(posicao, { observacao: evento.target.value })
                                }
                              />
                            </div>
                          ))}
                        </div>
                      )}
                      <AjudaCampo>
                        O tipo do glossário é o que deixa o sistema conferir sozinho se o arquivo
                        enviado é mesmo o documento pedido. Item sem tipo é aceito e conferido por
                        quem recebe.
                      </AjudaCampo>
                    </div>
                  </>
                )}

                {painel.modo === "editar" && (
                  <>
                    <Marcacao>
                      <input
                        type="checkbox"
                        checked={formulario.ativo}
                        disabled={salvando}
                        onChange={(evento) =>
                          setFormulario((atual) => ({ ...atual, ativo: evento.target.checked }))
                        }
                      />
                      <span>Ativa — aparece na criação de casos e na triagem</span>
                    </Marcacao>

                    <label className="text-xs text-tinta-3">
                      Motivo da alteração (opcional — fica no histórico)
                      <input
                        className={CAMPO}
                        maxLength={600}
                        value={formulario.motivo}
                        disabled={salvando}
                        onChange={(evento) =>
                          setFormulario((atual) => ({ ...atual, motivo: evento.target.value }))
                        }
                      />
                    </label>

                    <div className="rounded-campo border border-borda bg-papel-2 px-3 py-2 text-xs leading-[1.5] text-tinta-2">
                      <strong className="block text-tinta">Impacto da alteração</strong>
                      {impacto ? (
                        <>
                          <span className="block">
                            {impacto.casos} caso(s) usam esta ação.
                          </span>
                          {impacto.itens_com_documento.length > 0 && (
                            <span className="block">
                              Itens que já receberam documento e não podem sair:{" "}
                              {impacto.itens_com_documento
                                .map((i) => `${i.nome} (${i.documentos})`)
                                .join("; ")}
                            </span>
                          )}
                          <span className="block mt-1">{impacto.efeitos.codigo}</span>
                          <span className="block">{impacto.efeitos.checklist}</span>
                          <span className="block">{impacto.efeitos.desativar}</span>
                        </>
                      ) : (
                        <span className="block">Calculando o uso desta ação…</span>
                      )}
                    </div>
                  </>
                )}

                {erroPainel && <Aviso tom="critico">{erroPainel}</Aviso>}

                <div className="flex gap-2 flex-wrap">
                  <Botao
                    variante="primario"
                    onClick={() => void salvar()}
                    disabled={salvando || !podeSalvar}
                  >
                    {painel.modo === "novo" ? <Plus size={15} aria-hidden /> : null}
                    {salvando
                      ? "Salvando…"
                      : painel.modo === "novo"
                        ? "Criar ação"
                        : "Salvar alteração"}
                  </Botao>
                  {painel.modo === "editar" && (
                    <Botao variante="texto" onClick={abrirNovo} disabled={salvando}>
                      Cancelar
                    </Botao>
                  )}
                </div>
              </div>
            </Cartao>
          )}
        </aside>
      </div>
    </div>
  );
}
