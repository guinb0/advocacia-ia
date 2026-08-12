import type { Campo } from "@/lib/types";
import { Aviso, Selo } from "./Basicos";
import ui from "./ui.module.css";

export default function TabelaCampos({ campos }: { campos: Campo[] }) {
  if (campos.length === 0) {
    return (
      <Aviso tom="atencao" titulo="Nenhum campo foi identificado">
        A leitura não encontrou dados estruturados neste documento. Abra a aba &quot;Texto
        bruto&quot; para ver o que o OCR conseguiu ler.
      </Aviso>
    );
  }

  return (
    <table className={ui.tabela}>
      <thead>
        <tr>
          <th>Campo</th>
          <th>Valor lido</th>
          <th>Confiança</th>
          <th>Conferência</th>
        </tr>
      </thead>
      <tbody>
        {campos.map((campo) => (
          <tr key={campo.nome}>
            <td>
              <strong>{campo.rotulo}</strong>
              <div className={ui.observacao}>{campo.nome}</div>
            </td>
            <td className={ui.valor}>
              {campo.valor}
              {campo.observacao && <div className={ui.observacao}>{campo.observacao}</div>}
            </td>
            {/* Confiança 0 significa "não medida" (campo veio de regex, não de uma caixa do OCR). */}
            <td className={ui.valor}>
              {campo.confianca ? `${Math.round(campo.confianca * 100)}%` : "—"}
            </td>
            <td>
              {campo.valido === true ? (
                <Selo tom="ok" simbolo="✓">
                  válido
                </Selo>
              ) : campo.valido === false ? (
                <Selo tom="critico" simbolo="✕">
                  inválido
                </Selo>
              ) : (
                <Selo tom="neutro" simbolo="–">
                  não verificável
                </Selo>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
