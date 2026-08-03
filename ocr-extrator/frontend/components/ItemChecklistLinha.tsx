"use client";

import { useRef } from "react";

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
  onEnviar: (itemCodigo: string, arquivo: File) => void;
  onRemover: (entregaId: string) => void;
}

export default function ItemChecklistLinha({ item, enviando, onEnviar, onRemover }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const aparencia = APARENCIA[item.status];

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
            if (arquivo) onEnviar(item.codigo, arquivo);
            // Zera para permitir reenviar o mesmo arquivo depois de corrigi-lo.
            e.target.value = "";
          }}
        />
      </div>

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

              {entrega.dados_utilizaveis && entrega.tipo_confere !== false ? (
                <Tag tom="ok">ok</Tag>
              ) : (
                <Tag tom="warn">revisar</Tag>
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
