"use client";

/**
 * Glossário de documentos — os tipos que a classificação e a reclassificação usam.
 *
 * QUEM ENTRA AQUI
 *
 * A tela pede o módulo `glossario_documentos` (de fábrica: Advogado e Secretário,
 * ver `app/perfis.py`). Consultar a lista não pede nada: a reclassificação, dentro do
 * caso, lê o glossário para qualquer pessoa da equipe.
 *
 * O IMPACTO VEM ANTES DO SALVAR
 *
 * Ao abrir um tipo para edição, a tela busca quantos documentos e casos o usam e o
 * que muda com cada alteração. Renomear um tipo em uso e desativar pedem confirmação
 * com esse texto na frente. O código não aparece como campo editável: é ele que fica
 * gravado em cada documento classificado.
 *
 * DESATIVAR, NUNCA APAGAR
 *
 * Não existe botão de apagar. Tipo desativado sai das opções de classificação e os
 * documentos antigos continuam com ele — apagar levaria junto o significado deles.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, History, PencilLine, Plus, Tags } from "lucide-react";

import {
  AjudaCampo,
  Aviso,
  Botao,
  Cartao,
  Marcacao,
  Selo,
  Tabela,
  Td,
  Th,
  TrZebra,
  Vazio,
} from "@/components/ui/Basicos";
import {
  ApiError,
  criarTipoDocumento,
  editarTipoDocumento,
  historicoTipoDocumento,
  impactoTipoDocumento,
  listarCategorias,
  listarTiposDocumento,
} from "@/lib/api";
import { AUTH_ATIVA, useSessao } from "@/lib/auth";
import { invalidarTiposDocumento } from "@/lib/tiposDocumento";
import type {
  Categoria,
  EventoHistorico,
  ImpactoTipoDocumento,
  TipoDocumentoGlossario,
} from "@/lib/types";

const CAMPO =
  "block w-full min-h-10 mt-1 px-3 border border-borda-campo rounded-campo bg-papel text-tinta text-sm";

type Painel =
  | { modo: "novo" }
  | { modo: "editar"; tipo: TipoDocumentoGlossario }
  | { modo: "historico"; tipo: TipoDocumentoGlossario };

const FORMULARIO_VAZIO = {
  nome: "",
  codigo: "",
  descricao: "",
  sinonimos: "",
  ativo: true,
  motivo: "",
  /** Códigos das categorias (tipos de caso) em que o tipo é pedido. */
  categorias: [] as string[],
};

const ROTULO_ACAO: Record<string, string> = {
  criado: "Criado",
  editado: "Editado",
  desativado: "Desativado",
  reativado: "Reativado",
};

function semAcento(texto: string): string {
  return texto.normalize("NFD").replace(/[̀-ͯ]/g, "");
}

/** O mesmo código que o servidor gera quando o campo fica vazio. */
function sugerirCodigo(nome: string): string {
  const base = semAcento(nome.toLowerCase())
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const codigo = base && /^[a-z]/.test(base) ? base : `tipo_${base}`.replace(/_+$/, "");
  return codigo.slice(0, 60).replace(/_+$/, "");
}

function quando(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("pt-BR");
}

function mudancas(evento: EventoHistorico, nomeDoTipoDeCaso: (codigo: string) => string): string[] {
  const antes = evento.antes;
  const depois = evento.depois;
  if (!depois) return [];
  // Eventos anteriores aos tipos de caso não têm o campo: ausente é o mesmo que nenhum.
  const tiposDeCaso = (registro: Record<string, unknown>) =>
    ((registro.categorias as string[] | undefined) ?? []).map(nomeDoTipoDeCaso).join(", ");
  if (!antes) {
    const linhas = [`Nome: “${String(depois.nome ?? "")}”`];
    if (tiposDeCaso(depois)) linhas.push(`Pedido em: ${tiposDeCaso(depois)}`);
    return linhas;
  }
  const linhas: string[] = [];
  if (tiposDeCaso(antes) !== tiposDeCaso(depois)) {
    linhas.push(`Tipos de caso: ${tiposDeCaso(antes) || "nenhum"} → ${tiposDeCaso(depois) || "nenhum"}`);
  }
  if (antes.nome !== depois.nome) {
    linhas.push(`Nome: “${String(antes.nome)}” → “${String(depois.nome)}”`);
  }
  if (antes.descricao !== depois.descricao) linhas.push("Descrição alterada");
  const sinonimosAntes = ((antes.sinonimos as string[] | undefined) ?? []).join(", ");
  const sinonimosDepois = ((depois.sinonimos as string[] | undefined) ?? []).join(", ");
  if (sinonimosAntes !== sinonimosDepois) {
    linhas.push(`Sinônimos: ${sinonimosAntes || "nenhum"} → ${sinonimosDepois || "nenhum"}`);
  }
  return linhas;
}

