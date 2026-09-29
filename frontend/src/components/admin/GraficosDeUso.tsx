"use client";

/**
 * Gráficos de uso das APIs: quanto se gastou por dia, nas últimas 24 horas e
 * em cada parte do sistema, com alerta quando o dia de hoje foge da média.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { Aviso, Cartao, Vazio } from "@/components/ui/Basicos";
import { obterUsoDasApis, type UsoDasApis, type UsoDoDia } from "@/lib/api";
import { cn } from "@/lib/utils";

type Medida = "custo" | "tokens";

const PERIODOS = [7, 30, 90] as const;

const OPERACOES: Record<string, string> = {
  ocr: "Leitura do texto dos arquivos (OCR)",
  classificacao_documento: "Leitura de cada documento",
  analise_documentos: "Análise dos documentos do caso",
  geracao_peticao: "Geração da petição",
  embeddings: "Busca no acervo",
  transcricao: "Transcrição de áudio",
};

const FORNECEDORES: Record<string, { nome: string; cor: string }> = {
  openrouter: { nome: "OpenRouter", cor: "bg-acao" },
  deepseek: { nome: "DeepSeek", cor: "bg-marca-ouro" },
  mistral: { nome: "Mistral", cor: "bg-ok" },
};

function fornecedor(id: string) {
  return FORNECEDORES[id] ?? { nome: id, cor: "bg-tinta-3" };
}

function nomeDaOperacao(id: string) {
  return OPERACOES[id] ?? id.replace(/_/g, " ");
}

function formatar(valor: number, medida: Medida): string {
  if (medida === "custo") {
    return new Intl.NumberFormat("pt-BR", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: valor > 0 && valor < 1 ? 3 : 2,
    }).format(valor);
  }
  return new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 }).format(valor);
}

function valorDe(item: { custo_usd: number; tokens: number }, medida: Medida) {
  return medida === "custo" ? item.custo_usd : item.tokens;
}

function diaCurto(dia: string) {
  const [, mes, d] = dia.split("-");
  return `${d}/${mes}`;
}

function diaLongo(dia: string) {
  const texto = new Date(`${dia}T12:00:00`).toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
  return texto.charAt(0).toLocaleUpperCase("pt-BR") + texto.slice(1);
}

function Alternador<T extends string | number>({
  opcoes,
  valor,
  onMudar,
  rotulo,
  rotuloDe,
}: {
  opcoes: readonly T[];
  valor: T;
  onMudar: (v: T) => void;
  rotulo: string;
  rotuloDe: (v: T) => string;
}) {
  return (
    <div role="group" aria-label={rotulo} className="inline-flex rounded-campo border border-borda bg-papel-2 p-[2px]">
      {opcoes.map((opcao) => (
        <button
          key={String(opcao)}
          type="button"
          aria-pressed={opcao === valor}
          onClick={() => onMudar(opcao)}
          className={cn(
            "rounded-[6px] px-3 py-1 text-xs font-semibold transition-colors",
            opcao === valor ? "bg-papel text-tinta shadow-sm" : "text-tinta-3 hover:text-tinta",
          )}
        >
          {rotuloDe(opcao)}
        </button>
      ))}
    </div>
  );
}

function GraficoPorDia({ dias, medida }: { dias: UsoDoDia[]; medida: Medida }) {
  const [focado, setFocado] = useState<number | null>(null);
  const maximo = Math.max(...dias.map((d) => valorDe(d, medida)), 0);
  const anteriores = dias.slice(-8, -1);
  const media = anteriores.length ? anteriores.reduce((s, d) => s + valorDe(d, medida), 0) / anteriores.length : 0;
  const passo = dias.length > 31 ? 14 : dias.length > 10 ? 5 : 1;
  const fornecedoresUsados = [
    ...new Set(dias.flatMap((d) => Object.entries(d.por_fornecedor).filter(([, v]) => valorDe(v, medida) > 0).map(([id]) => id))),
  ];
  const dia = focado != null ? dias[focado] : dias[dias.length - 1];

  if (maximo <= 0) return <Vazio>Nenhum gasto registrado no período.</Vazio>;

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="font-semibold text-tinta">{diaLongo(dia.dia)}</span>
        <span className="tabular-nums text-tinta-2">
          <strong className="text-tinta">{formatar(valorDe(dia, medida), medida)}</strong>
          {" · "}
          {Math.round(dia.chamadas)} chamadas
          {dia.erros > 0 && <span className="text-critico"> · {Math.round(dia.erros)} com erro</span>}
        </span>
      </div>

      <div className="relative h-48" onMouseLeave={() => setFocado(null)}>
        {media > 0 && (
          <div
            className="pointer-events-none absolute inset-x-0 z-10 border-t border-dashed border-tinta-3"
            style={{ bottom: `${(media / maximo) * 100}%` }}
          >
            <span className="absolute right-0 -top-5 rounded bg-papel px-1 text-[11px] text-tinta-3">
              média 7 dias: {formatar(media, medida)}
            </span>
          </div>
        )}
        <div className="flex h-full items-end gap-[2px]">
          {dias.map((d, indice) => {
            const total = valorDe(d, medida);
            const hoje = indice === dias.length - 1;
            return (
              <button
                key={d.dia}
                type="button"
                onMouseEnter={() => setFocado(indice)}
                onFocus={() => setFocado(indice)}
                onClick={() => setFocado(indice)}
                aria-label={`${diaLongo(d.dia)}: ${formatar(total, medida)}`}
                className={cn(
                  "flex h-full min-w-0 flex-1 flex-col-reverse rounded-t-[3px] outline-offset-2",
                  focado === indice ? "bg-papel-3" : "hover:bg-papel-2",
                )}
              >
                <span
                  className={cn("flex w-full flex-col-reverse overflow-hidden rounded-t-[3px]", hoje && "ring-2 ring-tinta/40")}
                  style={{ height: `${(total / maximo) * 100}%` }}
                >
                  {Object.entries(d.por_fornecedor).map(([id, v]) => {
                    const parte = valorDe(v, medida);
                    if (parte <= 0 || total <= 0) return null;
                    return <span key={id} className={cn("w-full", fornecedor(id).cor)} style={{ height: `${(parte / total) * 100}%` }} />;
                  })}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex gap-[2px] text-[11px] text-tinta-3" aria-hidden>
        {dias.map((d, indice) => (
          <span key={d.dia} className="min-w-0 flex-1 text-center">
            {(dias.length - 1 - indice) % passo === 0 ? diaCurto(d.dia) : ""}
          </span>
        ))}
      </div>

      <Legenda ids={fornecedoresUsados} />
    </div>
  );
}

function Legenda({ ids }: { ids: string[] }) {
  if (ids.length < 2) return null;
  return (
    <ul className="m-0 flex list-none flex-wrap gap-4 p-0 text-xs text-tinta-2">
      {ids.map((id) => (
        <li key={id} className="flex items-center gap-[6px]">
          <span className={cn("h-3 w-3 rounded-[3px]", fornecedor(id).cor)} aria-hidden />
          {fornecedor(id).nome}
        </li>
      ))}
    </ul>
  );
}

function GraficoPorHora({ horas, medida }: { horas: UsoDasApis["por_hora"]; medida: Medida }) {
  const maximo = Math.max(...horas.map((h) => valorDe(h, medida)), 0);
  const pico = horas.reduce((melhor, h) => (valorDe(h, medida) > valorDe(melhor, medida) ? h : melhor), horas[0]);
  if (!horas.length || maximo <= 0) return <Vazio>Nada gasto nas últimas 24 horas.</Vazio>;
  return (
    <div className="grid gap-2">
      <p className="m-0 text-sm text-tinta-2">
        Hora de maior gasto: <strong className="text-tinta">{pico.hora.slice(11)}h</strong> ({formatar(valorDe(pico, medida), medida)},{" "}
        {Math.round(pico.chamadas)} chamadas).
      </p>
      <div className="flex h-28 items-end gap-[3px]">
        {horas.map((h) => {
          const valor = valorDe(h, medida);
          return (
            <div
              key={h.hora}
              title={`${h.hora.slice(11)}h — ${formatar(valor, medida)} · ${Math.round(h.chamadas)} chamadas`}
              className="flex h-full min-w-0 flex-1 items-end"
            >
              <span
                className={cn("w-full rounded-t-[3px]", h === pico ? "bg-atencao" : "bg-acao/70")}
                style={{ height: `${Math.max(valor > 0 ? 3 : 0, (valor / maximo) * 100)}%` }}
              />
            </div>
          );
        })}
      </div>
      <div className="flex gap-[3px] text-[11px] text-tinta-3" aria-hidden>
        {horas.map((h, indice) => (
          <span key={h.hora} className="min-w-0 flex-1 text-center">
            {indice % 4 === 3 ? `${h.hora.slice(11)}h` : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function PorOperacao({ uso, medida }: { uso: UsoDasApis; medida: Medida }) {
  const itens = uso.por_operacao.filter((o) => valorDe(o, medida) > 0 || o.chamadas > 0);
  const total = itens.reduce((s, o) => s + valorDe(o, medida), 0);
  const maximo = Math.max(...itens.map((o) => valorDe(o, medida)), 0);
  if (!itens.length) return <Vazio>Nenhuma chamada no período.</Vazio>;
  const ordenados = [...itens].sort((a, b) => valorDe(b, medida) - valorDe(a, medida));
  return (
    <ul className="m-0 grid list-none gap-3 p-0">
      {ordenados.map((o) => {
        const valor = valorDe(o, medida);
        const hoje = medida === "custo" ? o.hoje_custo_usd : o.hoje_tokens;
        const semCusto = medida === "custo" && valor <= 0 && uso.fornecedores_sem_custo.includes(o.fornecedor);
        return (
          <li key={`${o.operacao}-${o.fornecedor}`} className="grid gap-1">
            <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
              <span className="text-tinta">
                {nomeDaOperacao(o.operacao)}
                <span className="ml-2 text-xs text-tinta-3">{fornecedor(o.fornecedor).nome}</span>
              </span>
              {semCusto ? (
                <span className="text-xs text-tinta-3">custo não informado</span>
              ) : (
                <span className="tabular-nums text-tinta-2">
                  <strong className="text-tinta">{formatar(valor, medida)}</strong>
                  {total > 0 && <span className="text-tinta-3"> · {Math.round((valor / total) * 100)}%</span>}
                </span>
              )}
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-papel-3" aria-hidden>
              <div className={cn("h-full rounded-full", fornecedor(o.fornecedor).cor)} style={{ width: `${maximo ? (valor / maximo) * 100 : 0}%` }} />
            </div>
            <span className="text-xs text-tinta-3">
              {Math.round(o.chamadas)} chamadas
              {o.erros > 0 && <span className="text-critico"> · {Math.round(o.erros)} com erro</span>}
              {hoje > 0 && <> · hoje: {formatar(hoje, medida)}</>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export default function GraficosDeUso() {
  const [dias, setDias] = useState<(typeof PERIODOS)[number]>(30);
  const [uso, setUso] = useState<UsoDasApis | null>(null);
  const [medidaEscolhida, setMedidaEscolhida] = useState<Medida | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setErro(null);
    try {
      setUso(await obterUsoDasApis(dias));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível ler o uso das APIs.");
    }
  }, [dias]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const medida: Medida = medidaEscolhida ?? (uso && uso.totais.custo_usd > 0 ? "custo" : "tokens");

  const resumo = useMemo(() => {
    if (!uso) return null;
    const hoje = uso.por_dia[uso.por_dia.length - 1];
    const total = valorDe(uso.totais, medida);
    return { hoje: valorDe(hoje, medida), total, mediaDiaria: total / Math.max(1, uso.por_dia.length) };
  }, [uso, medida]);

  const alerta = uso?.alerta;

  return (
    <div className="mt-4 grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="m-0 font-titulo text-lg font-semibold text-tinta">Uso ao longo do tempo</h2>
          <p className="m-0 mt-1 text-sm text-tinta-3">Para perceber quando e em que parte do sistema o gasto sobe.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Alternador
            rotulo="Medida"
            opcoes={["custo", "tokens"] as const}
            valor={medida}
            onMudar={setMedidaEscolhida}
            rotuloDe={(m) => (m === "custo" ? "Custo (US$)" : "Tokens")}
          />
          <Alternador rotulo="Período" opcoes={PERIODOS} valor={dias} onMudar={setDias} rotuloDe={(d) => `${d} dias`} />
        </div>
      </div>

      {erro && <Aviso tom="critico">{erro}</Aviso>}

      {alerta && alerta.nivel !== "ok" && (
        <Aviso tom={alerta.nivel} titulo={alerta.nivel === "critico" ? "Gasto muito acima do normal hoje" : "Gasto acima do normal hoje"}>
          {alerta.mensagem}
          {alerta.principal_hoje && (
            <>
              {" "}
              Quem mais gastou hoje: <strong>{nomeDaOperacao(alerta.principal_hoje.operacao)}</strong> (
              {formatar(alerta.principal_hoje.valor, alerta.medida)}).
            </>
          )}
        </Aviso>
      )}

      {uso && uso.fornecedores_sem_custo.length > 0 && medida === "custo" && (
        <Aviso tom="info">
          {uso.fornecedores_sem_custo.map((f) => fornecedor(f).nome).join(", ")}{" "}
          {uso.fornecedores_sem_custo.length === 1 ? "não informa" : "não informam"} o custo de cada chamada, então{" "}
          {uso.fornecedores_sem_custo.length === 1 ? "fica" : "ficam"} fora do gráfico em dólar. Troque para{" "}
          <strong>Tokens</strong> para ver o consumo de todas.
        </Aviso>
      )}

      {!uso && !erro && <Vazio>Carregando o uso das APIs…</Vazio>}

      {uso && resumo && (
        <>
          <dl className="m-0 grid grid-cols-1 gap-3 sm:grid-cols-3">
            {[
              { rotulo: "Hoje", valor: resumo.hoje },
              { rotulo: "Média por dia", valor: resumo.mediaDiaria },
              { rotulo: `Total em ${uso.dias} dias`, valor: resumo.total },
            ].map((item) => (
              <div key={item.rotulo} className="rounded-campo border border-borda bg-papel px-4 py-3">
                <dt className="text-xs text-tinta-3">{item.rotulo}</dt>
                <dd className="m-0 mt-1 text-xl font-semibold tabular-nums text-tinta">{formatar(item.valor, medida)}</dd>
              </div>
            ))}
          </dl>

          <Cartao titulo="Por dia" subtitulo="Passe o mouse (ou toque) numa barra para ver o dia. A linha tracejada é a média dos 7 dias anteriores.">
            <GraficoPorDia dias={uso.por_dia} medida={medida} />
          </Cartao>

          <div className="grid gap-4 lg:grid-cols-2">
            <Cartao titulo="Últimas 24 horas" subtitulo="Horário de Brasília.">
              <GraficoPorHora horas={uso.por_hora} medida={medida} />
            </Cartao>
            <Cartao titulo="Onde o gasto vai" subtitulo={`Partes do sistema nos últimos ${uso.dias} dias.`}>
              <PorOperacao uso={uso} medida={medida} />
            </Cartao>
          </div>
        </>
      )}
    </div>
  );
}
