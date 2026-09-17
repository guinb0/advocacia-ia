"use client";

import { useState } from "react";

import type {
  DuplicidadeDocumento,
  Entrega,
  ItemSituacao,
  OpcoesReclassificacao,
} from "@/lib/types";
import { duplicidadesDoErro } from "@/lib/api";
import AvisoDuplicidade from "@/components/caso/AvisoDuplicidade";
import { Aviso, Botao, Selo } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import VisorEntrega from "@/components/caso/VisorEntrega";

interface Props {
  entregas: Entrega[];
  itens: ItemSituacao[];
  onAtribuir: (
    entregaId: string,
    itens: string[],
    opcoes?: OpcoesReclassificacao,
  ) => Promise<void> | void;
  onRemover: (entregaId: string) => void;
}

const CONECTIVOS = new Set(["da", "das", "de", "do", "dos", "e", "em", "para", "por"]);
const SIGLAS = new Set(["ASO", "CAT", "CNPJ", "CPF", "CNH", "CTPS", "INSS", "NIT", "PIS", "PPP", "RG"]);

function tituloDaLeitura(valor: string | null): string {
  const texto = String(valor ?? "").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  if (!texto) return "Documento sem categoria definida";
  return texto.toLocaleLowerCase("pt-BR").split(" ").map((palavra, indice) => {
    const maiuscula = palavra.toLocaleUpperCase("pt-BR");
    if (SIGLAS.has(maiuscula)) return maiuscula;
    if (indice > 0 && CONECTIVOS.has(palavra)) return palavra;
    return palavra.charAt(0).toLocaleUpperCase("pt-BR") + palavra.slice(1);
  }).join(" ");
}

export default function TriagemDocumentos({ entregas, itens, onAtribuir, onRemover }: Props) {
  const [destinos, setDestinos] = useState<Record<string, string>>({});
  const [salvando, setSalvando] = useState<string | null>(null);
  const [visor, setVisor] = useState<{ id: string; arquivo: string } | null>(null);
  /** Suspeita de duplicidade por documento, esperando a pessoa decidir. */
  const [suspeitas, setSuspeitas] = useState<
    Record<string, { lista: DuplicidadeDocumento[]; mensagem: string }>
  >({});

  if (entregas.length === 0) return null;

  function descartarSuspeita(entregaId: string) {
    setSuspeitas((atual) => {
      const resto = { ...atual };
      delete resto[entregaId];
      return resto;
    });
  }

  async function atribuir(entrega: Entrega, confirmar = false) {
    const destino = destinos[entrega.id];
    if (!destino) return;
    setSalvando(entrega.id);
    try {
      await onAtribuir(entrega.id, [destino], { confirmarDuplicidade: confirmar });
      descartarSuspeita(entrega.id);
    } catch (e) {
      // Só a duplicidade chega aqui: os demais erros a tela do caso já mostra.
      const lista = duplicidadesDoErro(e);
      if (lista) {
        setSuspeitas((atual) => ({
          ...atual,
          [entrega.id]: { lista, mensagem: e instanceof Error ? e.message : "" },
        }));
      }
    } finally {
      setSalvando(null);
    }
  }

  return (
    <section className="mt-5 border border-atencao-borda rounded-cartao bg-atencao-claro overflow-hidden">
      <div className="px-5 py-4 border-b border-atencao-borda">
        <h2 className="flex gap-2 items-center m-0 text-tinta font-titulo text-lg font-semibold">
          Outros documentos identificados <Selo tom="info">{entregas.length}</Selo>
        </h2>
        <p className="mt-1 mb-0 text-tinta-2 text-sm leading-[1.55]">
          A IA identificou estes arquivos, mas eles não correspondem a um item do checklist deste caso.
          Eles continuam disponíveis no final e entram como contexto da análise e da petição.
        </p>
      </div>
      <ul className="m-0 p-0 list-none bg-papel">
        {entregas.map((entrega) => {
          const lendo = entrega.status_proc === "na_fila" || entrega.status_proc === "processando";
          return (
            <li key={entrega.id} className="px-5 py-4 border-b border-borda last:border-b-0">
              <div className="flex items-center gap-3 flex-wrap">
                <Selo tom={lendo ? "info" : entrega.status_proc === "erro" ? "critico" : "atencao"}>
                  {lendo ? "Lendo…" : entrega.status_proc === "erro" ? "Falha na leitura" : "Identificado"}
                </Selo>
                <button
                  type="button"
                  className="flex-1 min-w-[180px] border-none bg-transparent text-acao font-codigo text-xs text-left underline underline-offset-2 cursor-pointer [overflow-wrap:anywhere]"
                  onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}
                >
                  {entrega.arquivo}
                </button>
                <Botao variante="secundario" pequeno onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}>
                  Abrir documento
                </Botao>
              </div>

              <p className="mt-2 mb-0 text-sm text-tinta-2">
                Identificado pela IA: <strong className="text-tinta">{tituloDaLeitura(entrega.identificacao_ia || entrega.tipo_detectado)}</strong>
              </p>

              {entrega.alertas?.map((alerta, indice) => (
                <div className="mt-3" key={indice}>
                  <Aviso tom={entrega.status_proc === "erro" ? "critico" : "atencao"}>{alerta}</Aviso>
                </div>
              ))}

              {suspeitas[entrega.id] && (
                <div className="mt-3">
                  <AvisoDuplicidade
                    mensagem={suspeitas[entrega.id].mensagem}
                    duplicidades={suspeitas[entrega.id].lista}
                    itens={itens}
                    confirmando={salvando === entrega.id}
                    rotuloConfirmar="Atribuir mesmo assim"
                    onConfirmar={() => void atribuir(entrega, true)}
                    onCancelar={() => descartarSuspeita(entrega.id)}
                  />
                </div>
              )}

              {!lendo && (
                <div className="flex gap-2 items-end mt-3 flex-wrap">
                  <label className="flex-1 min-w-[240px] text-xs text-tinta-3">
                    Item correto do checklist
                    <select
                      className="block w-full min-h-10 mt-1 px-3 border border-borda-campo rounded-campo bg-papel text-tinta text-sm"
                      value={destinos[entrega.id] ?? ""}
                      onChange={(evento) => setDestinos((atual) => ({ ...atual, [entrega.id]: evento.target.value }))}
                    >
                      <option value="">Escolha o documento…</option>
                      {itens.map((item) => (
                        <option key={item.codigo} value={item.codigo}>{item.nome} ({item.codigo})</option>
                      ))}
                    </select>
                  </label>
                  <BotaoProcesso
                    variante="primario"
                    onClick={() => atribuir(entrega)}
                    processando={salvando === entrega.id}
                    textoProcessando="Atribuindo…"
                    pendencia={destinos[entrega.id] ? null : "Escolha ao lado o item correto do checklist."}
                    pendenciaAoClicar
                  >
                    Atribuir ao item
                  </BotaoProcesso>
                  <Botao variante="perigo" onClick={() => onRemover(entrega.id)}>Remover</Botao>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {visor && <VisorEntrega entregaId={visor.id} arquivo={visor.arquivo} onFechar={() => setVisor(null)} />}
    </section>
  );
}
