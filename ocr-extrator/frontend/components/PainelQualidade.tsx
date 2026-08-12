import { semUnderscore } from "@/lib/formato";
import type { QualidadeImagem } from "@/lib/types";
import { Barra, Selo } from "./Basicos";
import ui from "./ui.module.css";

export default function PainelQualidade({ qualidade }: { qualidade: QualidadeImagem }) {
  return (
    <table className={ui.tabela}>
      <thead>
        <tr>
          <th>Métrica</th>
          <th>Medição</th>
          <th style={{ width: 130 }}>Score</th>
          <th>Situação</th>
        </tr>
      </thead>
      <tbody>
        {qualidade.metricas.map((m) => (
          <tr key={m.nome}>
            <td>
              <strong>{semUnderscore(m.nome)}</strong>
            </td>
            <td className={ui.observacao} style={{ margin: 0 }}>
              {m.mensagem}
            </td>
            <td>
              <span className={ui.valor}>{m.score}%</span>
              <Barra score={m.score} />
            </td>
            <td>
              {m.ok ? (
                <Selo tom="ok" simbolo="✓">
                  boa
                </Selo>
              ) : (
                <Selo tom="critico" simbolo="✕">
                  ruim
                </Selo>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
