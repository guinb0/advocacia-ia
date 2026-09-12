"""A regra de duplicidade (`app/duplicidade.py`), sem banco.

    .venv\\Scripts\\python.exe -m pytest tests/test_duplicidade.py -q
"""

from __future__ import annotations

from app import duplicidade as d
from app import tipos_documento
from app.categorias import ACIDENTE_TRABALHO_GERAL

CONHECIDOS = set(tipos_documento.SEMENTE_POR_CODIGO)

LAUDO = (
    "Laudo médico. Paciente atendido em consulta ortopédica apresenta lombalgia crônica "
    "com irradiação para o membro inferior esquerdo, iniciada após esforço repetitivo no "
    "posto de trabalho, com limitação funcional para carregar peso e permanecer em pé por "
    "longos períodos. Ressonância magnética evidencia protrusão discal em L4 L5. CID M51.1. "
    "Recomendo afastamento das atividades laborais por noventa dias e acompanhamento com "
    "fisioterapia motora três vezes por semana, com reavaliação ao final do período."
)


def _contracheque(mes: str, bruto: str, inss: str, liquido: str, horas: str) -> str:
    return (
        f"Demonstrativo de pagamento de salário. Empresa Transportes Rápidos Ltda. "
        f"Competência {mes}. Funcionário João da Silva, cargo motorista, matrícula 4471. "
        f"Salário base {bruto}. Horas extras {horas}. Adicional noturno 0,00. "
        f"Desconto INSS {inss}. Vale transporte 132,00. Total de vencimentos {bruto}. "
        f"Total de descontos {inss}. Valor líquido a receber {liquido}. "
        "Base de cálculo do FGTS conforme legislação vigente. Declaro ter recebido."
    )


def _entrega(id_: str, **dados) -> dict:
    base = {
        "id": id_,
        "arquivo": f"{id_}.pdf",
        "conteudo_sha256": None,
        "tipo_detectado": None,
        "itens_atendidos": [],
        "roteamento_origem": None,
        "extracao": {},
        "criado_em": "2026-09-10T10:00:00+00:00",
    }
    base.update(dados)
    return base


def _comparar(nova: dict, existente: dict):
    return d.comparar(nova, existente, ACIDENTE_TRABALHO_GERAL, CONHECIDOS)


def _cpf(valor: str, valido: bool = True) -> dict:
    return {"campos": [{"nome": "cpf", "valor": valor, "valido": valido}]}


def test_mesmos_bytes_e_identico_mesmo_com_nome_e_tipo_diferentes():
    achado = _comparar(
        _entrega("nova", conteudo_sha256="ABC123", tipo_detectado="rg"),
        _entrega("velha", conteudo_sha256="abc123", tipo_detectado="cpf"),
    )
    assert achado is not None and achado.regra == d.IDENTICO


def test_segunda_foto_do_mesmo_cpf_e_mesmo_numero():
    achado = _comparar(
        _entrega("nova", tipo_detectado="cpf", extracao=_cpf("529.982.247-25")),
        _entrega("velha", tipo_detectado="cpf", extracao=_cpf("52998224725")),
    )
    assert achado is not None and achado.regra == d.MESMO_NUMERO
    assert "CPF" in achado.explicacao


def test_numero_invalido_nao_serve_de_prova():
    assert (
        _comparar(
            _entrega("nova", tipo_detectado="cpf", extracao=_cpf("529.982.247-25", False)),
            _entrega("velha", tipo_detectado="cpf", extracao=_cpf("529.982.247-25")),
        )
        is None
    )


def test_rg_e_cnh_da_mesma_pessoa_nao_sao_o_mesmo_documento():
    rg = {"campos": [{"nome": "rg", "valor": "12.345.678-9", "valido": True}]}
    assert (
        _comparar(
            _entrega("cnh", tipo_detectado="cnh", extracao=rg),
            _entrega("rg", tipo_detectado="rg", extracao=rg),
        )
        is None
    )


def test_mesmo_laudo_com_diferenca_de_leitura_e_mesmo_conteudo():
    releitura = LAUDO.replace("ortopédica", "ortopedica.")  # erro típico de OCR
    achado = _comparar(
        _entrega("nova", itens_atendidos=["DOC.14"], extracao={"texto_completo": releitura}),
        _entrega("velha", itens_atendidos=["DOC.14"], extracao={"texto_completo": LAUDO}),
    )
    assert achado is not None and achado.regra == d.MESMO_CONTEUDO


def test_mesmo_texto_em_tipos_diferentes_nao_e_duplicidade():
    assert (
        _comparar(
            _entrega("atestado", itens_atendidos=["DOC.13"], extracao={"texto_completo": LAUDO}),
            _entrega("laudo", itens_atendidos=["DOC.14"], extracao={"texto_completo": LAUDO}),
        )
        is None
    )


def test_contracheques_de_meses_diferentes_nao_sao_duplicados():
    agosto = _contracheque("08/2026", "3.200,00", "288,00", "2.780,00", "212,40")
    julho = _contracheque("07/2026", "3.150,00", "283,50", "2.734,50", "180,10")
    indice = d.similaridade(agosto, julho)
    assert indice is not None and indice < d.LIMIAR_TEXTO
    assert (
        _comparar(
            _entrega("agosto", itens_atendidos=["DOC.07"], extracao={"texto_completo": agosto}),
            _entrega("julho", itens_atendidos=["DOC.07"], extracao={"texto_completo": julho}),
        )
        is None
    )


def test_texto_curto_nao_tem_o_que_comparar():
    assert d.similaridade("RG frente", "RG frente") is None


def test_tipo_da_entrega_segue_a_ordem_de_autoridade():
    categoria = ACIDENTE_TRABALHO_GERAL
    # Pedido explícito da reclassificação vence tudo.
    assert d.tipo_da_entrega(
        {"tipo_documento": "laudo_medico", "itens_atendidos": ["DOC.10"]}, categoria, CONHECIDOS
    ) == "laudo_medico"
    # Correção humana: vale o tipo gravado.
    assert d.tipo_da_entrega(
        {"roteamento_origem": "humano", "tipo_detectado": "cnh", "itens_atendidos": ["DOC.03"]},
        categoria,
        CONHECIDOS,
    ) == "cnh"
    # A CAT que o classificador leu como CTPS e o roteamento levou ao item da CAT.
    assert d.tipo_da_entrega(
        {"tipo_detectado": "ctps", "itens_atendidos": ["DOC.10"]}, categoria, CONHECIDOS
    ) == "cat"
    # Na triagem, sobra o que o classificador reconheceu.
    assert d.tipo_da_entrega({"tipo_detectado": "cpf"}, categoria, CONHECIDOS) == "cpf"
    assert d.tipo_da_entrega({"tipo_detectado": "desconhecido"}, categoria, CONHECIDOS) is None


def test_mensagem_e_erro_http():
    repetido = d.Duplicidade(
        entrega_id="e1",
        arquivo="rg.pdf",
        regra=d.IDENTICO,
        explicacao="arquivo idêntico",
        itens=("DOC.03",),
        criado_em="2026-09-10T13:22:01+00:00",
    )
    texto = d.mensagem([repetido])
    assert "já está no caso" in texto and "rg.pdf" in texto and "10/09/2026" in texto

    erro = d.DocumentoDuplicado([repetido], texto)
    assert erro.status_code == 409
    corpo = erro.corpo()
    assert corpo["codigo"] == d.CODIGO_ERRO
    assert corpo["detail"] == texto
    assert corpo["duplicidades"][0]["itens"] == ["DOC.03"]
