"""O vínculo que o documento não diz e a entrevista diz.

Caso real que motivou o módulo: chega um resumo de alta em nome de "Artur", sem
nenhuma palavra sobre quem ele é. O documento sozinho não pode afirmar parentesco —
mas na entrevista o cliente disse "meu filho Artur". Cruzar as duas coisas é o que
transforma "documento de terceiro" em "documento do filho do cliente".

Nenhum teste aqui toca a rede: `llm.chamar` entra dublado.
"""

from __future__ import annotations

import pytest

from app import vinculos


@pytest.fixture(autouse=True)
def _cache_limpo():
    """O cache de vínculos é global do processo e sobrevive entre testes.

    Sem isto, um teste que resolve "Artur" no `caso-1` faz o teste seguinte, que
    dubla o modelo de outro jeito no MESMO caso, receber a resposta cacheada e
    passar (ou falhar) pelo motivo errado.
    """
    vinculos.limpar_cache()
    yield
    vinculos.limpar_cache()


ENTREVISTA = (
    "ADVOGADO: Conte o que aconteceu. "
    "CLIENTE: Meu filho Artur Nunes se acidentou na fábrica em maio. "
    "Ele estava operando a prensa quando prendeu a mão. "
    "Meu chefe na época era o Ronaldo Prado, que não quis emitir a CAT."
)


def _dublar_llm(monkeypatch, resposta):
    def falso(instrucao, mensagem, **kwargs):
        return resposta

    monkeypatch.setattr(vinculos.llm, "chamar", falso)


def _sem_entrevista(monkeypatch, texto=ENTREVISTA):
    monkeypatch.setattr(vinculos, "texto_das_entrevistas", lambda caso_id: texto)


def test_vinculo_dito_na_entrevista_resolve_o_nome_do_documento(monkeypatch):
    _sem_entrevista(monkeypatch)
    _dublar_llm(monkeypatch, {"vinculos": [
        {"nome": "Artur Nunes", "relacao": "filho",
         "citacao": "Meu filho Artur Nunes se acidentou na fábrica em maio."},
    ]})

    achados = vinculos.resolver_por_entrevista("caso-1", "Maria Nunes", ["Artur Nunes"])

    assert achados[vinculos._dobrar("Artur Nunes")]["relacao"] == "filho"
    assert achados[vinculos._dobrar("Artur Nunes")]["relacao_origem"] == "entrevista"


def test_vinculo_com_citacao_inventada_e_descartado(monkeypatch):
    """Mesma trava do OCR: sem a frase literal na entrevista, o vínculo não sai daqui."""
    _sem_entrevista(monkeypatch)
    _dublar_llm(monkeypatch, {"vinculos": [
        {"nome": "Artur Nunes", "relacao": "filho",
         "citacao": "O cliente afirmou que Artur é seu filho primogênito."},
    ]})

    assert vinculos.resolver_por_entrevista("caso-1", "Maria Nunes", ["Artur Nunes"]) == {}


def test_modelo_nao_contrabandeia_nome_que_ninguem_pediu(monkeypatch):
    _sem_entrevista(monkeypatch)
    _dublar_llm(monkeypatch, {"vinculos": [
        {"nome": "Ronaldo Prado", "relacao": "chefe",
         "citacao": "Meu chefe na época era o Ronaldo Prado"},
    ]})

    achados = vinculos.resolver_por_entrevista("caso-1", "Maria Nunes", ["Artur Nunes"])
    assert achados == {}


def test_sem_entrevista_nao_chama_o_modelo(monkeypatch):
    """Caso sem entrevista não gasta chamada paga — sai antes de tocar a rede."""
    _sem_entrevista(monkeypatch, texto="")

    def explode(*args, **kwargs):
        raise AssertionError("não deveria chamar o modelo sem entrevista")

    monkeypatch.setattr(vinculos.llm, "chamar", explode)
    assert vinculos.resolver_por_entrevista("caso-1", "Maria Nunes", ["Artur"]) == {}


def test_falha_do_modelo_nao_derruba_a_analise(monkeypatch):
    """Vínculo é enriquecimento: modelo fora do ar não pode reprovar documento."""
    _sem_entrevista(monkeypatch)

    def falha(*args, **kwargs):
        raise vinculos.llm.ErroLLM("sem chave configurada")

    monkeypatch.setattr(vinculos.llm, "chamar", falha)
    assert vinculos.resolver_por_entrevista("caso-1", "Maria Nunes", ["Artur"]) == {}


