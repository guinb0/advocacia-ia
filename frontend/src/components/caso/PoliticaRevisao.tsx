"use client";

import { useEffect, useState } from "react";

import { obterPoliticaRevisao, definirPoliticaRevisao } from "@/lib/api";

/** Interruptor da POLÍTICA DO ESCRITÓRIO: revisão humana de documentos obrigatória.
 *
 * Vale para todos os casos, não só o aberto — por isso o texto deixa claro. Some
 * do portal do cliente (só é montado na visão do advogado). Ligado = comportamento
 * de sempre; desligado = documento com ressalva vai direto para a análise da LLM e
 * fica verde, sem parar em revisão.
 */
export default function PoliticaRevisao() {
  const [obrigatoria, setObrigatoria] = useState<boolean | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    obterPoliticaRevisao()
      .then((r) => {
        if (!cancelado) setObrigatoria(r.obrigatoria);
      })
      .catch(() => {
        if (!cancelado) setErro("Não foi possível ler a política de revisão.");
      });
    return () => {
      cancelado = true;
    };
  }, []);

  async function alternar() {
    if (obrigatoria === null || salvando) return;
    const alvo = !obrigatoria;
    setSalvando(true);
    setErro(null);
    try {
      const r = await definirPoliticaRevisao(alvo);
      setObrigatoria(r.obrigatoria);
    } catch {
      setErro("Não foi possível salvar. Tente de novo.");
    } finally {
      setSalvando(false);
    }
  }

  const ligada = obrigatoria === true;

  return (
    <section className="mb-4 flex items-start justify-between gap-4 rounded-cartao border border-borda bg-papel-2 px-5 py-4">
      <div className="min-w-0">
        <h3 className="m-0 text-sm font-semibold text-tinta">Revisão humana obrigatória</h3>
        <p className="mt-1 mb-0 max-w-[70ch] text-xs leading-[1.5] text-tinta-2">
          {obrigatoria === null
            ? "Carregando a política do escritório…"
            : ligada
              ? "Documentos com ressalva param para conferência de um advogado antes de contar no checklist. Vale para todos os casos do escritório."
              : "Documentos processados vão direto para a análise da LLM e ficam verdes, sem parar em revisão. Vale para todos os casos do escritório."}
        </p>
        {erro && <p className="mt-1 mb-0 text-xs text-critico">{erro}</p>}
      </div>

      <button
        type="button"
        role="switch"
        aria-checked={ligada}
        aria-label="Revisão humana obrigatória"
        disabled={obrigatoria === null || salvando}
        onClick={() => void alternar()}
        className={`relative mt-1 h-7 w-12 shrink-0 rounded-full border transition-colors disabled:opacity-60 ${
          ligada ? "border-acao bg-acao" : "border-borda-forte bg-papel-3"
        }`}
      >
        <span
          className={`absolute top-1/2 h-5 w-5 -translate-y-1/2 rounded-full bg-papel shadow transition-[left] ${
            ligada ? "left-[22px]" : "left-[2px]"
          }`}
        />
      </button>
    </section>
  );
}
