"use client";

import { useRef, useState } from "react";

import type { ItemSituacao } from "@/lib/types";
import { useModelo } from "@/lib/useExtracao";
import { Botao, Marcacao, Selo } from "@/components/ui/Basicos";
import ProgressoOcr from "@/components/ui/ProgressoOcr";
import VisorEntrega from "@/components/caso/VisorEntrega";
import CorrigirItemDocumento from "@/components/caso/CorrigirItemDocumento";

/* A lista não pré-visualiza nada: cada entrega aparece só como enviada, e o
 * arquivo abre no visor ao clique. Além de deixar o checklist limpo, isso evita
 * baixar a imagem inteira de toda entrega só para desenhar um quadrado de 46px —
 * um caso com 20 documentos puxava os 20 arquivos ao abrir. */

/* Cada estado carrega símbolo, palavra e tom. Antes eram só palavras em caixa
 * alta ("FALTA", "CONFERIR") coloridas: quem não distingue vermelho de âmbar
 * lia dois avisos idênticos, e "CONFERIR" não dizia o que fazer. */
const APARENCIA = {
  entregue: {
    borda: "var(--ok)",
    fundo: "",
    marcador: "border-ok-borda bg-ok-claro text-ok",
    texto: "Entregue",
    simbolo: "✓",
    tom: "ok",
    dica: null,
  },
  processando: {
    borda: "var(--acao)",
    fundo: "",
    marcador: "border-acao-borda bg-acao-clara text-acao",
    texto: "Lendo",
    simbolo: "◌",
    tom: "info",
    dica: "O arquivo chegou e está sendo lido. Pode continuar em outra coisa.",
  },
  conferir: {
    borda: "var(--atencao-marca)",
    fundo: "bg-atencao-claro",
    marcador: "border-atencao-borda bg-papel text-atencao",
    texto: "Confira",
    simbolo: "!",
    tom: "atencao",
    dica: "O arquivo chegou, mas a leitura encontrou um problema. Veja abaixo o motivo.",
  },
  pendente: {
    borda: "var(--critico)",
    fundo: "",
    marcador: "border-critico-borda bg-critico-claro text-critico",
    texto: "Falta enviar",
    simbolo: "✕",
    tom: "critico",
    dica: null,
  },
} as const;

interface Props {
  item: ItemSituacao;
  itensChecklist: ItemSituacao[];
  enviando: boolean;
  onEnviar: (itemCodigo: string, arquivo: File, usarParaRgECpf?: boolean) => void;
  onRemover: (entregaId: string) => void;
  onVincularIdentidade: (entregaId: string, itemCodigo: string) => void;
  onReatribuir: (entregaId: string, itens: string[]) => Promise<void> | void;
  dentroDoAtendimento?: boolean;
}

