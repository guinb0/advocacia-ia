"use client";

import { useRef, useState } from "react";

import type { ItemSituacao, OpcoesReclassificacao } from "@/lib/types";
import { useModelo } from "@/lib/useExtracao";
import { baixarSelecaoDeDocumentos, baixarSelecaoEmPdf } from "@/lib/api";
import { Aviso, Botao, Marcacao, Selo } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
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
  /** O caso a que este item pertence — usado para gerar o ZIP da seleção. */
  casoId: string;
  enviando: boolean;
  onEnviar: (itemCodigo: string, arquivo: File, usarParaRgECpf?: boolean) => void;
  onRemover: (entregaId: string) => void;
  onVincularIdentidade: (entregaId: string, itemCodigo: string) => void;
  onReatribuir: (
    entregaId: string,
    itens: string[],
    opcoes?: OpcoesReclassificacao,
  ) => Promise<void> | void;
  dentroDoAtendimento?: boolean;
}

export default function ItemChecklistLinha({
  item,
  itensChecklist,
  casoId,
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

  /* Seleção para o pacote (ZIP ou PDF único). Guarda os ids marcados; um id de
   * entrega que depois some (removida) fica no conjunto sem efeito — é
   * filtrado contra as entregas atuais antes de qualquer uso. */
  const [marcados, setMarcados] = useState<Set<string>>(new Set());
  const [baixando, setBaixando] = useState<"zip" | "pdf" | null>(null);
  const [erroZip, setErroZip] = useState<string | null>(null);
  const [faltandoZip, setFaltandoZip] = useState(0);

  const idsEntregas = item.entregas.map((e) => e.id);
  const idsMarcados = idsEntregas.filter((id) => marcados.has(id));
  const todosMarcados = idsEntregas.length > 0 && idsMarcados.length === idsEntregas.length;

  function alternarMarcado(id: string) {
    setMarcados((atual) => {
      const proximo = new Set(atual);
      if (proximo.has(id)) proximo.delete(id);
      else proximo.add(id);
      return proximo;
    });
  }

  async function baixarSelecao(formato: "zip" | "pdf") {
    if (idsMarcados.length === 0) return;
    setBaixando(formato);
    setErroZip(null);
    setFaltandoZip(0);
    try {
      const pacote =
        formato === "zip"
          ? await baixarSelecaoDeDocumentos(casoId, item.codigo, idsMarcados)
          : await baixarSelecaoEmPdf(casoId, item.codigo, idsMarcados);
      setFaltandoZip(pacote.faltando);
      /* Mesmo motivo de `BaixarDocumentos`: o blob veio por `fetch` (o link cru
       * não manda o Bearer), e sem revogar a URL o pacote fica preso na
       * memória da aba. */
      const url = URL.createObjectURL(pacote.arquivo);
      const link = document.createElement("a");
      link.href = url;
      link.download = pacote.nome;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      const padrao =
        formato === "pdf"
          ? "Não foi possível combinar os arquivos num PDF. Tente baixar em ZIP."
          : "Não foi possível montar o pacote.";
      setErroZip(e instanceof Error ? e.message : padrao);
    } finally {
      setBaixando(null);
    }
  }
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
          carregando={enviando}
          textoCarregando="Enviando…"
          onClick={() => inputRef.current?.click()}
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

      {/* "Nada passa despercebido": o item falta como arquivo próprio, mas o dado
        * dele (CTPS, PIS) apareceu em outro documento. Indício, não entrega — o
        * advogado confere antes de dar por resolvido. */}
      {item.status === "pendente" && (item.encontrado_em?.length ?? 0) > 0 && (
        <div className="mt-2 ml-9 max-w-[74ch] border-l-[3px] border-atencao bg-papel-2 px-3 py-2 text-xs leading-[1.55] text-tinta-2">
          <strong className="text-tinta">Encontrado em outro documento.</strong>{" "}
          Não foi enviada em separado, mas apareceu:
          <ul className="mt-1 mb-0 list-disc pl-5">
            {item.encontrado_em!.map((achado, i) => (
              <li key={i}>
                <span className="text-tinta">{achado.dado}</span>{" "}
                <span className="text-tinta-3">em “{achado.arquivo}”</span>
              </li>
            ))}
          </ul>
        </div>
      )}

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
        <>
          {/* Selecionar arquivos desta classificação e baixar só eles — em ZIP
            * ou combinados num único PDF. A classificação é o próprio item —
            * o pacote nunca mistura entregas de outro. */}
          <div className="flex items-center gap-3 flex-wrap mt-[10px] ml-9">
            <Marcacao>
              <input
                type="checkbox"
                checked={todosMarcados}
                onChange={() =>
                  setMarcados(todosMarcados ? new Set() : new Set(idsEntregas))
                }
                disabled={!!baixando}
              />
              <span>
                Selecionar {item.entregas.length === 1 ? "o arquivo" : "todos"}
              </span>
            </Marcacao>
            <Botao
              variante="secundario"
              pequeno
              onClick={() => void baixarSelecao("zip")}
              disabled={!!baixando || idsMarcados.length === 0}
            >
              {baixando === "zip"
                ? "Montando o pacote…"
                : `Baixar ${idsMarcados.length || ""} selecionado${idsMarcados.length === 1 ? "" : "s"} (.zip)`}
            </Botao>
            {idsMarcados.length > 1 && (
              <Botao
                variante="secundario"
                pequeno
                onClick={() => void baixarSelecao("pdf")}
                disabled={!!baixando}
                title="Junta as páginas de todos os selecionados num único arquivo PDF"
              >
                {baixando === "pdf" ? "Combinando…" : "Baixar como um PDF único"}
              </Botao>
            )}
          </div>

          {faltandoZip > 0 && (
            <div className="mt-2 ml-9 max-w-[74ch]">
              <Aviso tom="atencao" titulo="O pacote saiu incompleto">
                {faltandoZip} {faltandoZip === 1 ? "arquivo constava" : "arquivos constavam"}{" "}
                na seleção mas não {faltandoZip === 1 ? "está" : "estão"} mais no disco.
              </Aviso>
            </div>
          )}
          {erroZip && (
            <div className="mt-2 ml-9 max-w-[74ch]">
              <Aviso tom="critico" titulo="Não foi possível baixar">
                {erroZip}
              </Aviso>
            </div>
          )}

          <ul className="list-none mt-[10px] ml-9 p-0 border border-borda rounded-campo bg-papel-2">
          {item.entregas.map((entrega) => (
            <li
              key={entrega.id}
              className="flex items-center gap-[10px] flex-wrap px-3 py-[10px] border-b border-borda last:border-b-0"
            >
              <input
                type="checkbox"
                className="flex-none"
                checked={marcados.has(entrega.id)}
                onChange={() => alternarMarcado(entrega.id)}
                disabled={!!baixando}
                aria-label={`Selecionar ${entrega.arquivo}`}
              />
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
                <BotaoProcesso
                  variante="discreto"
                  pequeno
                  onClick={() => onVincularIdentidade(entrega.id, item.codigo)}
                  aguardando={enviando ? "Aguarde: o arquivo novo ainda está sendo enviado." : false}
                  title="Confirme somente se este for um documento de identidade unificado"
                >
                  Usar também como {item.tipo_ocr === "rg" ? "CPF" : "RG"}
                </BotaoProcesso>
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

              {(() => {
                // Prefere `avisos` (com tom); cai em `alertas` (só texto, tratado
                // como nota) para respostas antigas do servidor. Nota de rotina
                // aparece quieta; só problema real ganha borda colorida.
                const avisos =
                  entrega.avisos ??
                  entrega.alertas.map((texto) => ({ texto, tom: "info" as const }));
                if (avisos.length === 0) return null;
                const ESTILO = {
                  info: {
                    caixa: "border-borda bg-papel-2 text-tinta-3",
                    marca: "text-tinta-3",
                    simbolo: "·",
                  },
                  atencao: {
                    caixa: "border-atencao-borda border-l-4 bg-atencao-claro text-tinta-2",
                    marca: "text-atencao font-bold",
                    simbolo: "!",
                  },
                  critico: {
                    caixa: "border-critico-borda border-l-4 bg-critico-claro text-tinta-2",
                    marca: "text-critico font-bold",
                    simbolo: "✕",
                  },
                } as const;
                return (
                  <ul className="[flex-basis:100%] list-none mt-[6px] p-0">
                    {avisos.map((aviso, i) => {
                      const estilo = ESTILO[aviso.tom] ?? ESTILO.info;
                      return (
                        <li
                          key={i}
                          className={`flex gap-2 px-[11px] py-2 mt-[5px] border rounded-campo text-xs leading-[1.55] ${estilo.caixa}`}
                        >
                          <span className={`flex-none ${estilo.marca}`} aria-hidden>
                            {estilo.simbolo}
                          </span>
                          {aviso.texto}
                        </li>
                      );
                    })}
                  </ul>
                );
              })()}
            </li>
          ))}
          </ul>
        </>
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
