import type { LinhaTexto } from "@/lib/types";
import { Vazio } from "@/components/ui/Basicos";

export default function PainelTexto({ linhas }: { linhas: LinhaTexto[] }) {
  if (linhas.length === 0) {
    return <Vazio>O OCR não detectou nenhum bloco de texto nesta imagem.</Vazio>;
  }

  return (
    <div className="border border-borda rounded-campo font-codigo text-[0.8125rem] max-h-[520px] overflow-auto">
      {linhas.map((linha, i) => (
        <div
          key={i}
          className="flex gap-3 px-[11px] py-[7px] border-b border-borda last:border-b-0 text-tinta-2"
        >
          <span className="[flex:0_0_46px] text-tinta-3 tabular-nums text-right">
            {Math.round(linha.confianca * 100)}%
          </span>
          <span>{linha.texto}</span>
        </div>
      ))}
    </div>
  );
}
