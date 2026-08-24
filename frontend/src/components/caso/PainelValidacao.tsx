import type { Documento } from "@/lib/types";
import { ListaMensagens, ObservacaoTabela, Selo, Tabela, Td, TrZebra, ValorTabela } from "@/components/ui/Basicos";

/** Resposta de sim/não como selo: símbolo + palavra, nunca só a cor. */
function SimNao({ valor, tomDoNao = "critico" }: { valor: boolean; tomDoNao?: "critico" | "atencao" }) {
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

      <ListaMensagens titulo="Erros" itens={v.erros} tom="erro" />
      <ListaMensagens titulo="Avisos" itens={v.avisos} tom="aviso" />
      <ListaMensagens titulo="Sugestões ao usuário" itens={v.sugestoes} tom="sugestao" />

      {v.campos_esperados.length > 0 && (
        <>
          <div className="mt-[22px] mb-[10px] text-tinta text-sm font-bold">
            Campos esperados para {doc.tipo.descricao}
          </div>
          <Tabela>
            <tbody>
              {v.campos_esperados.map((campo) => {
                const extraido = !v.campos_faltando.includes(campo);
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
