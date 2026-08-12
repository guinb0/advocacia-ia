import type { ReactNode } from "react";

import { corDoScore, leituraDoScore, SELO_TOM, type TomSelo } from "@/lib/formato";
import ui from "./ui.module.css";

/* Estes são os componentes que garantem que estado nunca chegue à tela como
 * "um texto colorido". Cada um deles emite símbolo + palavra, e a cor entra
 * como reforço — a ordem inversa da que existia antes. */

export function Barra({ score }: { score: number }) {
  const leitura = leituraDoScore(score);

  return (
    <div className={ui.barra} title={`${score}% — ${leitura.texto}`}>
      <i
        className={ui.barraPreenchimento}
        style={{ width: `${Math.max(0, Math.min(100, score))}%`, background: corDoScore(score) }}
      />
    </div>
  );
}

export function Stat({
  chave,
  valor,
  score,
  titulo,
}: {
  chave: string;
  valor: string;
  /** Quando informado, desenha a barrinha colorida abaixo do número. */
  score?: number | null;
  titulo?: string;
}) {
  const temScore = score !== null && score !== undefined;

  return (
    <div className={ui.stat} title={titulo}>
      <div className={ui.statChave}>{chave}</div>
      <div className={ui.statValor}>{valor}</div>
      {temScore && (
        <>
          <Barra score={score} />
          {/* A barra é decoração; a leitura em palavra é o que sobra para quem
              usa leitor de tela ou não distingue as cores. */}
          <div className={ui.observacao}>{leituraDoScore(score).texto}</div>
        </>
      )}
    </div>
  );
}

/** Selo de estado: pílula com símbolo + palavra. */
export function Selo({
  tom,
  simbolo,
  children,
}: {
  tom: TomSelo;
  /** Símbolo antes da palavra. Omitir só quando o texto já for um número. */
  simbolo?: string;
  children: ReactNode;
}) {
  return (
    <span className={`selo ${SELO_TOM[tom]}`}>
      {simbolo && <span aria-hidden>{simbolo}</span>}
      {children}
    </span>
  );
}

/** Faixa de mensagem com símbolo. Usada para erro, ressalva e confirmação. */
export function Aviso({
  tom,
  titulo,
  children,
}: {
  tom: TomSelo;
  titulo?: string;
  children?: ReactNode;
}) {
  const simbolo = { ok: "✓", atencao: "!", critico: "✕", info: "i", neutro: "•" }[tom];
  const classe = { ok: "ok", atencao: "atencao", critico: "critico", info: "info", neutro: "info" }[
    tom
  ];

  return (
    <div className={`aviso aviso--${classe}`} role={tom === "critico" ? "alert" : undefined}>
      <span className="avisoSimbolo" aria-hidden>
        {simbolo}
      </span>
      <div>
        {titulo && <strong>{titulo}</strong>}
        {titulo && children ? <br /> : null}
        {children}
      </div>
    </div>
  );
}

export function ListaMensagens({
  titulo,
  itens,
  tom,
}: {
  titulo: string;
  itens: string[];
  tom: "erro" | "aviso" | "sugestao";
}) {
  if (itens.length === 0) return null;

  const classes = {
    erro: ui.msgErro,
    aviso: ui.msgAviso,
    sugestao: ui.msgSugestao,
  };

  return (
    <>
      <div className={ui.secao}>
        {titulo} ({itens.length})
      </div>
      <ul className={ui.mensagens}>
        {itens.map((item, i) => (
          <li key={i} className={classes[tom]}>
            {item}
          </li>
        ))}
      </ul>
    </>
  );
}
