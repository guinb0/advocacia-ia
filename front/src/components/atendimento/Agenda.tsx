"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarPlus, Copy, RefreshCw } from "lucide-react";

import { Aviso, AjudaCampo, Botao, Campo, Marcacao, RotuloCampo, Selo, Vazio } from "@/components/ui/Basicos";
import {
  agendarAtendimento,
  cancelarAtendimento,
  editarAtendimento,
  enviarConfirmacaoAtendimento,
  listarAtendimentos,
  marcarFaltaAtendimento,
  reagendarAtendimento,
  ROTULO_ESTADO,
  type Atendimento,
  type ConfigLembretes,
  type EstadoAtendimento,
} from "@/lib/api/atendimentos";
import { definirAtendimentoAtivo } from "@/lib/atendimentoAtivo";
import { formatarTelefone } from "@/lib/formato";
import type { Tela } from "@/lib/telas";

/* A agenda dos atendimentos: quem vem, quando, e o que fazer com cada um.
 *
 * O estado é do servidor (`acervo_atendimentos`); esta tela só pede transições.
 * Cada edição leva a `versao` lida — duas pessoas editando o mesmo horário não
 * se sobrescrevem em silêncio. */

const ATUALIZAR_MS = 15_000;

const TOM_ESTADO: Record<EstadoAtendimento, "neutro" | "info" | "ok" | "atencao" | "critico"> = {
  AGENDADA: "neutro",
  CLIENTE_AGUARDANDO: "critico",
  EM_ATENDIMENTO: "info",
  ENTREVISTA_FINALIZADA: "info",
  ANALISE_JURIDICA: "info",
  AGUARDANDO_CONFIRMACAO_ACOES: "atencao",
  QUALIFICACAO: "info",
  AVALIACAO_ESCRITORIO: "info",
  DOCUMENTACAO_PENDENTE: "ok",
  CONCLUIDA: "ok",
  CLIENTE_FALTOU: "atencao",
  CANCELADA: "neutro",
};

const ANTES_DA_ENTREVISTA: EstadoAtendimento[] = ["AGENDADA", "CLIENTE_AGUARDANDO", "CLIENTE_FALTOU"];
const EM_CURSO: EstadoAtendimento[] = [
  "EM_ATENDIMENTO",
  "ENTREVISTA_FINALIZADA",
  "ANALISE_JURIDICA",
  "AGUARDANDO_CONFIRMACAO_ACOES",
  "QUALIFICACAO",
  "AVALIACAO_ESCRITORIO",
];

type Periodo = "hoje" | "semana" | "mes";

function inicioDoDia(d: Date): Date {
  const c = new Date(d);
  c.setHours(0, 0, 0, 0);
  return c;
}

function intervalo(periodo: Periodo): { de: string; ate: string } {
  const de = inicioDoDia(new Date());
  const ate = new Date(de);
  ate.setDate(ate.getDate() + (periodo === "hoje" ? 1 : periodo === "semana" ? 7 : 31));
  return { de: de.toISOString(), ate: ate.toISOString() };
}

