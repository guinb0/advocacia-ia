import { semUnderscore } from "@/lib/formato";
import type { QualidadeImagem } from "@/lib/types";
import { Barra, Selo, Tabela, Td, Th, TrZebra } from "@/components/ui/Basicos";

export default function PainelQualidade({ qualidade }: { qualidade: QualidadeImagem }) {
  return (
    <Tabela>
      <thead>
        <tr>
          <Th>Métrica</Th>
          <Th>Medição</Th>
          <Th style={{ width: 130 }}>Score</Th>
          <Th>Situação</Th>
        </tr>
      </thead>
      <tbody>
        {qualidade.metricas.map((m) => (
          <TrZebra key={m.nome}>
            <Td>
              <strong>{semUnderscore(m.nome)}</strong>
            </Td>
            {/* Cor de destino era --tinta-3 (dimmed), mas `.tabela td` tinha
             * especificidade maior que `.observacao` sozinha e sempre ganhava
             * com --tinta-2 — bug pré-existente. Mantido igual (paridade
             * visual), sem corrigir em silêncio. */}
            <Td className="text-xs leading-[1.5]">{m.mensagem}</Td>
            <Td>
              <span className="font-codigo tabular-nums text-sm text-tinta">{m.score}%</span>
              <Barra score={m.score} />
            </Td>
            <Td>
              {m.ok ? (
                <Selo tom="ok" simbolo="✓">
                  boa
                </Selo>
              ) : (
                <Selo tom="critico" simbolo="✕">
                  ruim
                </Selo>
              )}
            </Td>
          </TrZebra>
        ))}
      </tbody>
    </Tabela>
  );
}
