"""Teste sem persistência do RAG de peças no mesmo caminho usado pela minuta."""
from __future__ import annotations

from app import ambiente, peticao_local


CONTEXTO = """Caso fictício para teste: trabalhadora exposta a jornada excessiva,
sem pagamento integral de horas extras, relata adoecimento ocupacional e possui
atestado médico, controles de ponto e contracheques. Redigir somente a seção
DO DIREITO, sem inventar dados, valores ou nomes."""


def main() -> None:
    ambiente.carregar()
    referencias = peticao_local._padroes_conteudisticos_para_redigir(CONTEXTO)
    assert "[P1]" in referencias, "Nenhuma peça foi recuperada do acervo."
    resposta = peticao_local._llm_json(
        """Você é advogado trabalhista. Redija apenas dois parágrafos de uma seção
DO DIREITO para o caso fictício. Use as referências internas exclusivamente como
padrão de profundidade e estrutura; não copie fatos, nomes, valores, datas ou
citações delas. Responda JSON com a chave texto.""",
        CONTEXTO + referencias,
        timeout=180,
    )
    texto = str(resposta.get("texto") or "").strip()
    if len(texto) < 120:
        raise RuntimeError("O modelo não devolveu texto jurídico suficiente no teste.")
    print(f"Referências recuperadas: {referencias.count('[P')}")
    print("Minuta de teste gerada:")
    print(texto)


if __name__ == "__main__":
    main()
