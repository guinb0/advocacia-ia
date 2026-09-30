"use client";

/**
 * As peças já protocoladas, de todos os casos: cliente, número e data do protocolo.
 *
 * A marcação é feita no dossiê, no cartão de protocolo abaixo da petição
 * (`ProtocoloDaPeticao`); aqui é só a consulta. A lista vem da petição inicial de
 * cada caso — as peças avulsas não têm protocolo registrado.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Search } from "lucide-react";

import { Aviso, Botao, Campo, Tabela, Td, Th, TrZebra, ValorTabela, Vazio } from "@/components/ui/Basicos";
import { listarPeticoesProtocoladas, type PeticaoProtocolada } from "@/lib/agente";

function dataBr(iso: string): string {
  const [ano, mes, dia] = iso.split("-");
  return ano && mes && dia ? `${dia}/${mes}/${ano}` : iso;
}

export default function PecasProtocoladas({ onAbrirDossie }: { onAbrirDossie: (casoId: string) => void }) {
  const [peticoes, setPeticoes] = useState<PeticaoProtocolada[] | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [busca, setBusca] = useState("");

  const recarregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      setPeticoes(await listarPeticoesProtocoladas());
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível carregar as peças protocoladas.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  const lista = useMemo(() => {
    const termo = busca.trim().toLocaleLowerCase();
    if (!termo) return peticoes ?? [];
    return (peticoes ?? []).filter(
      (p) =>
        p.cliente.toLocaleLowerCase().includes(termo) ||
        p.numero.toLocaleLowerCase().includes(termo) ||
        p.titulo.toLocaleLowerCase().includes(termo),
    );
  }, [peticoes, busca]);

  return (
    <div className="grid min-w-0 gap-5">
      <header className="flex min-w-0 flex-wrap items-start justify-between gap-5">
        <div className="min-w-0 max-w-[62ch]">
          <h1 className="m-0 font-titulo text-[1.75rem] font-semibold leading-[1.15] text-tinta">
            Peças protocoladas
          </h1>
          <p className="mt-2 mb-0 text-sm leading-[1.55] text-tinta-3">
            Petições já enviadas ao tribunal, com o número e a data do protocolo. Para marcar uma
            peça, abra o dossiê do caso e use &ldquo;Marcar como protocolada&rdquo; abaixo da petição.
          </p>
        </div>
        {peticoes && (
          <div className="min-w-[124px] rounded-cartao border border-borda-forte bg-papel px-4 py-3">
            <strong className="block font-titulo text-[1.6rem] font-semibold leading-none tabular-nums text-tinta">
              {peticoes.length}
            </strong>
            <span className="mt-[6px] block text-[11px] font-semibold uppercase tracking-[0.08em] text-tinta-3">
              Protocoladas
            </span>
          </div>
        )}
      </header>

      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] flex-1 sm:max-w-[360px]">
          <Search
            size={16}
            strokeWidth={2}
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-tinta-3"
          />
          <Campo
            className="min-h-10 pl-9 text-sm"
            type="search"
            value={busca}
            aria-label="Buscar por cliente ou número do protocolo"
            placeholder="Buscar por cliente ou número do protocolo"
            onChange={(e) => setBusca(e.target.value)}
          />
        </div>
        <Botao variante="secundario" pequeno className="ml-auto" onClick={() => void recarregar()} disabled={carregando}>
          <RefreshCw size={14} strokeWidth={2} aria-hidden />
          {carregando ? "Atualizando…" : "Atualizar"}
        </Botao>
      </div>

      {erro ? (
        <Aviso tom="critico" titulo="Não foi possível carregar">
          {erro}
        </Aviso>
      ) : carregando && !peticoes ? (
        <Vazio>Carregando as peças protocoladas…</Vazio>
      ) : lista.length === 0 ? (
        <Vazio>
          {busca.trim()
            ? `Nenhuma peça protocolada encontrada para “${busca.trim()}”.`
            : "Nenhuma peça foi marcada como protocolada ainda."}
        </Vazio>
      ) : (
        <div className="min-w-0 overflow-x-auto rounded-cartao border border-borda-forte bg-papel">
          <Tabela>
            <thead>
              <tr>
                <Th>Cliente</Th>
                <Th>Peça</Th>
                <Th>Nº do protocolo</Th>
                <Th>Data</Th>
                <Th>Marcado por</Th>
                <Th>
                  <span className="sr-only">Ações</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {lista.map((peca) => (
                <TrZebra key={peca.caso_id}>
                  <Td>
                    <strong className="[overflow-wrap:anywhere]">{peca.cliente || "Cliente sem nome"}</strong>
                  </Td>
                  <Td>{peca.titulo}</Td>
                  <ValorTabela className="select-all">
                    {peca.numero || <span className="font-ui text-tinta-3">não informado</span>}
                  </ValorTabela>
                  <ValorTabela className="whitespace-nowrap">{dataBr(peca.data)}</ValorTabela>
                  <Td>{peca.marcado_por || "—"}</Td>
                  <Td className="text-right">
                    <Botao variante="secundario" pequeno className="whitespace-nowrap" onClick={() => onAbrirDossie(peca.caso_id)}>
                      Abrir dossiê
                    </Botao>
                  </Td>
                </TrZebra>
              ))}
            </tbody>
          </Tabela>
        </div>
      )}
    </div>
  );
}
