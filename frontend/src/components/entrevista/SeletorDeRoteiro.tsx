"use client";

/**
 * Trocar o roteiro no meio do atendimento.
 *
 * O botão "Alterar roteiro" da entrevista abre ESTE seletor — o catálogo de
 * roteiros disponíveis — e não o editor. O caso comum não é corrigir uma
 * pergunta, é perceber que o atendimento é de outra categoria e trocar o
 * roteiro inteiro: um clique no card já troca, sem passo de confirmação.
 *
 * Editar continua a um clique de distância ("Editar o roteiro atual"), para
 * quem precisa consertar uma pergunta para ESTE cliente — mas deixou de ser o
 * que o botão principal faz.
 */

import { useEffect, useState } from "react";

import { ApiError, listarRoteiros, obterRoteiro } from "@/lib/api";
import type { RoteiroCompleto, RoteiroResumo } from "@/lib/types";

export default function SeletorDeRoteiro({
  atualCodigo,
  aoEscolher,
  aoEditarAtual,
  aoFechar,
}: {
  /** Código do roteiro em uso agora — fica destacado e não recarrega à toa. */
  atualCodigo: string;
  /** Troca o roteiro da sessão pelo escolhido, já completo (blocos e perguntas). */
  aoEscolher: (roteiro: RoteiroCompleto, origem: string) => void;
  /** Abre o editor do roteiro atual (a antiga função do botão). */
  aoEditarAtual: () => void;
  aoFechar: () => void;
}) {
  const [roteiros, setRoteiros] = useState<RoteiroResumo[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  /** Código do roteiro que está sendo buscado no clique — trava o card. */
  const [abrindo, setAbrindo] = useState<string | null>(null);

  useEffect(() => {
    listarRoteiros()
      .then(setRoteiros)
      .catch((e) => setErro(e instanceof ApiError ? e.message : String(e)))
      .finally(() => setCarregando(false));
  }, []);

  async function escolher(resumo: RoteiroResumo) {
    // Trocar pelo que já está em uso não faz nada — só fecha.
    if (resumo.codigo === atualCodigo) {
      aoFechar();
      return;
    }
    setAbrindo(resumo.codigo);
    setErro(null);
    try {
      const completo = await obterRoteiro(resumo.codigo);
      aoEscolher(completo, resumo.origem);
      aoFechar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : String(e));
      setAbrindo(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-tinta/40 flex items-start justify-center overflow-y-auto p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Trocar o roteiro"
    >
      <div className="w-full max-w-[720px] bg-papel border border-borda-forte my-4">
        <div className="sticky top-0 z-10 bg-papel flex justify-between items-center gap-4 flex-wrap px-4 py-3 border-b border-borda-forte">
          <div>
            <h2 className="m-0 font-semibold text-[19px] leading-[1.15] font-titulo">
              Trocar o roteiro
            </h2>
            <p className="m-0 mt-[3px] text-[11.5px] leading-[1.4] font-ui text-tinta-3">
              Escolha o roteiro que a entrevista vai seguir — o clique já troca.
            </p>
          </div>
          <div className="flex gap-[10px] items-center flex-wrap">
            <button
              type="button"
              className="px-[14px] py-[7px] rounded-campo border border-borda-campo bg-papel text-tinta text-[13px] font-ui cursor-pointer hover:bg-papel-3 disabled:cursor-not-allowed disabled:border-borda-forte disabled:bg-papel-3 disabled:text-tinta-desabilitada"
              onClick={aoEditarAtual}
            >
              Editar o roteiro atual
            </button>
            <button
              type="button"
              className="px-[14px] py-[7px] rounded-campo border border-borda-campo bg-papel text-tinta text-[13px] font-ui cursor-pointer hover:bg-papel-3"
              onClick={aoFechar}
            >
              Cancelar
            </button>
          </div>
        </div>

        <div className="p-4">
          {erro && (
            <div className="mb-3 border-l-4 border-critico bg-critico-claro px-3 py-[10px] text-[12.5px] leading-[1.5] font-ui text-tinta">
              {erro}
            </div>
          )}

          {carregando ? (
            <p className="m-0 text-tinta-3 text-sm">Carregando o catálogo…</p>
          ) : roteiros.length === 0 ? (
            <p className="m-0 text-tinta-3 text-sm">Nenhum roteiro no catálogo.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {roteiros.map((r) => {
                const emUso = r.codigo === atualCodigo;
                return (
                  <button
                    key={r.codigo}
                    type="button"
                    onClick={() => void escolher(r)}
                    disabled={abrindo !== null}
                    aria-current={emUso}
                    className={`text-left w-full p-3 border rounded-campo cursor-pointer transition-colors disabled:cursor-wait ${
                      emUso
                        ? "border-acao-borda bg-acao-clara"
                        : "border-borda bg-papel hover:bg-papel-3 hover:border-borda-forte"
                    }`}
                  >
                    <div className="flex items-center gap-2 flex-wrap">
                      <strong className="text-tinta text-sm">{r.nome}</strong>
                      {emUso && (
                        <span className="px-2 py-[1px] rounded-pill bg-acao text-papel text-[11px] font-ui">
                          em uso
                        </span>
                      )}
                      {r.importado ? (
                        <span className="px-2 py-[1px] rounded-pill bg-papel-3 text-tinta-3 text-[11px] font-ui">
                          {r.origem ? `de ${r.origem}` : "editado"}
                        </span>
                      ) : (
                        <span className="px-2 py-[1px] rounded-pill bg-papel-3 text-tinta-3 text-[11px] font-ui">
                          original do sistema
                        </span>
                      )}
                      {abrindo === r.codigo && (
                        <span className="text-tinta-3 text-[11px] font-ui">trocando…</span>
                      )}
                    </div>
                    {r.descricao && (
                      <p className="mt-1 mb-0 text-tinta-3 text-xs leading-[1.5]">{r.descricao}</p>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