export default function GlossarioDocumentos({ onVoltar }: { onVoltar: () => void }) {
  const sessao = useSessao();
  const podeEditar = !AUTH_ATIVA || sessao.modulos.includes("glossario_documentos");

  const [tipos, setTipos] = useState<TipoDocumentoGlossario[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [recado, setRecado] = useState<string | null>(null);
  const [busca, setBusca] = useState("");
  const [mostrarDesativados, setMostrarDesativados] = useState(false);

  const [painel, setPainel] = useState<Painel>({ modo: "novo" });
  const [formulario, setFormulario] = useState(FORMULARIO_VAZIO);
  const [impacto, setImpacto] = useState<ImpactoTipoDocumento | null>(null);
  const [eventos, setEventos] = useState<EventoHistorico[] | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [erroPainel, setErroPainel] = useState<string | null>(null);
  /* Da mesma rota que monta o checklist dos casos: a tabela mostra exatamente os tipos
   * de caso que existem e o que cada checklist já pede. */
  const [tiposDeCaso, setTiposDeCaso] = useState<Categoria[]>([]);
  const [erroTiposDeCaso, setErroTiposDeCaso] = useState<string | null>(null);

  const recarregar = useCallback(async () => {
    setCarregando(true);
    try {
      setTipos(await listarTiposDocumento(true));
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void recarregar();
    listarCategorias()
      .then((lista) => {
        setTiposDeCaso(lista);
        setErroTiposDeCaso(null);
      })
      .catch((e: unknown) => setErroTiposDeCaso(e instanceof Error ? e.message : String(e)));
  }, [recarregar]);

  const nomeDoTipoDeCaso = (codigo: string) =>
    tiposDeCaso.find((categoria) => categoria.codigo === codigo)?.nome ?? codigo;

  const visiveis = useMemo(() => {
    const termo = semAcento(busca.trim().toLowerCase());
    return tipos
      .filter((t) => mostrarDesativados || t.ativo)
      .filter(
        (t) =>
          !termo ||
          [t.nome, t.codigo, t.descricao, ...t.sinonimos].some((valor) =>
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

  async function abrirEdicao(tipo: TipoDocumentoGlossario) {
    setPainel({ modo: "editar", tipo });
    setFormulario({
      nome: tipo.nome,
      codigo: tipo.codigo,
      descricao: tipo.descricao,
      sinonimos: tipo.sinonimos.join(", "),
      ativo: tipo.ativo,
      motivo: "",
      categorias: tipo.categorias ?? [],
    });
    setImpacto(null);
    setErroPainel(null);
    try {
      setImpacto(await impactoTipoDocumento(tipo.codigo));
    } catch (e) {
      setErroPainel(e instanceof Error ? e.message : String(e));
    }
  }

  async function abrirHistorico(tipo: TipoDocumentoGlossario) {
    setPainel({ modo: "historico", tipo });
    setEventos(null);
    setErroPainel(null);
    try {
      setEventos(await historicoTipoDocumento(tipo.codigo));
    } catch (e) {
      setErroPainel(e instanceof Error ? e.message : String(e));
    }
  }

  const sinonimos = () =>
    formulario.sinonimos
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

  async function salvar() {
    if (painel.modo === "historico") return;
    setErroPainel(null);

    if (painel.modo === "editar") {
      const avisos: string[] = [];
      if (impacto && formulario.nome.trim() !== painel.tipo.nome && impacto.documentos > 0) {
        avisos.push(impacto.efeitos.renomear);
      }
      if (impacto && painel.tipo.ativo && !formulario.ativo) {
        avisos.push(impacto.efeitos.desativar);
      }
      if (avisos.length > 0 && !window.confirm(`${avisos.join("\n\n")}\n\nSalvar a alteração?`)) {
        return;
      }
    }

    setSalvando(true);
    try {
      if (painel.modo === "novo") {
        const criado = await criarTipoDocumento({
          nome: formulario.nome,
          codigo: formulario.codigo.trim() || undefined,
          descricao: formulario.descricao,
          sinonimos: sinonimos(),
          categorias: formulario.categorias,
        });
        const pedidoEm = criado.categorias?.length
          ? ` Passa a ser pedido no checklist de: ${criado.categorias.map(nomeDoTipoDeCaso).join(", ")}.`
          : " Não é pedido em nenhum checklist — marque os tipos de caso para que apareça.";
        setRecado(`“${criado.nome}” entrou no glossário com o código ${criado.codigo}.${pedidoEm}`);
        setFormulario(FORMULARIO_VAZIO);
      } else {
        const salvo = await editarTipoDocumento(painel.tipo.codigo, {
          nome: formulario.nome,
          descricao: formulario.descricao,
          sinonimos: sinonimos(),
          ativo: formulario.ativo,
          versao: painel.tipo.versao,
          motivo: formulario.motivo,
          categorias: formulario.categorias,
        });
        setRecado(`“${salvo.nome}” foi atualizado.`);
        setPainel({ modo: "editar", tipo: salvo });
        setFormulario((atual) => ({ ...atual, motivo: "" }));
        setImpacto(await impactoTipoDocumento(salvo.codigo).catch(() => null));
      }
      invalidarTiposDocumento();
      await recarregar();
    } catch (e) {
      setErroPainel(e instanceof Error ? e.message : String(e));
      // Versão desatualizada: a lista recarrega, e reabrir o tipo traz a atual.
      if (e instanceof ApiError && e.status === 409) void recarregar();
    } finally {
      setSalvando(false);
    }
  }

  const codigoEmEdicao = painel.modo === "novo" ? null : painel.tipo.codigo;

  /** O checklist do escritório já pede este tipo: a linha aparece marcada e travada. */
  function pedidoNoChecklistPadrao(categoria: Categoria): boolean {
    return (
      codigoEmEdicao !== null &&
      categoria.itens.some(
        (item) => !item.do_glossario && (item.tipo_documento ?? item.tipo_ocr) === codigoEmEdicao,
      )
    );
  }

  function alternarTipoDeCaso(codigo: string, marcado: boolean) {
    setFormulario((atual) => {
      const outros = atual.categorias.filter((c) => c !== codigo);
      return { ...atual, categorias: marcado ? [...outros, codigo] : outros };
    });
  }

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
                <Tags size={20} aria-hidden />
              </span>
              <h1 className="m-0 min-w-0 truncate text-[26px] font-semibold leading-[1.15] font-titulo text-tinta">
                Glossário de documentos
              </h1>
            </div>
            <p className="mt-2 mb-0 max-w-[70ch] text-tinta-3 text-sm leading-[1.55]">
              Os tipos de documento que a leitura automática e a reclassificação usam. O código de
              cada tipo fica gravado nos documentos e não muda; nome, descrição e sinônimos se
              editam aqui.
            </p>
          </div>
          <div className="grid min-w-[240px] grid-cols-3 gap-2 rounded-campo border border-borda bg-papel p-2 text-center">
            <div className="min-w-0 px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Total</span>
              <strong className="block font-codigo text-lg text-tinta">{tipos.length}</strong>
            </div>
            <div className="min-w-0 border-x border-borda px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Ativos</span>
              <strong className="block font-codigo text-lg text-tinta">{ativos}</strong>
            </div>
            <div className="min-w-0 px-2 py-1">
              <span className="block truncate text-[11px] text-tinta-3">Do escritório</span>
              <strong className="block font-codigo text-lg text-tinta">{doEscritorio}</strong>
            </div>
          </div>
        </div>
      </section>

      {erro && <Aviso tom="critico">{erro}</Aviso>}
      {recado && <Aviso tom="ok">{recado}</Aviso>}

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(280px,380px)] items-start gap-4 max-[920px]:grid-cols-1">
        <Cartao titulo="Tipos cadastrados" className="min-w-0 overflow-hidden">
          <div className="mt-2 flex min-w-0 flex-wrap items-end gap-3">
            <label className="min-w-[200px] flex-1 text-xs text-tinta-3">
              Buscar por nome, código ou sinônimo
              <input
                type="search"
                className={CAMPO}
                value={busca}
                onChange={(evento) => setBusca(evento.target.value)}
              />
            </label>
            <Marcacao>
              <input
                type="checkbox"
                checked={mostrarDesativados}
                onChange={(evento) => setMostrarDesativados(evento.target.checked)}
              />
              <span>Mostrar desativados</span>
            </Marcacao>
          </div>

          {carregando && (
            <div
              className="mt-3 rounded-campo border border-borda bg-papel-2 px-4 py-5 text-center text-sm text-tinta-3"
              aria-live="polite"
            >
              Carregando o glossário…
            </div>
          )}

          {!carregando && visiveis.length === 0 && (
            <Vazio className="mt-3">
              {tipos.length === 0 ? "O glossário ainda não tem tipos." : "Nenhum tipo encontrado."}
            </Vazio>
          )}

          <div className="mt-3 flex min-w-0 flex-col gap-2" aria-busy={carregando}>
            {visiveis.map((t) => (
              <div
                key={t.codigo}
                className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-4 rounded-campo border border-borda bg-papel px-3 py-3 max-[720px]:grid-cols-1"
              >
                <div className="min-w-0">
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
                        desativado
                      </Selo>
                    )}
                  </div>
                  <p className="mt-1 mb-0 truncate font-codigo text-[11px] text-tinta-3" title={t.codigo}>
                    {t.codigo}
                    {t.itens_checklist > 0 ? ` · pedido em ${t.itens_checklist} item(ns) de checklist` : ""}
                  </p>
                  {t.descricao && (
                    <p className="mt-1 mb-0 line-clamp-2 text-tinta-3 text-xs leading-[1.5]" title={t.descricao}>
                      {t.descricao}
                    </p>
                  )}
                  {t.sinonimos.length > 0 && (
                    <p className="mt-1 mb-0 text-tinta-3 text-xs leading-[1.5]">
                      Também chamado: {t.sinonimos.join(", ")}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 gap-2 items-center flex-wrap max-[720px]:justify-end">
                  {podeEditar && (
                    <Botao pequeno onClick={() => void abrirEdicao(t)}>
                      <PencilLine size={14} aria-hidden /> Editar
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
                  Nenhuma alteração registrada — o tipo está como o sistema o criou.
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
                      {mudancas(evento, nomeDoTipoDeCaso).map((linha) => (
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
                Seu perfil consulta o glossário. Criar e editar tipos é de quem tem o módulo
                “Glossário de documentos” — de fábrica, Advogado e Secretário.
              </p>
            </Cartao>
          ) : (
            <Cartao
              titulo={painel.modo === "novo" ? "Novo tipo" : `Editar — ${painel.tipo.nome}`}
              subtitulo={
                painel.modo === "novo"
                  ? "O tipo passa a aparecer nas opções de reclassificação assim que for criado, e no checklist dos tipos de caso marcados abaixo."
                  : undefined
              }
              className="min-w-0 overflow-hidden"
            >
              <div className="mt-2 flex flex-col gap-3">
                <label className="text-xs text-tinta-3">
                  Nome
                  <input
                    className={CAMPO}
                    maxLength={120}
                    value={formulario.nome}
                    disabled={salvando}
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
                      Fica gravado em cada documento classificado e não muda depois. Vazio: gerado a
                      partir do nome.
                    </AjudaCampo>
                  </label>
                ) : (
                  <p className="m-0 text-xs text-tinta-3">
                    Código <span className="font-codigo text-tinta">{painel.tipo.codigo}</span> — não
                    muda.
                  </p>
                )}

                <label className="text-xs text-tinta-3">
                  Descrição
                  <textarea
                    className={`${CAMPO} min-h-[72px] py-2 leading-[1.5]`}
                    maxLength={600}
                    value={formulario.descricao}
                    disabled={salvando}
                    onChange={(evento) =>
                      setFormulario((atual) => ({ ...atual, descricao: evento.target.value }))
                    }
                  />
                </label>

                <label className="text-xs text-tinta-3">
                  Sinônimos, separados por vírgula
                  <input
                    className={CAMPO}
                    value={formulario.sinonimos}
                    disabled={salvando}
                    onChange={(evento) =>
                      setFormulario((atual) => ({ ...atual, sinonimos: evento.target.value }))
                    }
                  />
                  <AjudaCampo>Entram na leitura automática dos próximos documentos.</AjudaCampo>
                </label>

                <div className="text-xs text-tinta-3">
                  Tipos de caso em que este documento é pedido
                  {erroTiposDeCaso ? (
                    <div className="mt-1">
                      <Aviso tom="critico">
                        Não foi possível carregar os tipos de caso: {erroTiposDeCaso}
                      </Aviso>
                    </div>
                  ) : tiposDeCaso.length === 0 ? (
                    <p className="mt-1 mb-0">Carregando os tipos de caso…</p>
                  ) : (
                    <div className="mt-1 max-w-full overflow-x-auto rounded-campo border border-borda">
                      <Tabela>
                        <thead>
                          <tr>
                            <Th className="w-12">Pedir</Th>
                            <Th>Tipo de caso</Th>
                          </tr>
                        </thead>
                        <tbody>
                          {tiposDeCaso.map((categoria) => {
                            const padrao = pedidoNoChecklistPadrao(categoria);
                            const id = `tipo-de-caso-${categoria.codigo}`;
                            return (
                              <TrZebra key={categoria.codigo}>
                                <Td>
                                  <input
                                    id={id}
                                    type="checkbox"
                                    checked={padrao || formulario.categorias.includes(categoria.codigo)}
                                    disabled={salvando || padrao}
                                    onChange={(evento) =>
                                      alternarTipoDeCaso(categoria.codigo, evento.target.checked)
                                    }
                                  />
                                </Td>
                                <Td>
                                  <label htmlFor={id} className="text-tinta">
                                    {categoria.nome}
                                  </label>
                                  {padrao && (
                                    <span className="block text-[11px] text-tinta-3">
                                      Já pedido no checklist padrão.
                                    </span>
                                  )}
                                </Td>
                              </TrZebra>
                            );
                          })}
                        </tbody>
                      </Tabela>
                    </div>
                  )}
                  <AjudaCampo>
                    Entra como item opcional no fim do checklist desses casos — inclusive dos já
                    abertos.
                  </AjudaCampo>
                </div>

                {painel.modo === "editar" && (
                  <>
                    <Marcacao>
                      <input
                        type="checkbox"
                        checked={formulario.ativo}
                        disabled={
                          salvando || (painel.tipo.ativo && impacto?.pode_desativar === false)
                        }
                        onChange={(evento) =>
                          setFormulario((atual) => ({ ...atual, ativo: evento.target.checked }))
                        }
                      />
                      <span>Ativo — aparece nas opções de classificação</span>
                    </Marcacao>
                    {painel.tipo.ativo && impacto?.bloqueio_desativacao && (
                      <AjudaCampo className="mt-0">{impacto.bloqueio_desativacao}</AjudaCampo>
                    )}

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
                            {impacto.documentos} documento(s) em {impacto.casos} caso(s) usam este
                            tipo; {impacto.correcoes} correção(ões) registrada(s).
                          </span>
                          {impacto.itens_checklist.length > 0 && (
                            <span className="block">
                              Pedido em:{" "}
                              {impacto.itens_checklist
                                .slice(0, 6)
                                .map((i) => `${i.nome} (${i.categoria_nome})`)
                                .join("; ")}
                              {impacto.itens_checklist.length > 6
                                ? ` e mais ${impacto.itens_checklist.length - 6}`
                                : ""}
                            </span>
                          )}
                          <span className="block mt-1">{impacto.efeitos.codigo}</span>
                          <span className="block">{impacto.efeitos.renomear}</span>
                          <span className="block">{impacto.efeitos.sinonimos}</span>
                        </>
                      ) : (
                        <span className="block">Calculando o uso deste tipo…</span>
                      )}
                    </div>
                  </>
                )}

                {erroPainel && <Aviso tom="critico">{erroPainel}</Aviso>}

                <div className="flex gap-2 flex-wrap">
                  <Botao
                    variante="primario"
                    onClick={() => void salvar()}
                    disabled={salvando || formulario.nome.trim().length < 2}
                  >
                    {painel.modo === "novo" ? <Plus size={15} aria-hidden /> : null}
                    {salvando
                      ? "Salvando…"
                      : painel.modo === "novo"
                        ? "Criar tipo"
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
