import type { LinhaTexto } from "@/lib/types";
import ui from "./ui.module.css";

export default function PainelTexto({ linhas }: { linhas: LinhaTexto[] }) {
  if (linhas.length === 0) {
    return <div className={ui.vazio}>O OCR não detectou nenhum bloco de texto nesta imagem.</div>;
  }

  return (
    <div className={ui.linhas}>
      {linhas.map((linha, i) => (
        <div key={i} className={ui.linha}>
          <span className={ui.linhaConfianca}>{Math.round(linha.confianca * 100)}%</span>
          <span>{linha.texto}</span>
        </div>
      ))}
    </div>
  );
}
