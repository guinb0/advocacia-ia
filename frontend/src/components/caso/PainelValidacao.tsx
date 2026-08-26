import type { Documento } from "@/lib/types";
import { Aviso, ListaMensagens, ObservacaoTabela, Selo, Tabela, Td, TrZebra, ValorTabela } from "@/components/ui/Basicos";

/** Resposta de sim/não como selo: símbolo + palavra, nunca só a cor. */
function SimNao({ valor, tomDoNao = "critico" }: { valor?: boolean | null; tomDoNao?: "critico" | "atencao" }) {
  if (valor === null || valor === undefined) {
    return (
      <Selo tom="neutro" simbolo="–">
        não informado
      </Selo>
    );
  }

  return valor ? (
    <Selo tom="ok" simbolo="✓">
      sim
    </Selo>
  ) : (
    <Selo tom={tomDoNao} simbolo={tomDoNao === "critico" ? "✕" : "!"}>
      não
    </Selo>
  );
}

export default function PainelValidacao({ doc }: { doc: Documento }) {
  const v = doc.validacao;
  const erros = v?.erros ?? [];
  const avisos = v?.avisos ?? [];
  const sugestoes = v?.sugestoes ?? [];
  const camposEsperados = v?.campos_esperados ?? [];
  const camposFaltando = v?.campos_faltando ?? [];
  const tipoDescricao = doc.tipo?.descricao ?? "este documento";

  if (!v) {
    return (
      <Aviso tom="atencao" titulo="Conferência indisponível">
        Esta leitura foi salva sem os dados de conferência automática.
      </Aviso>
    );
  }

  return (
    <>
      {/* Primeira seção da tela: sem margem superior, como `.secao:first-child`. */}
      <div className="mt-0 mb-[10px] text-tinta text-sm font-bold">Situação</div>
      <Tabela>
        <tbody>
          <TrZebra>
            <Td>
              <strong>Dados utilizáveis</strong>
              <ObservacaoTabela>
                legível, nada faltando e nada reprovado no dígito verificador
              </ObservacaoTabela>
            </Td>
            <Td className="text-right">
              <SimNao valor={v.dados_utilizaveis} />
            </Td>
          </TrZebra>
          <TrZebra>
            <Td>
              <strong>Imagem legível</strong>
            </Td>
            <Td className="text-right">
              <SimNao valor={v.imagem_legivel} />
            </Td>
          </TrZebra>
          <TrZebra>
            <Td>
              <strong>Sem ressalvas de qualidade</strong>
            </Td>
            <Td className="text-right">
              <SimNao valor={v.aprovado} tomDoNao="atencao" />
            </Td>
          </TrZebra>
        </tbody>
      </Tabela>

      <ListaMensagens titulo="Erros" itens={erros} tom="erro" />
      <ListaMensagens titulo="Avisos" itens={avisos} tom="aviso" />
      <ListaMensagens titulo="Sugestões ao usuário" itens={sugestoes} tom="sugestao" />

      {camposEsperados.length > 0 && (
        <>
          <div className="mt-[22px] mb-[10px] text-tinta text-sm font-bold">
            Campos esperados para {tipoDescricao}
          </div>
          <Tabela>
            <tbody>
              {camposEsperados.map((campo) => {
                const extraido = !camposFaltando.includes(campo);
                return (
                  <TrZebra key={campo}>
                    <ValorTabela>{campo}</ValorTabela>
                    <Td className="text-right">
                      {extraido ? (
                        <Selo tom="ok" simbolo="✓">
                          extraído
                        </Selo>
                      ) : (
                        <Selo tom="critico" simbolo="✕">
                          faltando
                        </Selo>
                      )}
                    </Td>
                  </TrZebra>
                );
              })}
            </tbody>
          </Tabela>
        </>
      )}
    </>
  );
}
