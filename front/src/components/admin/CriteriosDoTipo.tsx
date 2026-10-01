"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";

import { AjudaCampo, Aviso, Botao, Marcacao, Vazio } from "@/components/ui/Basicos";
import {
  criarCriterio,
  editarCriterio,
  listarCriterios,
  removerCriterio,
  reordenarCriterios,
  type CriterioTipoCaso,
} from "@/lib/api";

const CAMPO =
  "block w-full min-h-10 px-3 border border-borda-campo rounded-campo bg-papel text-tinta text-sm";

/* Cada alteração vai direto ao servidor: os critérios não entram no versionamento
 * do tipo (são uma tabela à parte) e não pedem "Salvar alteração". */
export default function CriteriosDoTipo({ codigo, podeEditar }: { codigo: string; podeEditar: boolean }) {
  const [criterios, setCriterios] = useState<CriterioTipoCaso[] | null>(null);
  const [rascunhos, setRascunhos] = useState<Record<string, string>>({});
  const [novo, setNovo] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      setCriterios(await listarCriterios(codigo));
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
      setCriterios([]);
    }
  }, [codigo]);

  useEffect(() => {
    setCriterios(null);
    setRascunhos({});
    setNovo("");
    void carregar();
  }, [carregar]);

  const executar = async (acao: () => Promise<unknown>) => {
    setOcupado(true);
    setErro(null);
    try {
      await acao();
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setOcupado(false);
    }
  };

  const mover = (posicao: number, direcao: -1 | 1) => {
    if (!criterios) return;
    const destino = posicao + direcao;
    if (destino < 0 || destino >= criterios.length) return;
    const ids = criterios.map((c) => c.id);
    [ids[posicao], ids[destino]] = [ids[destino], ids[posicao]];
    void executar(() => reordenarCriterios(codigo, ids));
  };

  return (
    <div className="text-xs text-tinta-3">
      <span>Critérios de enquadramento</span>
      <AjudaCampo>
        Uma condição por linha que a análise pós-entrevista confere no relato (“cliente era empregado
        dos Correios”, “houve afastamento pelo INSS”). Não muda o checklist do cliente.
      </AjudaCampo>

      {erro && (
        <div className="mt-2">
          <Aviso tom="critico">{erro}</Aviso>
        </div>
      )}

      {criterios === null ? (
        <p className="mt-2 text-sm">Carregando…</p>
      ) : criterios.length === 0 ? (
        <Vazio className="mt-2">Nenhum critério cadastrado.</Vazio>
      ) : (
        <ol className="m-0 mt-2 flex list-none flex-col gap-2 p-0">
          {criterios.map((c, posicao) => {
            const rascunho = rascunhos[c.id];
            const alterado = rascunho !== undefined && rascunho.trim() !== c.texto;
            return (
              <li key={c.id} className="min-w-0 rounded-campo border border-borda bg-papel-2 px-3 py-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="shrink-0 font-codigo text-[11px] text-tinta-3">{posicao + 1}.</span>
                  <input
                    className={CAMPO}
                    maxLength={400}
                    value={rascunho ?? c.texto}
                    disabled={!podeEditar || ocupado}
                    onChange={(e) => setRascunhos((atual) => ({ ...atual, [c.id]: e.target.value }))}
                  />
                  {podeEditar && (
                    <div className="flex shrink-0 items-center gap-1">
                      <Botao
                        pequeno
                        variante="texto"
                        aria-label="Subir critério"
                        disabled={ocupado || posicao === 0}
                        onClick={() => mover(posicao, -1)}
                      >
                        <ChevronUp size={14} aria-hidden />
                      </Botao>
                      <Botao
                        pequeno
                        variante="texto"
                        aria-label="Descer critério"
                        disabled={ocupado || posicao === criterios.length - 1}
                        onClick={() => mover(posicao, 1)}
                      >
                        <ChevronDown size={14} aria-hidden />
                      </Botao>
                      <Botao
                        pequeno
                        variante="texto"
                        aria-label="Remover critério"
                        disabled={ocupado}
                        onClick={() => {
                          if (window.confirm("Remover este critério?")) {
                            void executar(() => removerCriterio(codigo, c.id));
                          }
                        }}
                      >
                        <Trash2 size={14} aria-hidden />
                      </Botao>
                    </div>
                  )}
                </div>
                {podeEditar && (
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <Marcacao>
                      <input
                        type="checkbox"
                        checked={c.ativo}
                        disabled={ocupado}
                        onChange={(e) => void executar(() => editarCriterio(codigo, c.id, { ativo: e.target.checked }))}
                      />
                      <span>Ativo</span>
                    </Marcacao>
                    {alterado && (
                      <Botao
                        pequeno
                        disabled={ocupado}
                        onClick={() =>
                          void executar(async () => {
                            await editarCriterio(codigo, c.id, { texto: rascunho });
                            setRascunhos(({ [c.id]: _descartado, ...resto }) => resto);
                          })
                        }
                      >
                        Salvar critério
                      </Botao>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}

      {podeEditar && (
        <form
          className="mt-2 flex min-w-0 items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (novo.trim().length < 3) return;
            void executar(async () => {
              await criarCriterio(codigo, novo);
              setNovo("");
            });
          }}
        >
          <input
            className={CAMPO}
            maxLength={400}
            placeholder="Novo critério"
            value={novo}
            disabled={ocupado}
            onChange={(e) => setNovo(e.target.value)}
          />
          <Botao pequeno type="submit" disabled={ocupado || novo.trim().length < 3}>
            <Plus size={14} aria-hidden /> Acrescentar
          </Botao>
        </form>
      )}
    </div>
  );
}