def test_documento_vence_entrevista_e_origem_fica_registrada():
    """O que o arquivo declara não é sobrescrito pelo que alguém contou."""
    validacao = {
        "partes": [
            {"nome": "Artur Nunes", "papel": "paciente", "relacao_com_cliente": ""},
            {"nome": "Joana Lima", "papel": "declarante", "relacao_com_cliente": "esposa"},
        ],
        "pessoa_principal": {"nome": "Artur Nunes", "papel": "paciente", "relacao_com_cliente": ""},
    }
    achados = {
        vinculos._dobrar("Artur Nunes"): {
            "relacao": "filho", "citacao": "meu filho Artur", "relacao_origem": "entrevista",
        },
        vinculos._dobrar("Joana Lima"): {
            "relacao": "irmã", "citacao": "minha irmã Joana", "relacao_origem": "entrevista",
        },
    }

    saida = vinculos.aplicar(validacao, achados)

    artur, joana = saida["partes"]
    assert (artur["relacao_com_cliente"], artur["relacao_origem"]) == ("filho", "entrevista")
    # O documento disse "esposa"; a entrevista dizia "irmã" e NÃO pode vencer.
    assert (joana["relacao_com_cliente"], joana["relacao_origem"]) == ("esposa", "documento")
    assert saida["pessoa_principal"]["relacao_com_cliente"] == "filho"
    assert saida["pessoa_principal"]["relacao_citacao"] == "meu filho Artur"


def test_acento_e_caixa_nao_impedem_o_encontro(monkeypatch):
    _sem_entrevista(monkeypatch, texto="CLIENTE: o Antônio é meu genro.")
    _dublar_llm(monkeypatch, {"vinculos": [
        {"nome": "ANTONIO SOUZA", "relacao": "genro", "citacao": "o Antonio e meu genro"},
    ]})

    achados = vinculos.resolver_por_entrevista("c1", "Maria", ["Antônio Souza"])
    assert achados[vinculos._dobrar("antonio souza")]["relacao"] == "genro"


def test_lote_do_mesmo_caso_gasta_uma_chamada_so(monkeypatch):
    """Vinte documentos do mesmo caso não podem virar vinte chamadas pagas.

    O gatilho é a pasta que o advogado joga de uma vez na Carteira: todos os
    arquivos são do mesmo caso e perguntam sobre a mesma entrevista. Sem cache,
    cada documento repetiria a pergunta inteira.
    """
    vinculos.limpar_cache()
    _sem_entrevista(monkeypatch)
    chamadas = []

    def contando(instrucao, mensagem, **kwargs):
        chamadas.append(mensagem)
        return {"vinculos": [
            {"nome": "Artur Nunes", "relacao": "filho",
             "citacao": "Meu filho Artur Nunes se acidentou na fábrica em maio."},
        ]}

    monkeypatch.setattr(vinculos.llm, "chamar", contando)

    for _ in range(20):
        achados = vinculos.resolver_por_entrevista("caso-lote", "Maria Nunes", ["Artur Nunes"])
        assert achados[vinculos._dobrar("Artur Nunes")]["relacao"] == "filho"

    assert len(chamadas) == 1


def test_nome_novo_no_lote_dispara_nova_pergunta(monkeypatch):
    """Cache não pode esconder nome que ainda não foi perguntado."""
    vinculos.limpar_cache()
    _sem_entrevista(monkeypatch)
    chamadas = []

    def contando(instrucao, mensagem, **kwargs):
        chamadas.append(mensagem)
        return {"vinculos": []}

    monkeypatch.setattr(vinculos.llm, "chamar", contando)

    vinculos.resolver_por_entrevista("caso-2", "Maria", ["Artur Nunes"])
    vinculos.resolver_por_entrevista("caso-2", "Maria", ["Artur Nunes"])  # cacheado
    vinculos.resolver_por_entrevista("caso-2", "Maria", ["Ronaldo Prado"])  # novo

    assert len(chamadas) == 2


def test_nome_sem_vinculo_na_entrevista_nao_e_perguntado_de_novo(monkeypatch):
    """"A entrevista não diz" também é resposta, e fica guardada."""
    vinculos.limpar_cache()
    _sem_entrevista(monkeypatch)
    chamadas = []

    def contando(instrucao, mensagem, **kwargs):
        chamadas.append(mensagem)
        return {"vinculos": []}

    monkeypatch.setattr(vinculos.llm, "chamar", contando)

    assert vinculos.resolver_por_entrevista("caso-3", "Maria", ["Fulano"]) == {}
    assert vinculos.resolver_por_entrevista("caso-3", "Maria", ["Fulano"]) == {}
    assert len(chamadas) == 1


def test_cache_e_por_caso_e_nao_vaza_entre_casos(monkeypatch):
    """Vínculo de um cliente não pode aparecer no caso de outro."""
    vinculos.limpar_cache()
    _sem_entrevista(monkeypatch)
    _dublar_llm(monkeypatch, {"vinculos": [
        {"nome": "Artur Nunes", "relacao": "filho",
         "citacao": "Meu filho Artur Nunes se acidentou na fábrica em maio."},
    ]})

    vinculos.resolver_por_entrevista("caso-A", "Maria Nunes", ["Artur Nunes"])

    chamou = []
    def registrando(instrucao, mensagem, **kwargs):
        chamou.append(1)
        return {"vinculos": []}

    monkeypatch.setattr(vinculos.llm, "chamar", registrando)
    assert vinculos.resolver_por_entrevista("caso-B", "Outro Cliente", ["Artur Nunes"]) == {}
    assert chamou == [1]
