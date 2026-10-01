"use client";

import { useCallback, useEffect, useState } from "react";

import GraficosDeUso from "@/components/admin/GraficosDeUso";
import { Aviso, Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";
import { informarSaldoApi, obterGastosApi, type GastoApi, type SinalGastoApi } from "@/lib/api";

const COBRANCA_OPENAI = "https://platform.openai.com/settings/organization/billing/overview";

const TOM: Record<SinalGastoApi, "ok" | "atencao" | "critico" | "neutro"> = {
  ok: "ok",
  atencao: "atencao",
  critico: "critico",
  desconhecido: "neutro",
  ausente: "neutro",
};

const ROTULO: Record<SinalGastoApi, string> = {
  ok: "pode seguir",
  atencao: "recarregue em breve",
  critico: "recarregue agora",
  desconhecido: "saldo não informado",
  ausente: "não configurada",
};

function dinheiro(valor: number | null, moeda: string): string {
  if (valor == null || Number.isNaN(valor)) return "—";
  const codigo = moeda === "CNY" || moeda === "USD" || moeda === "BRL" ? moeda : "USD";
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: codigo }).format(valor);
}

function quandoFoi(iso: string): string {
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return "";
  return data.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** A OpenAI não conta a ninguém quanto crédito resta: quem sabe é o escritório, pelo
 *  site dela. O sistema guarda o valor e desconta o gasto dali em diante. */
function CreditoInformado({ api, aoSalvar }: { api: GastoApi; aoSalvar: () => void }) {
  const [aberto, setAberto] = useState(!api.informado);
  const [valor, setValor] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function salvar() {
    if (!valor.trim()) {
      setErro("Digite o valor que aparece no site da OpenAI.");
      return;
    }
    setSalvando(true);
    setErro(null);
    try {
      await informarSaldoApi(api.id, valor);
      setValor("");
      setAberto(false);
      aoSalvar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível salvar o crédito.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="mt-3 rounded-[var(--raio-sm)] border border-borda bg-papel-2 p-3 text-sm">
      {api.informado && (
        <p className="m-0 text-tinta-2">
          Crédito informado em {quandoFoi(api.informado.informado_em)}:{" "}
          <strong className="tabular-nums">{dinheiro(api.informado.valor, "USD")}</strong>
          {api.gasto_desde_informado != null && (
            <>
              {" "}· gasto desde então:{" "}
              <strong className="tabular-nums">{dinheiro(api.gasto_desde_informado, "USD")}</strong>
            </>
          )}
          <span className="block text-xs text-tinta-3">
            {api.fonte_gasto === "oficial"
              ? "Gasto informado pela própria OpenAI."
              : "Gasto calculado pelo sistema a partir do uso do chat da petição. É uma estimativa: confira no site da OpenAI de vez em quando."}
          </span>
        </p>
      )}

      {!aberto ? (
        <Botao variante="secundario" pequeno className="mt-2" onClick={() => setAberto(true)}>
          Informar crédito atual (fez recarga?)
        </Botao>
      ) : (
        <form
          className={api.informado ? "mt-3 border-t border-borda pt-3" : ""}
          onSubmit={(evento) => {
            evento.preventDefault();
            void salvar();
          }}
        >
          <p className="m-0 font-semibold text-tinta">
            {api.informado ? "Atualizar o crédito" : "Para o sistema avisar quando o crédito estiver acabando:"}
          </p>
          <ol className="my-2 ml-5 list-decimal space-y-1 text-tinta-2">
            <li>
              Abra a{" "}
              <a href={COBRANCA_OPENAI} target="_blank" rel="noreferrer" className="font-semibold text-acao underline">
                página de cobrança da OpenAI
              </a>
              .
            </li>
            <li>
              Copie o valor de <strong>Credit balance</strong> (crédito restante).
            </li>
            <li>Digite o valor aqui e clique em Salvar. Depois de cada recarga, faça isto de novo.</li>
          </ol>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1 rounded-[var(--raio-sm)] border border-borda-forte bg-papel px-2">
              <span className="text-tinta-3">US$</span>
              <input
                inputMode="decimal"
                className="w-28 bg-transparent py-[6px] tabular-nums outline-none"
                placeholder="25,50"
                value={valor}
                onChange={(evento) => setValor(evento.target.value)}
                aria-label="Crédito restante na OpenAI, em dólares"
              />
            </label>
            <Botao type="submit" variante="primario" pequeno carregando={salvando} textoCarregando="Salvando…">
              Salvar
            </Botao>
            {api.informado && (
              <Botao type="button" variante="discreto" pequeno onClick={() => setAberto(false)} disabled={salvando}>
                Cancelar
              </Botao>
            )}
          </div>
          {erro && (
            <p className="m-0 mt-2 text-critico" role="alert">
              {erro}
            </p>
          )}
        </form>
      )}
    </div>
  );
}

export default function PainelGastosApi({ onVoltar }: { onVoltar: () => void }) {
  const [apis, setApis] = useState<GastoApi[]>([]);
  const [quando, setQuando] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      const painel = await obterGastosApi();
      setApis(painel.apis);
      setQuando(painel.atualizado_em);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível ler os gastos das APIs.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const urgentes = apis.filter((api) => api.sinal === "critico");
  const atencao = apis.filter((api) => api.sinal === "atencao");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Botao variante="secundario" pequeno onClick={onVoltar}>
            ← Voltar para a carteira
          </Botao>
          <h1 className="mt-[6px] mb-0 text-xl tracking-[-0.01em]">Gastos das APIs</h1>
          <p className="mt-[5px] mb-0 max-w-[66ch] text-base text-tinta-2">
            Quanto cada API já consumiu neste sistema e quanto ainda resta na conta, para recarregar antes de acabar.
          </p>
        </div>
        <Botao variante="discreto" onClick={() => void carregar()} carregando={carregando} textoCarregando="Atualizando…">
          Atualizar
        </Botao>
      </div>

      {erro && <Aviso tom="critico">{erro}</Aviso>}
      {urgentes.length > 0 && (
        <Aviso tom="critico" titulo="Recarregue agora">
          {urgentes.map((api) => api.nome).join(", ")} {urgentes.length === 1 ? "está" : "estão"} no fim do crédito.
        </Aviso>
      )}
      {urgentes.length === 0 && atencao.length > 0 && (
        <Aviso tom="atencao" titulo="Recarregue em breve">
          {atencao.map((api) => api.nome).join(", ")} {atencao.length === 1 ? "está" : "estão"} com o saldo baixo.
        </Aviso>
      )}

      {!carregando && apis.length === 0 && <Vazio>Nenhuma API acompanhada.</Vazio>}

      <div className="grid gap-3 md:grid-cols-2">
        {apis.map((api) => (
          <Cartao key={api.id} titulo={api.nome}>
            <div className="mb-3 flex items-center justify-between gap-2">
              <span className="shrink-0">
                <Selo tom={TOM[api.sinal]}>{ROTULO[api.sinal]}</Selo>
              </span>
              <span className="text-sm text-tinta-2">{api.mensagem}</span>
            </div>
            <p className="m-0 text-2xl font-semibold tabular-nums text-tinta">
              {api.saldo == null ? "Saldo não informado" : dinheiro(api.saldo, api.moeda)}
              {api.teto != null && <span className="ml-2 text-sm font-normal text-tinta-3">de {dinheiro(api.teto, api.moeda)}</span>}
            </p>
            {api.teto != null && api.teto > 0 && api.saldo != null && (
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-papel-3" aria-hidden>
                <div
                  className={api.sinal === "critico" ? "h-full bg-critico" : api.sinal === "atencao" ? "h-full bg-atencao" : "h-full bg-ok"}
                  style={{ width: `${Math.max(0, Math.min(100, (api.saldo / api.teto) * 100))}%` }}
                />
              </div>
            )}
            {api.saldo_informado && api.configurada && (
              <CreditoInformado api={api} aoSalvar={() => void carregar()} />
            )}
            <dl className="mt-4 grid grid-cols-3 gap-2 text-sm">
              <div>
                <dt className="text-tinta-3">24 horas</dt>
                <dd className="m-0 font-semibold tabular-nums">{dinheiro(api.gasto_24h, "USD")}</dd>
              </div>
              <div>
                <dt className="text-tinta-3">7 dias</dt>
                <dd className="m-0 font-semibold tabular-nums">{dinheiro(api.gasto_7d, "USD")}</dd>
              </div>
              <div>
                <dt className="text-tinta-3">30 dias</dt>
                <dd className="m-0 font-semibold tabular-nums">{dinheiro(api.gasto_30d, "USD")}</dd>
              </div>
            </dl>
            <p className="m-0 mt-2 text-xs text-tinta-3">
              {Math.round(api.chamadas_30d)} chamadas nos últimos 30 dias
              {api.erros_30d > 0 ? ` · ${Math.round(api.erros_30d)} com erro` : ""}
            </p>
          </Cartao>
        ))}
      </div>
      {quando && <p className="m-0 text-xs text-tinta-3">Atualizado em {new Date(quando).toLocaleString("pt-BR")}.</p>}

      <GraficosDeUso key={quando} />
    </div>
  );
}
