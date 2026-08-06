"use client";

import { useRef, useState } from "react";

import type { ItemSituacao } from "@/lib/types";
import { useModelo } from "@/lib/useExtracao";
import estilos from "./Checklist.module.css";
import ProgressoOcr from "./ProgressoOcr";
import VisorEntrega from "./VisorEntrega";

/* A lista não pré-visualiza nada: cada entrega aparece só como enviada, e o
 * arquivo abre no visor ao clique. Além de deixar o checklist limpo, isso evita
 * baixar a imagem inteira de toda entrega só para desenhar um quadrado de 46px —
 * um caso com 20 documentos puxava os 20 arquivos ao abrir. */

const APARENCIA = {
  entregue: { classe: estilos.entregue, texto: "ENTREGUE" },
  processando: { classe: estilos.conferir, texto: "LENDO" },
  conferir: { classe: estilos.conferir, texto: "CONFERIR" },
  pendente: { classe: estilos.pendente, texto: "FALTA" },
} as const;

interface Props {
  item: ItemSituacao;
  enviando: boolean;
  onEnviar: (itemCodigo: string, arquivo: File, usarParaRgECpf?: boolean) => void;
  onRemover: (entregaId: string) => void;
  onVincularIdentidade: (entregaId: string, itemCodigo: string) => void;
}

export default function ItemChecklistLinha({
  item,
  enviando,
  onEnviar,
  onRemover,
  onVincularIdentidade,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [usarParaRgECpf, setUsarParaRgECpf] = useState(false);
  /** Entrega aberta no visor (arquivo + campos extraídos). */
  const [visor, setVisor] = useState<{ id: string; arquivo: string } | null>(null);
  const estadoModelo = useModelo();
  const aparencia = APARENCIA[item.status];
  const podeUsarParaAmbos = item.tipo_ocr === "rg" || item.tipo_ocr === "cpf";

  // A legibilidade que interessa é a da entrega que resolveu o item.
  const melhorScore = item.entregas.reduce<number | null>(
    (melhor, e) =>
      e.score_legibilidade === null
        ? melhor
        : melhor === null
          ? e.score_legibilidade
          : Math.max(melhor, e.score_legibilidade),
    null,
  );

  return (
    <li className={`${estilos.item} ${aparencia.classe}`}>
      <div className={estilos.cabecalhoItem}>
        <span className={estilos.marcador} aria-hidden />

        <span className={estilos.codigo}>{item.codigo}</span>

        <span className={estilos.nome}>
          {item.nome}
          {item.obrigatorio && <span className={estilos.obrigatorio}>OBRIGATÓRIO</span>}
        </span>

        {melhorScore !== null && (
          <span className={estilos.legibilidade}>legib. {melhorScore}%</span>
        )}

        <span
          className={
            item.status === "conferir" ? estilos.carimboConferir : estilos.situacaoItem
          }
        >
          {enviando ? "LENDO…" : aparencia.texto}
        </span>

        <button
          type="button"
          className={estilos.botaoEnviar}
          onClick={() => inputRef.current?.click()}
          disabled={enviando}
        >
          {item.entregas.length ? "Enviar outro" : "Enviar"}
        </button>

        <input
          ref={inputRef}
          type="file"
          accept="image/*,application/pdf,.pdf"
          hidden
          onChange={(e) => {
            const arquivo = e.target.files?.[0];
            if (arquivo) onEnviar(item.codigo, arquivo, usarParaRgECpf);
            // Zera para permitir reenviar o mesmo arquivo depois de corrigi-lo.
            e.target.value = "";
            setUsarParaRgECpf(false);
          }}
        />
      </div>

      {(enviando || item.status === "processando") && (
        <ProgressoOcr modeloPronto={estadoModelo === "pronto"} />
      )}

      {podeUsarParaAmbos && (
        <label className={estilos.opcaoCIN}>
          <input
            type="checkbox"
            checked={usarParaRgECpf}
            onChange={(e) => setUsarParaRgECpf(e.target.checked)}
            disabled={enviando}
          />
          Forçar identidade unificada (RG e CPF no mesmo arquivo). CNH e CIN já são
          reconhecidas sozinhas — marque só se a leitura não tiver identificado.
        </label>
      )}

      {item.entregas.length > 0 && (
        <ul className={estilos.entregas}>
          {item.entregas.map((entrega) => (
            <li key={entrega.id} className={estilos.entrega}>
              <span className={estilos.selo} aria-hidden>
                ENVIADO
              </span>

              <button
                type="button"
                className={estilos.arquivo}
                onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}
                title="Abrir o documento e os dados extraídos"
              >
                {entrega.arquivo}
              </button>

              <button
                type="button"
                className={estilos.botaoDados}
                onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}
              >
                Ver informações extraídas
              </button>

              {(entrega.itens_atendidos?.length ?? 1) > 1 && (
                <span className={estilos.obrigatorio}>CIN · VALE PARA RG E CPF</span>
              )}

              {podeUsarParaAmbos && (entrega.itens_atendidos?.length ?? 1) === 1 && (
                <button
                  type="button"
                  className={estilos.vincularCIN}
                  onClick={() => onVincularIdentidade(entrega.id, item.codigo)}
                  disabled={enviando}
                  title="Confirme somente se este for um documento de identidade unificado"
                >
                  Usar também como {item.tipo_ocr === "rg" ? "CPF" : "RG"}
                </button>
              )}

              <button
                type="button"
                className={estilos.remover}
                onClick={() => onRemover(entrega.id)}
                title="Remover este arquivo"
              >
                ✕
              </button>

              {entrega.alertas.length > 0 && (
                <ul className={estilos.alertas}>
                  {entrega.alertas.map((alerta, i) => (
                    <li key={i}>{alerta}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}

      {visor && (
        <VisorEntrega
          entregaId={visor.id}
          arquivo={visor.arquivo}
          onFechar={() => setVisor(null)}
        />
      )}
    </li>
  );
}