export default function ItemChecklistLinha({
  item,
  itensChecklist,
  enviando,
  onEnviar,
  onRemover,
  onVincularIdentidade,
  onReatribuir,
  dentroDoAtendimento = false,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [usarParaRgECpf, setUsarParaRgECpf] = useState(false);
  /** Entrega aberta no visor (arquivo + campos extraídos). */
  const [visor, setVisor] = useState<{ id: string; arquivo: string } | null>(null);
  const estadoModelo = useModelo();
  const aparencia = APARENCIA[item.status];
  const podeUsarParaAmbos = item.tipo_ocr === "rg" || item.tipo_ocr === "cpf";
  const lendoAgora = item.entregas.some((entrega) => entrega.status_proc === "processando");
  const aguardandoNaFila =
    !lendoAgora && item.entregas.some((entrega) => entrega.status_proc === "na_fila");

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
    <li
      className={`px-[18px] py-[14px] border-b border-borda border-l-4 last:border-b-0 ${aparencia.fundo}`}
      style={{ borderLeftColor: aparencia.borda }}
    >
      <div className="flex gap-3 items-center flex-wrap">
        <span
          className={`flex-none grid place-items-center w-6 h-6 border-[1.5px] rounded-full text-xs font-bold leading-none ${aparencia.marcador}`}
          aria-hidden
        >
          {aparencia.simbolo}
        </span>

        <span className="flex-1 min-w-[180px] flex items-center gap-[9px] flex-wrap text-tinta text-base font-medium leading-[1.35]">
          {item.nome}
          {item.obrigatorio && <Selo tom="neutro">Obrigatório</Selo>}
          <span className="flex-none text-tinta-3 font-codigo text-xs tabular-nums">{item.codigo}</span>
        </span>

        {melhorScore !== null && (
          <span
            className="flex-none text-tinta-3 text-xs tabular-nums"
            title="Nitidez medida na leitura do arquivo"
          >
            nitidez {melhorScore}%
          </span>
        )}

        <Selo tom={enviando ? "info" : aparencia.tom} simbolo={enviando ? "◌" : aparencia.simbolo}>
          {enviando ? "Lendo…" : aparencia.texto}
        </Selo>

        <Botao
          variante={item.entregas.length ? "secundario" : "primario"}
          pequeno
          onClick={() => inputRef.current?.click()}
          disabled={enviando}
        >
          {item.entregas.length ? "Enviar outro arquivo" : "Enviar arquivo"}
        </Botao>

        <input
          ref={inputRef}
          type="file"
          hidden
          onChange={(e) => {
            const arquivo = e.target.files?.[0];
            if (arquivo) onEnviar(item.codigo, arquivo, usarParaRgECpf);
            // Zera para permitir reenviar o mesmo arquivo depois de corrigi-lo.
            e.target.value = "";
            setUsarParaRgECpf(false);
          }}
        />

        {aparencia.dica && !enviando && (
          <span className="[flex-basis:100%] mt-1 ml-9 text-tinta-3 text-xs leading-[1.5]">
            {aparencia.dica}
          </span>
        )}
      </div>

      {(enviando || item.status === "processando") && (
        <ProgressoOcr modeloPronto={estadoModelo === "pronto"} naFila={!enviando && aguardandoNaFila} />
      )}

      {podeUsarParaAmbos && (
        <Marcacao className="mt-2 ml-9 max-w-[74ch]">
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
        </Marcacao>
      )}

      {item.entregas.length > 0 && (
        <ul className="list-none mt-[10px] ml-9 p-0 border border-borda rounded-campo bg-papel-2">
          {item.entregas.map((entrega) => (
            <li
              key={entrega.id}
              className="flex items-center gap-[10px] flex-wrap px-3 py-[10px] border-b border-borda last:border-b-0"
            >
              <Selo tom="ok" simbolo="✓">
                Recebido
              </Selo>

              <button
                type="button"
                className="flex-1 min-w-[150px] py-[2px] border-none bg-transparent text-acao font-codigo text-xs text-left underline underline-offset-2 [overflow-wrap:anywhere] cursor-pointer hover:text-acao-forte"
                onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}
                title="Abrir o documento e os dados extraídos"
              >
                {entrega.arquivo}
              </button>

              {(entrega.itens_atendidos?.length ?? 1) > 1 && (
                <Selo tom="info">Vale para RG e CPF</Selo>
              )}

              <Botao
                variante="secundario"
                pequeno
                onClick={() => setVisor({ id: entrega.id, arquivo: entrega.arquivo })}
              >
                Ver o que foi lido
              </Botao>

              {podeUsarParaAmbos && (entrega.itens_atendidos?.length ?? 1) === 1 && (
                <Botao
                  variante="discreto"
                  pequeno
                  onClick={() => onVincularIdentidade(entrega.id, item.codigo)}
                  disabled={enviando}
                  title="Confirme somente se este for um documento de identidade unificado"
                >
                  Usar também como {item.tipo_ocr === "rg" ? "CPF" : "RG"}
                </Botao>
              )}

              <Botao variante="perigo" pequeno onClick={() => onRemover(entrega.id)}>
                Remover
              </Botao>

              {entrega.status_proc !== "na_fila" && entrega.status_proc !== "processando" && (
                <CorrigirItemDocumento
                  entregaId={entrega.id}
                  itemAtual={item.codigo}
                  itens={itensChecklist}
                  onReatribuir={onReatribuir}
                  expandidoPorPadrao={dentroDoAtendimento}
                  destacar={
                    dentroDoAtendimento
                    || entrega.roteamento_origem === "deterministico"
                    || entrega.tipo_confere === false
                    || entrega.tipo_detectado === "ctps"
                  }
                />
              )}

              {entrega.alertas.length > 0 && (
                <ul className="[flex-basis:100%] list-none mt-[6px] p-0">
                  {entrega.alertas.map((alerta, i) => (
                    <li
                      key={i}
                      className="flex gap-2 px-[11px] py-2 mt-[5px] border border-atencao-borda border-l-4 rounded-campo bg-atencao-claro text-tinta-2 text-xs leading-[1.55]"
                    >
                      <span className="flex-none text-atencao font-bold" aria-hidden>
                        !
                      </span>
                      {alerta}
                    </li>
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
