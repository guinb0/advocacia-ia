import type { Campo } from "@/lib/types";
import { Tag } from "./Basicos";
import ui from "./ui.module.css";

export default function TabelaCampos({ campos }: { campos: Campo[] }) {
  if (campos.length === 0) {
    return (
      <div className={ui.caixaErro}>
        Nenhum campo estruturado foi extraído. Veja a aba &quot;Texto bruto&quot; para conferir o
        que o OCR conseguiu ler.
      </div>
    );
  }

  return (
    <table className={ui.tabela}>
      <thead>
        <tr>
          <th>Campo</th>
          <th>Valor</th>
          <th>Confiança</th>
          <th>Validação</th>
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
            <td>{campo.confianca ? `${Math.round(campo.confianca * 100)}%` : "—"}</td>
            <td>
              {campo.valido === true ? (
                <Tag tom="ok">válido</Tag>
              ) : campo.valido === false ? (
                <Tag tom="err">inválido</Tag>
              ) : (
                <Tag tom="warn">não verificável</Tag>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
