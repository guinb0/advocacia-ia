"use client";

/**
 * O "seu caso × os números" num lugar só: pega os fatos do caso (entrevista +
 * o que o OCR extraiu — CID, benefício, datas) e mostra as decisões parecidas do
 * acervo e como elas terminaram, por vara. Descritivo, nunca previsão de êxito.
 */

import { useCallback, useEffect, useState } from "react";

import { jurimetriaDoCaso, type JurimetriaCaso } from "@/lib/api";
import { Aviso, Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";

const TOM_RESULTADO: Record<string, "ok" | "atencao" | "critico" | "info" | "neutro"> = {
  PROCEDENTE: "ok",
  PARCIAL: "info",
  ACORDO: "info",
  IMPROCEDENTE: "critico",
  EXTINTO: "neutro",
  INDEFINIDO: "neutro",
};

function Barra({ nome, percentual, quantidade }: { nome: string; percentual: number; quantidade: number }) {
  return (
    <div className="grid gap-1">
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="min-w-0 truncate text-tinta-2" title={nome}>{nome}</span>
        <span className="flex-none tabular-nums text-tinta-3">{percentual}% · {quantidade}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-papel-3">
        <div className="h-full rounded-full bg-acao" style={{ width: `${Math.min(100, percentual)}%` }} />
      </div>
    </div>
  );
}

export default function PainelJurimetriaCaso({ casoId }: { casoId: string }) {
  const [dados, setDados] = useState<JurimetriaCaso | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      setDados(await jurimetriaDoCaso(casoId));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível cruzar com o acervo.");
    } finally {
      setCarregando(false);
    }
  }, [casoId]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const est = dados?.estatisticas;

  return (
    <Cartao
      titulo="Seu caso × as decisões do acervo"
      subtitulo="Os fatos do caso — entrevista e o que o OCR extraiu — cruzados com decisões semelhantes. Retrato da amostra parecida, não previsão de resultado."
    >
      {/* Sinais do caso que alimentaram a busca — deixa claro o que puxou os precedentes. */}
      {dados?.sinais && (dados.sinais.categoria || dados.sinais.achados.length > 0) && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {dados.sinais.categoria && <Selo tom="info">{dados.sinais.categoria}</Selo>}
          {dados.sinais.achados.slice(0, 6).map((a, i) => (
            <span key={i} className="rounded-pill border border-borda bg-papel-2 px-2 py-1 text-[11px] text-tinta-2 [overflow-wrap:anywhere]">
              {a.length > 60 ? a.slice(0, 60) + "…" : a}
            </span>
          ))}
        </div>
      )}

      {carregando && !dados ? (
        <Vazio>Cruzando os fatos do caso com o acervo…</Vazio>
      ) : erro ? (
        <Aviso tom="critico" titulo="Erro">{erro}</Aviso>
      ) : !dados?.disponivel || !est ? (
        <Aviso tom="atencao" titulo="Sem cruzamento agora">{dados?.aviso || "Sem dados para cruzar."}</Aviso>
      ) : (
        <div className="grid gap-5">
          {/* Números-chave da amostra semelhante. */}
          <div className="grid grid-cols-2 gap-3 max-[560px]:grid-cols-1">
            <div className="rounded-campo border border-borda-forte bg-papel p-3">
              <strong className="block text-[1.5rem] leading-none tabular-nums text-tinta">
                {est.desfechos_merito.percentual}%
              </strong>
              <span className="text-xs text-tinta-3">
                favoráveis no mérito ({est.desfechos_merito.favoraveis}/{est.desfechos_merito.processos})
              </span>
            </div>
            <div className="rounded-campo border border-borda-forte bg-papel p-3">
              <strong className="block text-[1.5rem] leading-none tabular-nums text-tinta">
                {est.processos_analisados}
              </strong>
              <span className="text-xs text-tinta-3">
                decisões semelhantes · similaridade até {est.similaridade_amostra.maxima}
              </span>
            </div>
          </div>

          {/* Como terminaram (por desfecho) e onde (por vara). */}
          <div className="grid grid-cols-2 gap-6 max-[640px]:grid-cols-1">
            {est.resultados.length > 0 && (
              <div>
                <h4 className="mb-2 mt-0 text-[11px] font-semibold uppercase tracking-wide text-tinta-3">Como terminaram</h4>
                <div className="grid gap-2">
                  {est.resultados.map((r) => (
                    <Barra key={r.nome} nome={r.nome} percentual={r.percentual} quantidade={r.quantidade} />
                  ))}
                </div>
              </div>
            )}
            {est.varas.length > 0 && (
              <div>
                <h4 className="mb-2 mt-0 text-[11px] font-semibold uppercase tracking-wide text-tinta-3">Por vara / órgão</h4>
                <div className="grid gap-2">
                  {est.varas.map((v) => (
                    <Barra key={v.nome} nome={v.nome} percentual={v.percentual} quantidade={v.quantidade} />
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Os precedentes que fundam os números — auditáveis. */}
          <div>
            <h4 className="mb-2 mt-0 text-[11px] font-semibold uppercase tracking-wide text-tinta-3">
              Decisões semelhantes
            </h4>
            <ul className="grid gap-2 m-0 list-none p-0">
              {dados.precedentes.map((p, i) => (
                <li key={i} className="rounded-campo border border-borda bg-papel-2 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-codigo text-xs text-tinta" title={p.processo ?? ""}>
                      {p.processo ?? "processo não informado"}
                    </span>
                    <div className="flex items-center gap-2">
                      <Selo tom={TOM_RESULTADO[p.resultado?.toUpperCase()] ?? "neutro"}>{p.resultado}</Selo>
                      {p.similaridade != null && (
                        <span className="text-[11px] tabular-nums text-tinta-3">sim. {p.similaridade}</span>
                      )}
                    </div>
                  </div>
                  <p className="mt-1 mb-1 text-[11px] text-tinta-3 [overflow-wrap:anywhere]">{p.vara}</p>
                  <p className="m-0 line-clamp-3 text-xs leading-[1.5] text-tinta-2 [overflow-wrap:anywhere]">{p.trecho}</p>
                  {p.url && (
                    <a href={p.url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-[11px] text-acao">
                      ver decisão
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </div>

          <p className="m-0 text-[11px] leading-[1.5] text-tinta-3">{est.aviso}</p>
        </div>
      )}
    </Cartao>
  );
}
