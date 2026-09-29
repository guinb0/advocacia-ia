import type { Campo } from "@/lib/types";
import { Aviso, ObservacaoTabela, Selo, Tabela, Td, Th, TrZebra, ValorTabela } from "@/components/ui/Basicos";

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
    <Tabela>
      <thead>
        <tr>
          <Th>Campo</Th>
          <Th>Valor lido</Th>
          <Th>Confiança</Th>
          <Th>Conferência</Th>
        </tr>
      </thead>
      <tbody>
        {campos.map((campo) => (
          <TrZebra key={campo.nome}>
            <Td>
              <strong>{campo.rotulo}</strong>
              <ObservacaoTabela>{campo.nome}</ObservacaoTabela>
            </Td>
            <ValorTabela>
              {campo.valor}
              {campo.observacao && <ObservacaoTabela>{campo.observacao}</ObservacaoTabela>}
            </ValorTabela>
            {/* Confiança 0 significa "não medida" (campo veio de regex, não de uma caixa do OCR). */}
            <ValorTabela>
              {typeof campo.confianca === "number" && campo.confianca > 0
                ? `${Math.round(campo.confianca * 100)}%`
                : "—"}
            </ValorTabela>
            <Td>
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
            </Td>
          </TrZebra>
        ))}
      </tbody>
    </Tabela>
  );
}
