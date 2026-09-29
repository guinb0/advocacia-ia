"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import estilos from "@/components/admin/ChatPeticao.module.css";
import type { DocumentoCitavel } from "@/lib/chatPeticao";

export type FiltroDosDocumentos = "todos" | "lidos" | "sem_leitura";

/** O motivo, em uma palavra, de o chat ainda não conseguir usar o documento. */
const SEM_LEITURA: Record<string, string> = {
  na_fila: "Na fila da leitura",
  processando: "Sendo lido agora",
  erro: "A leitura falhou",
  sem_texto: "Sem texto legível",
};

interface Props {
  documentos: DocumentoCitavel[];
  filtroInicial: FiltroDosDocumentos;
  /** Recebe também a lista na ordem da tela: é ela que o visor percorre com ← →. */
  aoAbrir: (documento: DocumentoCitavel, lista: DocumentoCitavel[]) => void;
  aoPerguntar: (documento: DocumentoCitavel) => void;
  aoFechar: () => void;
}

const lido = (d: DocumentoCitavel) => d.situacao === "lido";

/** Consulta rápida aos anexos do caso sem sair da conversa: abrir, passar de um para o
 *  outro e perguntar sobre um deles. */
export default function DocumentosDaConversa({
  documentos,
  filtroInicial,
  aoAbrir,
  aoPerguntar,
  aoFechar,
}: Props) {
  const [filtro, setFiltro] = useState<FiltroDosDocumentos>(filtroInicial);
  const [busca, setBusca] = useState("");
  const campoBusca = useRef<HTMLInputElement>(null);

  /* No toque, focar a busca abriria o teclado por cima da lista que a pessoa quer ver. */
  useEffect(() => {
    if (window.matchMedia("(hover: hover)").matches) campoBusca.current?.focus();
  }, []);

  const totais = useMemo(() => {
    const lidos = documentos.filter(lido).length;
    return { todos: documentos.length, lidos, sem_leitura: documentos.length - lidos };
  }, [documentos]);

  const visiveis = useMemo(() => {
    const termo = busca.trim().toLocaleLowerCase("pt-BR");
    return documentos.filter((d) => {
      if (filtro === "lidos" && !lido(d)) return false;
      if (filtro === "sem_leitura" && lido(d)) return false;
      if (!termo) return true;
      return `${d.tipo} ${d.arquivo}`.toLocaleLowerCase("pt-BR").includes(termo);
    });
  }, [documentos, filtro, busca]);

  const filtros: Array<{ valor: FiltroDosDocumentos; rotulo: string }> = [
    { valor: "todos", rotulo: "Todos" },
    { valor: "lidos", rotulo: "Lidos" },
    ...(totais.sem_leitura > 0 || filtro === "sem_leitura"
      ? [{ valor: "sem_leitura" as const, rotulo: "Sem leitura" }]
      : []),
  ];

  return (
    <>
      <div className={estilos.fundoDoHistorico} onClick={aoFechar} aria-hidden />
      <div
        className={`${estilos.historico} ${estilos.painelDocumentos}`}
        role="dialog"
        aria-label="Documentos do caso"
        onKeyDown={(evento) => {
          if (evento.key === "Escape") {
            evento.stopPropagation();
            aoFechar();
          }
        }}
      >
        <div className={estilos.historicoTopo}>
          <strong>Documentos do caso</strong>
          <button type="button" className={estilos.novaNoHistorico} onClick={aoFechar}>
            Fechar
          </button>
        </div>

        <div className={estilos.filtrosDocs} role="group" aria-label="Mostrar">
          {filtros.map((f) => (
            <button
              key={f.valor}
              type="button"
              className={`${estilos.filtroDoc} ${filtro === f.valor ? estilos.filtroAtivo : ""}`}
              aria-pressed={filtro === f.valor}
              onClick={() => setFiltro(f.valor)}
            >
              {f.rotulo} ({totais[f.valor]})
            </button>
          ))}
        </div>

        <input
          ref={campoBusca}
          type="search"
          className={estilos.buscaDocs}
          placeholder="Procurar pelo nome ou tipo (ex.: CTPS, RG)"
          value={busca}
          onChange={(evento) => setBusca(evento.target.value)}
          aria-label="Procurar documento"
        />

        {visiveis.length === 0 ? (
          <p className={estilos.vazio}>
            {documentos.length === 0
              ? "Este caso ainda não tem documentos enviados."
              : "Nenhum documento com esse nome ou tipo."}
          </p>
        ) : (
          <ul className={estilos.listaDeConversas}>
            {visiveis.map((d) => (
              <li key={d.id} className={estilos.itemDaConversa}>
                <button
                  type="button"
                  className={estilos.itemCorpo}
                  onClick={() => aoAbrir(d, visiveis)}
                  title={`Abrir ${d.arquivo}`}
                >
                  <span className={estilos.itemTitulo}>{d.tipo || d.arquivo}</span>
                  {d.tipo && <span className={`${estilos.itemMeta} ${estilos.nomeDoArquivo}`}>{d.arquivo}</span>}
                  {!lido(d) && (
                    <span className={estilos.seloLeitura}>{SEM_LEITURA[d.situacao] ?? "Ainda não lido"}</span>
                  )}
                </button>
                <button
                  type="button"
                  className={estilos.perguntarDoc}
                  onClick={() => aoPerguntar(d)}
                  title="Escrever uma pergunta sobre este documento"
                >
                  Perguntar
                </button>
              </li>
            ))}
          </ul>
        )}

        <p className={estilos.dicaDocs}>
          Clique no documento para abrir. No visor, as setas ← → passam para o próximo.
        </p>
      </div>
    </>
  );
}
