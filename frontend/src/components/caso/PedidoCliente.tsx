"use client";

import { useCallback, useEffect, useState } from "react";

import { obterCobrancaDocumentos, obterPedido, salvarCobrancaDocumentos } from "@/lib/api";
import type { CobrancaDocumentos, Pedido, Progresso } from "@/lib/types";
import { AjudaCampo, Botao, Cartao, Marcacao, RotuloCampo, Vazio } from "@/components/ui/Basicos";

/** Painel que gera o texto pronto para o advogado mandar ao cliente. */
export default function PedidoCliente({
  casoId,
  progresso,
  naoResolvidos,
}: {
  casoId: string;
  /** Só serve para refazer o pedido quando algo muda no checklist. */
  progresso: Progresso;
  /** Quantos itens do checklist ainda entram no texto do pedido. */
  naoResolvidos: number;
}) {
  const [pedido, setPedido] = useState<Pedido | null>(null);
  const [incluirOpcionais, setIncluirOpcionais] = useState(false);
  const [copiado, setCopiado] = useState(false);
  const [cobranca, setCobranca] = useState<CobrancaDocumentos | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [retorno, setRetorno] = useState("");

  const chave = `${progresso.obrigatorios_entregues}-${progresso.itens_a_conferir}-${progresso.opcionais_entregues}`;

  useEffect(() => {
    let cancelado = false;
    obterPedido(casoId, incluirOpcionais)
      .then((p) => {
        if (!cancelado) setPedido(p);
      })
      .catch(() => {
        if (!cancelado) setPedido(null);
      });
    return () => {
      cancelado = true;
    };
  }, [casoId, incluirOpcionais, chave]);

  useEffect(() => {
    obterCobrancaDocumentos(casoId).then(setCobranca).catch(() => setCobranca(null));
  }, [casoId]);

  const salvarAutomacao = useCallback(async () => {
    if (!cobranca) return;
    setSalvando(true);
    setRetorno("");
    try {
      const atualizada = await salvarCobrancaDocumentos(casoId, cobranca);
      setCobranca(atualizada);
      setRetorno(atualizada.ativa ? "Cobrança automática ativada." : "Cobrança automática desativada.");
    } catch (e) {
      setRetorno(e instanceof Error ? e.message : "Não foi possível salvar a automação.");
    } finally {
      setSalvando(false);
    }
  }, [casoId, cobranca]);

  const copiar = useCallback(async () => {
    if (!pedido) return;
    try {
      await navigator.clipboard.writeText(pedido.texto);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch {
      // Sem permissão de área de transferência: o texto continua visível para
      // seleção manual, então não vale interromper o fluxo com um erro.
      setCopiado(false);
    }
  }, [pedido]);

  return (
    <Cartao
      titulo="Pedido para o cliente"
      subtitulo={
        naoResolvidos === 0
          ? "Nada pendente — o texto abaixo só confirma o que já foi recebido."
          : `${naoResolvidos} ${naoResolvidos === 1 ? "item pendente virou" : "itens pendentes viraram"} a mensagem abaixo. Cole no WhatsApp ou no e-mail do cliente.`
      }
    >
      {pedido === null ? (
        <Vazio>Montando o pedido…</Vazio>
      ) : (
        <>
          <div className="flex items-center gap-[14px] mb-[14px] flex-wrap">
            {/* A ação principal do bloco é copiar: é para isso que o bloco existe. */}
            <Botao variante="primario" onClick={copiar}>
              {copiado ? "✓ Mensagem copiada" : "Copiar a mensagem"}
            </Botao>
            <Marcacao>
              <input
                type="checkbox"
                checked={incluirOpcionais}
                onChange={(e) => setIncluirOpcionais(e.target.checked)}
              />
              <span>Incluir também os documentos opcionais</span>
            </Marcacao>
          </div>

          <RotuloCampo htmlFor="texto-pedido">Mensagem gerada</RotuloCampo>
          <textarea
            id="texto-pedido"
            className="w-full p-[14px] border border-borda-campo rounded-campo bg-papel-2 text-tinta font-codigo text-xs leading-[1.65] resize-y focus:border-acao focus:shadow-[0_0_0_3px_var(--acao-clara)] focus:outline-none"
            value={pedido.texto}
            readOnly
            rows={12}
          />

          <AjudaCampo>
            O texto se refaz sozinho conforme os documentos chegam — não precisa editar aqui.
          </AjudaCampo>

          {cobranca && (
            <div className="mt-5 border-t border-borda pt-4">
              <div className="flex items-center gap-3 flex-wrap">
                <Marcacao>
                  <input
                    type="checkbox"
                    checked={cobranca.ativa}
                    onChange={(e) => setCobranca({ ...cobranca, ativa: e.target.checked })}
                  />
                  <span>Cobrar documentos automaticamente pelo WhatsApp</span>
                </Marcacao>
              </div>
              <div className="grid grid-cols-[minmax(220px,1fr)_150px] gap-3 mt-3 max-[640px]:grid-cols-1">
                <label className="text-xs text-tinta-3">
                  WhatsApp do cliente
                  <input
                    className="block w-full mt-1 p-2 border border-borda-campo rounded-campo bg-papel text-tinta"
                    value={cobranca.telefone}
                    onChange={(e) => setCobranca({ ...cobranca, telefone: e.target.value })}
                    placeholder="(61) 99999-9999"
                  />
                </label>
                <label className="text-xs text-tinta-3">
                  Repetir a cada
                  <select
                    className="block w-full mt-1 p-2 border border-borda-campo rounded-campo bg-papel text-tinta"
                    value={cobranca.intervalo_dias}
                    onChange={(e) => setCobranca({ ...cobranca, intervalo_dias: Number(e.target.value) })}
                  >
                    {[1, 2, 3, 5, 7, 14].map((dias) => <option key={dias} value={dias}>{dias} {dias === 1 ? "dia" : "dias"}</option>)}
                  </select>
                </label>
              </div>
              <Marcacao className="mt-3">
                <input
                  type="checkbox"
                  checked={cobranca.incluir_opcionais}
                  onChange={(e) => setCobranca({ ...cobranca, incluir_opcionais: e.target.checked })}
                />
                <span>Incluir documentos opcionais nas cobranças</span>
              </Marcacao>
              <div className="mt-3 flex items-center gap-3 flex-wrap">
                <Botao variante="primario" onClick={() => void salvarAutomacao()} disabled={salvando}>
                  {salvando ? "Salvando…" : "Salvar automação"}
                </Botao>
                {retorno && <span className="text-xs text-tinta-3">{retorno}</span>}
              </div>
              <AjudaCampo>
                Cada envio usa a mensagem acima refeita naquele momento. Quando o cliente envia outro arquivo, a próxima cobrança já remove o que chegou e inclui apenas o que continua pendente.
              </AjudaCampo>
            </div>
          )}
        </>
      )}
    </Cartao>
  );
}
