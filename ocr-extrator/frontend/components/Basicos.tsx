import type { ReactNode } from "react";

import { corDoScore } from "@/lib/formato";
import ui from "./ui.module.css";

export function Barra({ score }: { score: number }) {
  return (
    <div className={ui.barra}>
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
  return (
    <div className={ui.stat} title={titulo}>
      <div className={ui.statChave}>{chave}</div>
      <div className={ui.statValor}>{valor}</div>
      {score !== null && score !== undefined && <Barra score={score} />}
    </div>
  );
}

type Tom = "ok" | "err" | "warn";

export function Tag({ tom, children }: { tom: Tom; children: ReactNode }) {
  const classes = { ok: ui.tagOk, err: ui.tagErr, warn: ui.tagWarn };
  return <span className={`${ui.tag} ${classes[tom]}`}>{children}</span>;
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
