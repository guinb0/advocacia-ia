"use client";

/**
 * Prévia leve de um arquivo, para mostrar ao lado de outro trabalho (a petição, a
 * conferência do protocolo). O `VisorEntrega` é a tela completa, com leitura do OCR
 * e navegação; aqui é só o documento, ocupando a altura que o recipiente der.
 */

import { useEffect, useState, type ReactNode } from "react";

import { RespostaFormatada } from "@/components/ui/Markdown";
import { baixarArquivoEntregaPdf } from "@/lib/api";
import { useArquivoEntrega } from "@/lib/useArquivo";

type TipoDeArquivo = "pdf" | "imagem" | "texto" | "markdown" | "audio" | "video" | "docx" | "outro";

const EXTENSOES: [TipoDeArquivo, RegExp][] = [
  ["pdf", /\.pdf$/i],
  ["imagem", /\.(jpe?g|png|gif|bmp|webp|tiff?|avif)$/i],
  ["texto", /\.txt$/i],
  ["markdown", /\.(md|markdown)$/i],
  ["audio", /\.(mp3|wav|ogg|oga|opus|m4a|aac|flac|weba)$/i],
  ["video", /\.(mp4|webm|mov|m4v|ogv)$/i],
  ["docx", /\.docx$/i],
];

export function tipoDoArquivo(nome: string): TipoDeArquivo {
  return EXTENSOES.find(([, padrao]) => padrao.test(nome))?.[0] ?? "outro";
}

const ROTULOS: Record<TipoDeArquivo, string> = {
  pdf: "PDF",
  imagem: "Imagem",
  texto: "Texto",
  markdown: "Texto",
  audio: "Áudio",
  video: "Vídeo",
  docx: "Word",
  outro: "Arquivo",
};

export function rotuloDoTipo(nome: string): string {
  const tipo = tipoDoArquivo(nome);
  if (tipo !== "outro") return ROTULOS[tipo];
  const ext = nome.includes(".") ? nome.slice(nome.lastIndexOf(".") + 1).toUpperCase() : "";
  return ext ? `Arquivo .${ext.toLowerCase()}` : "Arquivo";
}

const MOLDURA = "h-full w-full rounded-campo bg-papel";

function Mensagem({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center p-6">
      <p className="m-0 max-w-sm text-center text-sm leading-relaxed text-tinta-3">{children}</p>
    </div>
  );
}

type Props = {
  /** Object URL do arquivo; `null` enquanto carrega. */
  url: string | null;
  /** Nome do arquivo — é a extensão que decide como mostrar. */
  arquivo: string;
  erro?: string | null;
  /** O que dizer quando o formato não abre no navegador. */
  semPrevia?: string;
};

export default function PreviaArquivo({ url, arquivo, erro, semPrevia }: Props) {
  const tipo = tipoDoArquivo(arquivo);
  const [texto, setTexto] = useState<string | null>(null);

  useEffect(() => {
    setTexto(null);
    if (!url || (tipo !== "texto" && tipo !== "markdown")) return;
    let cancelado = false;
    fetch(url)
      .then((r) => r.text())
      .then((conteudo) => {
        if (!cancelado) setTexto(conteudo);
      })
      .catch(() => {
        if (!cancelado) setTexto("Não foi possível exibir o conteúdo deste arquivo de texto.");
      });
    return () => {
      cancelado = true;
    };
  }, [url, tipo]);

  if (erro) return <Mensagem>{erro}</Mensagem>;
  if (!url) return <Mensagem>Abrindo o documento…</Mensagem>;

  switch (tipo) {
    case "pdf":
      return <iframe className={`${MOLDURA} border-none`} src={url} title={`Documento ${arquivo}`} />;
    case "imagem":
      return (
        <div className="flex h-full w-full items-start justify-center overflow-auto">
          {/* eslint-disable-next-line @next/next/no-img-element -- object URL de blob, que o otimizador do Next não processa. */}
          <img className="block max-w-full rounded-campo object-contain" src={url} alt={`Documento ${arquivo}`} />
        </div>
      );
    case "texto":
      return (
        <pre className={`${MOLDURA} m-0 overflow-auto whitespace-pre-wrap break-words p-4 font-codigo text-sm text-tinta`}>
          {texto ?? "Carregando o texto…"}
        </pre>
      );
    case "markdown":
      return (
        <div className={`${MOLDURA} overflow-auto px-6 py-5`}>
          {texto == null ? <p className="m-0 text-sm text-tinta-3">Carregando o texto…</p> : <RespostaFormatada texto={texto} />}
        </div>
      );
    case "audio":
      return (
        <div className="flex h-full w-full items-start justify-center p-4">
          <audio className="w-full" src={url} controls preload="metadata">
            Este navegador não toca áudio.
          </audio>
        </div>
      );
    case "video":
      return (
        <div className="flex h-full w-full items-start justify-center">
          <video className="block max-h-full max-w-full rounded-campo bg-black" src={url} controls preload="metadata">
            Este navegador não toca vídeo.
          </video>
        </div>
      );
    default:
      return (
        <Mensagem>
          {semPrevia ?? "Este formato não abre no navegador. O arquivo está preservado; baixe-o para abrir no programa certo."}
        </Mensagem>
      );
  }
}

/** Prévia de um arquivo já enviado ao caso. Word aparece convertido em PDF pelo servidor. */
export function PreviaDeEntrega({ entregaId, arquivo }: { entregaId: string; arquivo: string }) {
  const ehWord = tipoDoArquivo(arquivo) === "docx";
  const { url, erro } = useArquivoEntrega(ehWord ? null : entregaId);
  const [pdfDoWord, setPdfDoWord] = useState<string | null>(null);
  const [erroWord, setErroWord] = useState<string | null>(null);

  useEffect(() => {
    setPdfDoWord(null);
    setErroWord(null);
    if (!ehWord) return;
    let cancelado = false;
    let criada: string | null = null;
    baixarArquivoEntregaPdf(entregaId)
      .then(({ arquivo: blob }) => {
        if (cancelado) return;
        criada = URL.createObjectURL(blob);
        setPdfDoWord(criada);
      })
      .catch((e: unknown) => {
        if (!cancelado) setErroWord(e instanceof Error ? e.message : "Não foi possível exibir este documento Word.");
      });
    return () => {
      cancelado = true;
      if (criada) URL.revokeObjectURL(criada);
    };
  }, [entregaId, ehWord]);

  if (ehWord) return <PreviaArquivo url={pdfDoWord} arquivo="documento.pdf" erro={erroWord} />;
  return <PreviaArquivo url={url} arquivo={arquivo} erro={erro} />;
}

/** Prévia de um arquivo que ainda está só no computador de quem usa (não foi enviado). */
export function PreviaDeArquivoLocal({ arquivo }: { arquivo: File }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    const criada = URL.createObjectURL(arquivo);
    setUrl(criada);
    return () => URL.revokeObjectURL(criada);
  }, [arquivo]);

  return (
    <PreviaArquivo
      url={url}
      arquivo={arquivo.name}
      semPrevia={
        tipoDoArquivo(arquivo.name) === "docx"
          ? "Documento Word não abre no navegador antes de ser enviado. Ele vai convertido para PDF dentro do .zip."
          : undefined
      }
    />
  );
}
