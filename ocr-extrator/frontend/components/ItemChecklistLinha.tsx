"use client";

import { useRef, useState } from "react";

import type { ItemSituacao } from "@/lib/types";
import { useModelo } from "@/lib/useExtracao";
import { Selo } from "./Basicos";
import estilos from "./Checklist.module.css";
import ProgressoOcr from "./ProgressoOcr";
import VisorEntrega from "./VisorEntrega";

/* A lista não pré-visualiza nada: cada entrega aparece só como enviada, e o
 * arquivo abre no visor ao clique. Além de deixar o checklist limpo, isso evita
 * baixar a imagem inteira de toda entrega só para desenhar um quadrado de 46px —
 * um caso com 20 documentos puxava os 20 arquivos ao abrir. */

/* Cada estado carrega símbolo, palavra e tom. Antes eram só palavras em caixa
 * alta ("FALTA", "CONFERIR") coloridas: quem não distingue vermelho de âmbar
 * lia dois avisos idênticos, e "CONFERIR" não dizia o que fazer. */
const APARENCIA = {
  entregue: {
    classe: estilos.entregue,
    texto: "Entregue",
    simbolo: "✓",
    tom: "ok",
    dica: null,
  },
  processando: {
    classe: estilos.processando,
    texto: "Lendo",
    simbolo: "◌",
    tom: "info",
    dica: "O arquivo chegou e está sendo lido. Pode continuar em outra coisa.",
  },
  conferir: {
    classe: estilos.conferir,
    texto: "Confira",
    simbolo: "!",
    tom: "atencao",
    dica: "O arquivo chegou, mas a leitura encontrou um problema. Veja abaixo o motivo.",
  },
  pendente: {
    classe: estilos.pendente,
    texto: "Falta enviar",
    simbolo: "✕",
    tom: "critico",
    dica: null,
  },
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
        <span className={estilos.marcador} aria-hidden>
          {aparencia.simbolo}
        </span>

        <span className={estilos.nome}>
          {item.nome}
          {item.obrigatorio && <Selo tom="neutro">Obrigatório</Selo>}
          <span className={estilos.codigo}>{item.codigo}</span>
        </span>

        {melhorScore !== null && (
          <span className={estilos.legibilidade} title="Nitidez medida na leitura do arquivo">
            nitidez {melhorScore}%
          </span>
        )}

        <Selo tom={enviando ? "info" : aparencia.tom} simbolo={enviando ? "◌" : aparencia.simbolo}>
          {enviando ? "Lendo…" : aparencia.texto}
        </Selo>

        <button
          type="button"
          className={`botao ${item.entregas.length ? "botao--secundario" : "botao--primario"} botao--pequeno`}
          onClick={() => inputRef.current?.click()}
          disabled={enviando}
        >
          {item.entregas.length ? "Enviar outro arquivo" : "Enviar arquivo"}
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

        {aparencia.dica && !enviando && <span className={estilos.dica}>{aparencia.dica}</span>}
      </div>

      {(enviando || item.status === "processando") && (
        <ProgressoOcr modeloPronto={estadoModelo === "pronto"} />
      )}

      {podeUsarParaAmbos && (
        <label className={`marcacao ${estilos.opcaoCIN}`}>
          <input
            type="checkbox"
            checked={usarParaRgECpf}
            onChange={(e) => setUsarParaRgECpf(e.target.checked)}
            disabled={enviando}
          />
          <span>
            Este arquivo vale como RG <strong>e</strong> CPF (documento de identidade
            unificado). A CNH e a CIN já são reconhecidas sozinhas — marque só se a leitura não
            tiver identificado.
          </span>
        </label>
      )}

      {item.entregas.length > 0 && (
        <ul className={estilos.entregas}>
          {item.entregas.map((entrega) => (
            <li key={entrega.id} className={estilos.entrega}>
              <Selo tom="ok" simbolo="✓">
                Recebido
              </Selo>

              <button
                type="button"
                className={estilos.arquivo}
                onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}
                title="Abrir o documento e os dados extraídos"
              >
                {entrega.arquivo}
              </button>

              {(entrega.itens_atendidos?.length ?? 1) > 1 && (
                <Selo tom="info">Vale para RG e CPF</Selo>
              )}

              <button
                type="button"
                className="botao botao--secundario botao--pequeno"
                onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}
              >
                Ver o que foi lido
              </button>

              {podeUsarParaAmbos && (entrega.itens_atendidos?.length ?? 1) === 1 && (
                <button
                  type="button"
                  className="botao botao--discreto botao--pequeno"
                  onClick={() => onVincularIdentidade(entrega.id, item.codigo)}
                  disabled={enviando}
                  title="Confirme somente se este for um documento de identidade unificado"
                >
                  Usar também como {item.tipo_ocr === "rg" ? "CPF" : "RG"}
                </button>
              )}

              <button
                type="button"
                className="botao botao--perigo botao--pequeno"
                onClick={() => onRemover(entrega.id)}
              >
                Remover
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
