"use client";

import { useRef, useState } from "react";

import { urlArquivoEntrega } from "@/lib/api";
import type { ItemSituacao } from "@/lib/types";
import { Tag } from "./Basicos";
import estilos from "./Checklist.module.css";
import ui from "./ui.module.css";

const APARENCIA = {
  entregue: { classe: estilos.entregue, icone: "✓", texto: "entregue" },
  conferir: { classe: estilos.conferir, icone: "!", texto: "conferir" },
  pendente: { classe: estilos.pendente, icone: "○", texto: "falta" },
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
  const aparencia = APARENCIA[item.status];
  const podeUsarParaAmbos = item.tipo_ocr === "rg" || item.tipo_ocr === "cpf";

  return (
    <li className={`${estilos.item} ${aparencia.classe}`}>
      <div className={estilos.cabecalhoItem}>
        <span className={estilos.marcador} aria-hidden>
          {enviando ? "…" : aparencia.icone}
        </span>

        <div className={estilos.identificacao}>
          <div className={estilos.nome}>
            {item.nome}
            {item.obrigatorio && <Tag tom="err">obrigatório</Tag>}
          </div>
          <div className={ui.observacao}>
            {item.codigo}
            {item.tipo_ocr && " · o sistema confere o tipo automaticamente"}
          </div>
        </div>

        <button
          type="button"
          className={estilos.botaoEnviar}
          onClick={() => inputRef.current?.click()}
          disabled={enviando}
        >
          {enviando ? "Lendo…" : item.entregas.length ? "Enviar outro" : "Enviar"}
        </button>

        <input
          ref={inputRef}
          type="file"
          accept="image/*"
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

      {podeUsarParaAmbos && (
        <label className={estilos.opcaoCIN}>
          <input
            type="checkbox"
            checked={usarParaRgECpf}
            onChange={(e) => setUsarParaRgECpf(e.target.checked)}
            disabled={enviando}
          />
          Esta é uma CIN (identidade unificada): usar este arquivo para RG e CPF.
        </label>
      )}

      {item.entregas.length > 0 && (
        <ul className={estilos.entregas}>
          {item.entregas.map((entrega) => (
            <li key={entrega.id} className={estilos.entrega}>
              <a
                href={urlArquivoEntrega(entrega.id)}
                target="_blank"
                rel="noreferrer"
                className={estilos.arquivo}
              >
                {entrega.arquivo}
              </a>

              {entrega.score_legibilidade !== null && (
                <span className={ui.observacao}>legibilidade {entrega.score_legibilidade}%</span>
              )}

              {entrega.dados_utilizaveis || entrega.confirmado_manual ? (
                <Tag tom="ok">{entrega.confirmado_manual ? "confirmado" : "ok"}</Tag>
              ) : (
                <Tag tom="warn">revisar</Tag>
              )}

              {(entrega.itens_atendidos?.length ?? 1) > 1 && (
                <Tag tom="ok">vale para RG e CPF</Tag>
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
    </li>
  );
}