function lerData(iso: string | null): Date | null {
  if (!iso) return null;
  const texto = /[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(texto);
  return Number.isNaN(d.getTime()) ? null : d;
}

function paraCampos(iso: string | null): { data: string; hora: string } {
  const d = lerData(iso);
  if (!d) return { data: "", hora: "" };
  const p = (n: number) => String(n).padStart(2, "0");
  return { data: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`, hora: `${p(d.getHours())}:${p(d.getMinutes())}` };
}

function rotuloDia(d: Date): string {
  const hoje = inicioDoDia(new Date());
  const dia = inicioDoDia(d);
  const diff = Math.round((dia.getTime() - hoje.getTime()) / 86_400_000);
  if (diff === 0) return "Hoje";
  if (diff === 1) return "Amanhã";
  if (diff === -1) return "Ontem";
  return d.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "2-digit" });
}

interface Formulario {
  id: string | null;
  versao: number;
  cliente: string;
  telefone: string;
  data: string;
  hora: string;
  duracao: number;
  observacao: string;
  lembretesPadrao: boolean;
  lembretes: ConfigLembretes;
  enviarConfirmacao: boolean;
}

const LEMBRETES_VAZIOS: ConfigLembretes = { ativo: true, intervalo_dias: 1, minutos_antes_no_dia: [60] };

function formularioNovo(): Formulario {
  const amanha = new Date();
  amanha.setDate(amanha.getDate() + 1);
  amanha.setHours(9, 0, 0, 0);
  return {
    id: null,
    versao: 0,
    cliente: "",
    telefone: "",
    ...paraCampos(amanha.toISOString()),
    duracao: 60,
    observacao: "",
    lembretesPadrao: true,
    lembretes: LEMBRETES_VAZIOS,
    enviarConfirmacao: true,
  };
}

function formularioDe(a: Atendimento): Formulario {
  return {
    id: a.id,
    versao: a.versao,
    cliente: a.cliente,
    telefone: formatarTelefone(a.telefone || ""),
    ...paraCampos(a.data_hora),
    duracao: a.duracao_min || 60,
    observacao: a.observacao || "",
    lembretesPadrao: !a.config_lembretes,
    lembretes: a.config_lembretes ?? LEMBRETES_VAZIOS,
    enviarConfirmacao: false,
  };
}

function FormularioAgendamento({
  inicial,
  onSalvo,
  onCancelar,
}: {
  inicial: Formulario;
  onSalvo: () => void;
  onCancelar: () => void;
}) {
  const [f, setF] = useState(inicial);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [minutosTexto, setMinutosTexto] = useState(inicial.lembretes.minutos_antes_no_dia.join(", "));
  const altera = <K extends keyof Formulario>(k: K, v: Formulario[K]) => setF((atual) => ({ ...atual, [k]: v }));

  const salvar = async () => {
    setErro(null);
    if (f.cliente.trim().length < 2) return setErro("Informe o nome do cliente.");
    if (!f.data || !f.hora) return setErro("Informe data e hora.");
    const quando = new Date(`${f.data}T${f.hora}:00`);
    if (Number.isNaN(quando.getTime())) return setErro("Data ou hora inválida.");
    const minutos = minutosTexto
      .split(/[,;\s]+/)
      .map((t) => parseInt(t, 10))
      .filter((n) => Number.isFinite(n) && n > 0 && n <= 1440)
      .slice(0, 6);
    const lembretes = f.lembretesPadrao ? null : { ...f.lembretes, minutos_antes_no_dia: minutos };
    setSalvando(true);
    try {
      if (f.id) {
        await editarAtendimento(f.id, {
          versao: f.versao,
          cliente: f.cliente.trim(),
          telefone: f.telefone,
          data_hora: quando.toISOString(),
          observacao: f.observacao,
          ...(lembretes ? { lembretes } : { usar_lembretes_padrao: true }),
        });
      } else {
        await agendarAtendimento({
          cliente: f.cliente.trim(),
          telefone: f.telefone,
          data_hora: quando.toISOString(),
          duracao_min: f.duracao,
          observacao: f.observacao,
          lembretes,
          enviar_confirmacao: f.enviarConfirmacao,
        });
      }
      onSalvo();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível salvar o agendamento.");
    } finally {
      setSalvando(false);
    }
  };

  return (
    <section className="mb-5 rounded-cartao border border-acao-borda bg-papel p-5 shadow-cartao">
      <h3 className="m-0 text-lg font-semibold text-tinta">{f.id ? "Editar agendamento" : "Novo agendamento"}</h3>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <RotuloCampo htmlFor="ag-cliente">Cliente</RotuloCampo>
          <Campo id="ag-cliente" value={f.cliente} onChange={(e) => altera("cliente", e.target.value)} autoComplete="off" />
        </div>
        <div>
          <RotuloCampo htmlFor="ag-telefone">WhatsApp</RotuloCampo>
          <Campo
            id="ag-telefone"
            inputMode="tel"
            placeholder="(DDD) 00000-0000"
            value={f.telefone}
            onChange={(e) => altera("telefone", formatarTelefone(e.target.value))}
          />
          <AjudaCampo>Sem telefone não há confirmação nem lembretes automáticos.</AjudaCampo>
        </div>
        <div>
          <RotuloCampo htmlFor="ag-data">Data</RotuloCampo>
          <Campo id="ag-data" type="date" value={f.data} onChange={(e) => altera("data", e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <RotuloCampo htmlFor="ag-hora">Hora</RotuloCampo>
            <Campo id="ag-hora" type="time" value={f.hora} onChange={(e) => altera("hora", e.target.value)} />
          </div>
          {!f.id && (
            <div>
              <RotuloCampo htmlFor="ag-duracao">Duração (min)</RotuloCampo>
              <Campo
                id="ag-duracao"
                type="number"
                min={10}
                max={480}
                value={f.duracao}
                onChange={(e) => altera("duracao", Math.max(10, Math.min(480, Number(e.target.value) || 60)))}
              />
            </div>
          )}
        </div>
        <div className="sm:col-span-2">
          <RotuloCampo htmlFor="ag-obs">Observação</RotuloCampo>
          <Campo id="ag-obs" value={f.observacao} onChange={(e) => altera("observacao", e.target.value)} />
        </div>
      </div>

      <div className="mt-4 rounded-campo border border-borda bg-papel-2 px-4 py-3">
        <Marcacao>
          <input type="checkbox" checked={f.lembretesPadrao} onChange={(e) => altera("lembretesPadrao", e.target.checked)} />
          Usar os lembretes padrão do escritório (WhatsApp › Lembretes)
        </Marcacao>
        {!f.lembretesPadrao && (
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Marcacao>
              <input
                type="checkbox"
                checked={f.lembretes.ativo}
                onChange={(e) => altera("lembretes", { ...f.lembretes, ativo: e.target.checked })}
              />
              Enviar lembretes
            </Marcacao>
            <div>
              <RotuloCampo htmlFor="ag-dias">Lembrar a cada (dias)</RotuloCampo>
              <Campo
                id="ag-dias"
                type="number"
                min={0}
                max={30}
                value={f.lembretes.intervalo_dias}
                onChange={(e) =>
                  altera("lembretes", { ...f.lembretes, intervalo_dias: Math.max(0, Math.min(30, Number(e.target.value) || 0)) })
                }
              />
            </div>
            <div>
              <RotuloCampo htmlFor="ag-minutos">No dia: minutos antes</RotuloCampo>
              <Campo id="ag-minutos" value={minutosTexto} placeholder="120, 30" onChange={(e) => setMinutosTexto(e.target.value)} />
            </div>
          </div>
        )}
      </div>

      {!f.id && (
        <div className="mt-3">
          <Marcacao>
            <input type="checkbox" checked={f.enviarConfirmacao} onChange={(e) => altera("enviarConfirmacao", e.target.checked)} />
            Enviar a confirmação por WhatsApp agora
          </Marcacao>
        </div>
      )}

      {erro && (
        <div className="mt-3">
          <Aviso tom="critico">{erro}</Aviso>
        </div>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <Botao variante="primario" onClick={() => void salvar()} carregando={salvando} textoCarregando="Salvando…">
          {f.id ? "Salvar alterações" : "Agendar"}
        </Botao>
        <Botao variante="discreto" onClick={onCancelar} disabled={salvando}>
          Cancelar
        </Botao>
      </div>
    </section>
  );
}

export default function Agenda({
  onNavegar,
  onAbrirCaso,
}: {
  onNavegar: (tela: Tela) => void;
  onAbrirCaso: (casoId: string) => void;
}) {
  const [periodo, setPeriodo] = useState<Periodo>("semana");
  const [itens, setItens] = useState<Atendimento[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [formulario, setFormulario] = useState<Formulario | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      setItens(await listarAtendimentos(intervalo(periodo)));
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível carregar a agenda.");
    } finally {
      setCarregando(false);
    }
  }, [periodo]);

  useEffect(() => {
    setCarregando(true);
    void carregar();
    const t = window.setInterval(() => void carregar(), ATUALIZAR_MS);
    return () => window.clearInterval(t);
  }, [carregar]);

  const porDia = useMemo(() => {
    const grupos = new Map<string, { rotulo: string; itens: Atendimento[] }>();
    const ordenados = [...itens].sort((a, b) => (lerData(a.data_hora)?.getTime() ?? 0) - (lerData(b.data_hora)?.getTime() ?? 0));
    for (const item of ordenados) {
      const d = lerData(item.data_hora);
      const chave = d ? inicioDoDia(d).toISOString() : "sem-data";
      if (!grupos.has(chave)) grupos.set(chave, { rotulo: d ? rotuloDia(d) : "Sem horário", itens: [] });
      grupos.get(chave)!.itens.push(item);
    }
    return [...grupos.values()];
  }, [itens]);

  const agir = async (id: string, acao: () => Promise<unknown>, sucesso?: string) => {
    setOcupado(id);
    setErro(null);
    setAviso(null);
    try {
      await acao();
      if (sucesso) setAviso(sucesso);
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "A ação não foi concluída.");
    } finally {
      setOcupado(null);
    }
  };

  const entrar = (a: Atendimento) => {
    definirAtendimentoAtivo({ id: a.id, sala: a.sala, cliente: a.cliente, telefone: a.telefone });
    onNavegar("entrevista");
  };

  const enviarConfirmacao = (a: Atendimento, forcar: boolean) =>
    void agir(a.id, async () => {
      const r = await enviarConfirmacaoAtendimento(a.id, forcar);
      if (r.status === "ja_enviado") throw new Error("A confirmação já foi enviada. Use “Reenviar” para mandar de novo.");
      if (!r.enviado) throw new Error(r.motivo || `Confirmação não enviada (${r.status}).`);
    }, "Confirmação enviada pelo WhatsApp.");

  const copiar = (texto: string) => {
    void navigator.clipboard?.writeText(texto).then(() => setAviso("Link do cliente copiado."));
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {(["hoje", "semana", "mes"] as Periodo[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriodo(p)}
              className={`rounded-campo border px-3 py-2 text-xs font-semibold ${
                periodo === p ? "border-tinta bg-tinta text-papel" : "border-borda-forte bg-papel text-tinta-2 hover:border-tinta"
              }`}
            >
              {p === "hoje" ? "Hoje" : p === "semana" ? "Próximos 7 dias" : "Próximos 30 dias"}
            </button>
          ))}
          <Botao variante="discreto" pequeno onClick={() => void carregar()} aria-label="Atualizar">
            <RefreshCw aria-hidden className="size-4" />
          </Botao>
        </div>
        <Botao variante="primario" onClick={() => setFormulario(formularioNovo())}>
          <CalendarPlus aria-hidden className="size-4" /> Novo agendamento
        </Botao>
      </div>

      {formulario && (
        <FormularioAgendamento
          key={formulario.id ?? "novo"}
          inicial={formulario}
          onCancelar={() => setFormulario(null)}
          onSalvo={() => {
            setFormulario(null);
            setAviso("Agendamento salvo.");
            void carregar();
          }}
        />
      )}

      {erro && (
        <div className="mb-3">
          <Aviso tom="critico">{erro}</Aviso>
        </div>
      )}
      {aviso && (
        <div className="mb-3">
          <Aviso tom="ok">{aviso}</Aviso>
        </div>
      )}

      {carregando && itens.length === 0 ? (
        <Vazio>Carregando a agenda…</Vazio>
      ) : porDia.length === 0 ? (
        <Vazio>Nenhum atendimento neste período. Use “Novo agendamento” para marcar o primeiro.</Vazio>
      ) : (
        <div className="space-y-5">
          {porDia.map((grupo) => (
            <section key={grupo.rotulo}>
              <h3 className="mb-2 text-sm font-bold capitalize text-tinta">{grupo.rotulo}</h3>
              <ul className="m-0 list-none divide-y divide-borda overflow-hidden rounded-cartao border border-borda-forte bg-papel p-0 shadow-cartao">
                {grupo.itens.map((a) => {
                  const d = lerData(a.data_hora);
                  const antes = ANTES_DA_ENTREVISTA.includes(a.estado);
                  const emCurso = EM_CURSO.includes(a.estado);
                  const ocupadoAqui = ocupado === a.id;
                  return (
                    <li key={a.id} className={`px-4 py-3 ${a.estado === "CLIENTE_AGUARDANDO" ? "bg-critico-claro" : ""}`}>
                      <div className="grid gap-3 lg:grid-cols-[90px_minmax(0,1fr)_auto] lg:items-center">
                        <div className="font-titulo text-lg font-semibold tabular-nums text-tinta">
                          {d ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "—"}
                        </div>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <strong className="truncate text-sm text-tinta">{a.cliente}</strong>
                            <Selo tom={TOM_ESTADO[a.estado]}>{ROTULO_ESTADO[a.estado]}</Selo>
                            {a.cliente_na_sala && <Selo tom="critico" simbolo="●">cliente na sala</Selo>}
                            {a.origem === "avulso" && <Selo tom="neutro">avulso</Selo>}
                          </div>
                          <div className="mt-1 text-xs text-tinta-3">
                            {a.telefone ? formatarTelefone(a.telefone) : "sem WhatsApp"}
                            {a.responsavel_nome ? ` · Responsável: ${a.responsavel_nome}` : ""}
                            {a.observacao ? ` · ${a.observacao}` : ""}
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-2 lg:justify-end">
                          {(antes || emCurso) && a.estado !== "CLIENTE_FALTOU" && (
                            <Botao variante="primario" pequeno onClick={() => entrar(a)} disabled={ocupadoAqui}>
                              {emCurso ? "Continuar" : a.estado === "CLIENTE_AGUARDANDO" ? "Entrar agora" : "Iniciar entrevista"}
                            </Botao>
                          )}
                          {a.link_cliente && antes && (
                            <Botao variante="secundario" pequeno onClick={() => copiar(a.link_cliente!)}>
                              <Copy aria-hidden className="size-3" /> Link do cliente
                            </Botao>
                          )}
                          {a.estado === "AGENDADA" && a.telefone && (
                            <>
                              <Botao variante="secundario" pequeno carregando={ocupadoAqui} onClick={() => enviarConfirmacao(a, false)}>
                                Enviar confirmação
                              </Botao>
                              <Botao variante="discreto" pequeno disabled={ocupadoAqui} onClick={() => enviarConfirmacao(a, true)}>
                                Reenviar
                              </Botao>
                            </>
                          )}
                          {antes && a.estado !== "CLIENTE_AGUARDANDO" && (
                            <Botao variante="discreto" pequeno disabled={ocupadoAqui} onClick={() => setFormulario(formularioDe(a))}>
                              Editar
                            </Botao>
                          )}
                          {a.estado === "AGENDADA" && (
                            <Botao
                              variante="discreto"
                              pequeno
                              disabled={ocupadoAqui}
                              onClick={() => void agir(a.id, () => marcarFaltaAtendimento(a.id), "Falta registrada.")}
                            >
                              Marcar falta
                            </Botao>
                          )}
                          {a.estado === "CLIENTE_FALTOU" && (
                            <Botao
                              variante="secundario"
                              pequeno
                              disabled={ocupadoAqui}
                              onClick={() =>
                                void agir(a.id, async () => {
                                  const r = await reagendarAtendimento(a.id);
                                  setFormulario(formularioDe(r));
                                })
                              }
                            >
                              Reagendar
                            </Botao>
                          )}
                          {antes && (
                            <Botao
                              variante="perigo"
                              pequeno
                              disabled={ocupadoAqui}
                              onClick={() => {
                                if (window.confirm(`Cancelar o atendimento de ${a.cliente}?`)) {
                                  void agir(a.id, () => cancelarAtendimento(a.id), "Atendimento cancelado.");
                                }
                              }}
                            >
                              Cancelar
                            </Botao>
                          )}
                          {a.casos?.map((c) => (
                            <Botao key={c.id} variante="texto" onClick={() => onAbrirCaso(c.id)}>
                              Abrir caso: {c.acao || c.categoria}
                            </Botao>
                          ))}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
