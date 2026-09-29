"use client";

import { useEffect, useState } from "react";
import {
  assinarDiagnosticoJitsi,
  diagnosticoJitsiAtivo,
  listarDiagnosticoJitsi,
  retratoDiagnosticoJitsi,
  type EventoDiagnosticoJitsi,
} from "@/lib/diagnosticoJitsi";

export default function DiagnosticoJitsi() {
  const [ativo, setAtivo] = useState(false);
  const [aberto, setAberto] = useState(false);
  const [retrato, setRetrato] = useState<Record<string, unknown>>({});
  const [eventos, setEventos] = useState<EventoDiagnosticoJitsi[]>([]);

  useEffect(() => {
    const ligado = diagnosticoJitsiAtivo();
    setAtivo(ligado);
    if (!ligado) return;
    void retratoDiagnosticoJitsi().then(setRetrato);
    setEventos(listarDiagnosticoJitsi());
    return assinarDiagnosticoJitsi(() => setEventos(listarDiagnosticoJitsi()));
  }, []);

  if (!ativo) return null;
  return (
    <aside className="fixed bottom-3 left-3 z-[100] max-w-[min(94vw,560px)] font-mono text-xs">
      <button type="button" className="rounded bg-slate-950 px-3 py-2 text-white" onClick={() => setAberto((v) => !v)}>
        Diagnóstico Jitsi ({eventos.length})
      </button>
      {aberto && (
        <div className="mt-2 max-h-[70vh] overflow-auto rounded border border-slate-600 bg-slate-950 p-3 text-slate-100 shadow-xl">
          <p className="m-0 mb-2 font-sans text-sm font-semibold">Modo diagnóstico — dados locais, sem mídia</p>
          <pre className="m-0 whitespace-pre-wrap break-words text-[11px]">{JSON.stringify(retrato, null, 2)}</pre>
          <hr className="my-3 border-slate-700" />
          {eventos.slice().reverse().map((item, indice) => (
            <pre key={`${item.quando}-${indice}`} className="m-0 mb-2 whitespace-pre-wrap break-words text-[11px]">
              {item.quando} {item.evento}{item.dados ? ` ${JSON.stringify(item.dados)}` : ""}
            </pre>
          ))}
        </div>
      )}
    </aside>
  );
}
