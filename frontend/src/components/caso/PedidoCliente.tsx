"use client";

import { useCallback, useEffect, useState } from "react";

import { obterPedido } from "@/lib/api";
import type { Pedido, Progresso } from "@/lib/types";
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
        </>
      )}
    </Cartao>
  );
}
