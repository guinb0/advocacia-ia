import { semUnderscore } from "@/lib/formato";
import type { QualidadeImagem } from "@/lib/types";
import { Barra, Tag } from "./Basicos";
import ui from "./ui.module.css";

export default function PainelQualidade({ qualidade }: { qualidade: QualidadeImagem }) {
  return (
    <table className={ui.tabela}>
      <thead>
        <tr>
          <th>Métrica</th>
          <th>Medição</th>
          <th style={{ width: 130 }}>Score</th>
          <th>Status</th>
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
              {m.score}%
              <Barra score={m.score} />
            </td>
            <td>
              <Tag tom={m.ok ? "ok" : "err"}>{m.ok ? "ok" : "ruim"}</Tag>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
