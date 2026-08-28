"""Ponte com o agente jurídico: vínculo, envio de documento, conferência e dossiê.

Sem rede e sem o agente no ar — o cliente HTTP é substituído por um dublê. O que se
prova aqui é o que a ponte promete:

    .venv\\Scripts\\python.exe -m tests.test_agente
"""

import os
import sys
import tempfile
from pathlib import Path

# A ponte só se considera ligada com endereço configurado; sem isto o dossiê
# responderia "agente não configurado" e metade dos testes não exercitaria nada.
os.environ.setdefault("AGENTE_API_URL", "http://agente-de-teste.invalido")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import armazenamento  # noqa: E402

# Redireciona o banco ANTES de qualquer uso, como nos demais testes.
_TEMP = Path(tempfile.mkdtemp(prefix="ocr-agente-"))
armazenamento.DIR_DADOS = _TEMP
armazenamento.DIR_ARQUIVOS = _TEMP / "casos"
armazenamento.DIR_CONTRATOS = _TEMP / "contratos"
armazenamento.CAMINHO_BANCO = _TEMP / "casos.db"

from app.agente import dossie, espelho  # noqa: E402
from app.agente.cliente import AgenteIndisponivel, Cliente, ErroDoAgente, caso_ref_valido  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


class ClienteFalso:
    """Dublê do agente. Registra o que recebeu e devolve o que for programado."""

    enviados: list[tuple[str, str]] = []
    declarados: list[tuple[str, str, str]] = []
    casos_criados: int = 0
    fatos_devolvidos: list[dict] = []
    erro: Exception | None = None
    casos_apagados: set[str] = set()
    """Casos que o agente diz não conhecer — como um banco recriado do zero."""
    casos_invisiveis: set[str] = set()
    """Casos criados mas ainda não visíveis na leitura — réplica ou pooler atrasado."""

    def __init__(self, *_args, **_kwargs) -> None:
        if ClienteFalso.erro is not None:
            raise ClienteFalso.erro

    def caso_existe(self, caso_ref):
        if not caso_ref_valido(caso_ref):
            return False
        if caso_ref in ClienteFalso.casos_apagados:
            return False
        if caso_ref in ClienteFalso.casos_invisiveis:
            return False
        return True

    def caso(self, _caso_ref):
        # Quem sincroniza qualifica a parte reclamante em seguida, e para isso lê o caso.
        # Sem parte alguma, a qualificação desiste em silêncio — as seções que provam a
        # qualificação trazem o próprio dublê, com partes de verdade.
        return {"parties": []}

    def criar_cliente(self, nome, **_):
        return {"id": "client_TESTE", "full_name": nome}

    def criar_caso(self, **_kwargs):
        ClienteFalso.casos_criados += 1
        return {"id": f"case_01J0000000000000000000000{ClienteFalso.casos_criados}"}

    def enviar_extracao(self, caso_ref, *, evento_externo, origem, extracao):
        ClienteFalso.enviados.append((caso_ref, evento_externo))
        return {"document": {"id": "doc_1"}}

    def declarar_documento(self, caso_ref, *, kind, arquivo, origem):
        ClienteFalso.declarados.append((caso_ref, kind, origem))
        return {"document": {"id": "doc_declarado"}}

    def fatos(self, _caso_ref):
        return {"items": ClienteFalso.fatos_devolvidos}


def extracao_falsa(tipo: str = "ctps") -> dict:
    return {
        "tipo": {"codigo": tipo, "detectado": tipo},
        "campos": [{"nome": "nome", "valor": "MARIA", "confianca": 0.98, "valido": True}],
        "validacao": {"veredito": "APROVADO", "dados_utilizaveis": True, "score_legibilidade": 90},
    }


def fato(tipo: str, valor: dict) -> dict:
    return {"type": tipo, "value": valor, "status": "EXTRACTED", "confidence": 0.95}


def main() -> int:
    armazenamento.inicializar()
    espelho.Cliente = ClienteFalso  # type: ignore[assignment]
    dossie.Cliente = ClienteFalso  # type: ignore[assignment]

    print("1. Vínculo com o agente")
    caso = armazenamento.criar_caso("Maria Santos", "acidente_trabalho_geral")
    caso_id = caso["id"]

    vinculo = espelho.garantir_caso(caso_id)
    checar(
        vinculo["caso_ref"] == "case_01J00000000000000000000001",
        "o caso é espelhado no agente",
    )

    espelho.garantir_caso(caso_id)
    checar(
        ClienteFalso.casos_criados == 1,
        "chamar de novo reaproveita o caso — não cria um segundo para o mesmo cliente",
    )

    # Visibilidade atrasada: o caso foi criado mas a leitura ainda devolve 404. Sem a
    # janela de confiança, cada `garantir_caso` recriaria outro caso — o loop do
    # `diag_pipeline` em produção.
    ClienteFalso.casos_invisiveis.add(vinculo["caso_ref"])
    reutilizado = espelho.garantir_caso(caso_id)
    checar(
        reutilizado["caso_ref"] == vinculo["caso_ref"],
        "vínculo recente não é trocado quando o agente ainda não confirma o caso",
    )
    checar(
        ClienteFalso.casos_criados == 1,
        "visibilidade atrasada não dispara recriação em loop",
    )
    ClienteFalso.casos_invisiveis.clear()

    # Vínculo órfão, num caso à parte para não mexer no que as seções seguintes usam: o
    # caso existiu e sumiu do outro lado (banco recriado, migração). Sem a conferência, o
    # vínculo continuaria apontando para o nada e o dossiê abriria vazio para sempre — foi
    # o que aconteceu na migração do agente para o SQL Server.
    orfao = armazenamento.criar_caso("Jose Orfao", "acidente_trabalho_geral")["id"]
    antes = espelho.garantir_caso(orfao)
    ClienteFalso.casos_apagados.add(antes["caso_ref"])
    depois = espelho.garantir_caso(orfao)
    checar(
        depois["caso_ref"] != antes["caso_ref"],
        "caso que sumiu do agente é recriado, e o vínculo passa a apontar para o novo",
    )
    checar(
        depois["enviados"] == [],
        "o revínculo zera as entregas enviadas — o caso novo não conhece nenhuma",
    )
    ClienteFalso.casos_apagados.clear()

    antigo = armazenamento.criar_caso("Vinculo Antigo", "acidente_trabalho_geral")["id"]
    armazenamento.vincular_agente(antigo, "123", "client_antigo")
    recriado = espelho.garantir_caso(antigo)
    checar(
        recriado["caso_ref"].startswith("case_"),
        "vínculo antigo fora do formato case_ é recriado em vez de derrubar o worker",
    )

    print("\n2. Envio da extração")
    caminho = armazenamento.DIR_ARQUIVOS / caso_id / "ctps.png"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"x")
    entrega = armazenamento.registrar_entrega_pendente(caso_id, "DOC.01", "ctps.png", caminho)

    checar(
        not espelho.enviar_entrega(caso_id, entrega["id"]),
        "entrega ainda em leitura não é enviada — não há campo para virar fato",
    )

    armazenamento.concluir_entrega(entrega["id"], extracao_falsa(), True, ["DOC.01"])
    checar(espelho.enviar_entrega(caso_id, entrega["id"]), "entrega pronta é enviada")
    entrega_db = armazenamento.obter_entrega(entrega["id"])
    chave = espelho._chave_envio(entrega["id"], entrega_db["extracao"])
    checar(
        ClienteFalso.enviados == [("case_01J00000000000000000000001", chave)],
        "entrega_id:hash da extração vai como chave de idempotência",
    )

    espelho.enviar_entrega(caso_id, entrega["id"])
    checar(len(ClienteFalso.enviados) == 1, "o mesmo documento não é reenviado")

    caminho_cnis = armazenamento.DIR_ARQUIVOS / caso_id / "cnis.pdf"
    caminho_cnis.write_bytes(b"x")
    cnis = armazenamento.registrar_entrega_pendente(caso_id, "DOC.08", "cnis.pdf", caminho_cnis)
    armazenamento.concluir_entrega(cnis["id"], extracao_falsa("cnis"), True, ["DOC.08"])
    checar(espelho.enviar_entrega(caso_id, cnis["id"]), "CNIS é aceito como documento jurídico recebido")
    checar(
        ClienteFalso.declarados[-1][1] == "DOCUMENT.CNIS",
        "CNIS baixa o item do dossiê sem ser enviado como OCR de identificação",
    )
    checar(
        len(ClienteFalso.enviados) == 2,
        "documento jurídico entra como conhecimento genérico sem fingir tipo de identificação",
    )

    print("\n3. Agente fora do ar")
    ClienteFalso.erro = AgenteIndisponivel("O agente jurídico não respondeu.")
    caminho2 = armazenamento.DIR_ARQUIVOS / caso_id / "cpf.png"
    caminho2.write_bytes(b"x")
    entrega2 = armazenamento.registrar_entrega_pendente(caso_id, "DOC.02", "cpf.png", caminho2)
    armazenamento.concluir_entrega(entrega2["id"], extracao_falsa("cpf"), True, ["DOC.02"])

    checar(not espelho.enviar_entrega(caso_id, entrega2["id"]), "o envio falha sem estourar")
    vinculo = armazenamento.obter_vinculo_agente(caso_id)
    checar(bool(vinculo["ultimo_erro"]), "o motivo fica registrado no vínculo")
    entrega2_db = armazenamento.obter_entrega(entrega2["id"])
    chave2 = espelho._chave_envio(entrega2["id"], entrega2_db["extracao"])
    checar(
        chave2 not in vinculo["enviados"],
        "a entrega continua pendente de envio — não é dada como entregue",
    )

    montado = dossie.montar(caso_id)
    etapas = {e["codigo"]: e for e in montado["etapas"]}
    checar(
        etapas["fatos"]["estado"] == "indisponivel",
        "agente fora do ar não vira 'nenhum fato' na tela do advogado",
    )
    checar(
        etapas["documentos"]["estado"] in ("andamento", "pronto"),
        "o que é do OCR continua sendo mostrado mesmo sem o agente",
    )
    ClienteFalso.erro = None

    print("\n4. Conferência do contrato contra os documentos")
    ClienteFalso.fatos_devolvidos = [
        fato("PERSON.CPF", {"digits": "12345678900"}),
        fato("PERSON.NAME", {"full_name": "MARIA APARECIDA SANTOS"}),
        fato("PERSON.BIRTH_DATE", {"date": "1990-03-15"}),
    ]

    igual = espelho.conferir_contrato(
        caso_id,
        {
            "cpf": "123.456.789-00",
            "nome da pessoa": "Maria Aparecida Santos",
            "data de nascimento": "15/03/1990",
        },
    )
    checar(igual["divergencias"] == [], "formatação diferente não é divergência")
    checar(
        set(igual["conferidos"]) == {"cpf", "nome da pessoa", "data de nascimento"},
        "os três campos são conferidos",
    )

    divergente = espelho.conferir_contrato(caso_id, {"cpf": "999.888.777-66"})
    checar(len(divergente["divergencias"]) == 1, "CPF diferente é acusado")
    checar(
        divergente["divergencias"][0]["nos_documentos"] == "12345678900",
        "a divergência mostra o valor que veio dos documentos",
    )

    print("\n5. Dossiê com o agente respondendo")

    class ClienteCompleto(ClienteFalso):
        def analise(self, _ref):
            return {
                "classifications": [{"code": "LABOR.X", "label": "Acidente do trabalho"}],
                "missing_information": [
                    {"code": "DOCUMENT.CAT", "status": "OPEN", "severity": "BLOCKING"}
                ],
            }

        def contradicoes(self, _ref):
            return {"items": []}

        def documentos(self, _ref):
            return {"items": [{"id": "doc_1"}]}

        def peticoes(self, _ref):
            return {
                "items": [
                    {
                        "id": "generation_1",
                        "version": 1,
                        "status": "DRAFT",
                        "blocking_findings": 2,
                    }
                ]
            }

        def estrategia(self, _ref):
            return None

        def pesquisas(self, _ref):
            return {
                "items": [
                    {
                        "id": "research_1",
                        "status": "COMPLETED",
                        "corpus_coverage": {"complete": False, "ratio": 0.849},
                    }
                ]
            }

    dossie.Cliente = ClienteCompleto  # type: ignore[assignment]
    montado = dossie.montar(caso_id)
    etapas = {e["codigo"]: e for e in montado["etapas"]}

    checar(montado["agente"]["disponivel"], "o dossiê marca o agente como disponível")
    checar(etapas["classificacao"]["estado"] == "pronto", "a classificação aparece na linha")
    checar(
        etapas["pendencias"]["estado"] == "atencao",
        "pendência indispensável em aberto é atenção, não pronto",
    )
    checar(
        "84" in etapas["pesquisa"]["detalhe"] or "85" in etapas["pesquisa"]["detalhe"],
        "a cobertura incompleta do acervo é declarada junto da pesquisa",
    )
    checar(
        any(c["rotulo"] == "CPF" for c in montado["cliente"]["campos"]),
        "a ficha do cliente é montada a partir dos fatos, com origem",
    )
    checar(
        etapas["peticao"]["estado"] == "atencao",
        "minuta com achado bloqueante aparece como retida, nunca como pronta",
    )
    checar(
        "2 achado" in etapas["peticao"]["detalhe"],
        "a etapa diz quantos achados retiveram a peça",
    )

    # Vínculo órfão visto pela tela: o dossiê é a porta de entrada, e era ali que o
    # advogado batia de novo e de novo em "caso não encontrado". Recriar tem de acontecer
    # sem ele pedir — não existe botão para isso.
    class ClienteSumido(ClienteCompleto):
        primeira: bool = True

        def analise(self, ref):
            if ClienteSumido.primeira:
                ClienteSumido.primeira = False
                raise ErroDoAgente("Caso não encontrado.", status=404)
            return super().analise(ref)

    orfao_na_tela = armazenamento.criar_caso("Tela Orfa", "acidente_trabalho_geral")["id"]
    espelho.garantir_caso(orfao_na_tela)
    dossie.Cliente = ClienteSumido  # type: ignore[assignment]
    espelho.Cliente = ClienteSumido  # type: ignore[assignment]
    recuperado = dossie.montar(orfao_na_tela)
    checar(
        recuperado["agente"]["disponivel"],
        "caso que sumiu do agente é recriado ao abrir o dossiê, em vez de repetir o erro",
    )
    checar(
        recuperado["agente"].get("recuperado") is True,
        "a recuperação fica declarada no dossiê, não acontece escondida",
    )
    dossie.Cliente = ClienteCompleto  # type: ignore[assignment]
    espelho.Cliente = ClienteFalso  # type: ignore[assignment]

    print("\n6. Paginação completa dos fatos")

    class ClientePaginado(Cliente):
        def __init__(self):
            self.chamadas: list[str] = []

        def _chamar(self, _metodo, caminho, **_kwargs):
            self.chamadas.append(caminho)
            offset = int(caminho.split("offset=")[1])
            todos = [{"id": f"fact_{indice}"} for indice in range(102)]
            return {
                "items": todos[offset : offset + 100],
                "total": len(todos),
                "limit": 100,
                "offset": offset,
            }

    paginado = ClientePaginado()
    pagina = paginado.fatos("case_01J00000000000000000000001")
    checar(len(pagina["items"]) == 102, "todos os fatos são lidos, não só os 20 padrão")
    checar(
        paginado.chamadas
        == [
            "/api/v1/cases/case_01J00000000000000000000001/facts?limit=100&offset=0",
            "/api/v1/cases/case_01J00000000000000000000001/facts?limit=100&offset=100",
        ],
        "a API usa limit/offset e avança até o total declarado",
    )

    class ClienteSemProgresso(Cliente):
        def __init__(self):
            pass

        def _chamar(self, _metodo, _caminho, **_kwargs):
            return {"items": [{"id": "fact_repetido"}], "total": 2}

    try:
        ClienteSemProgresso().fatos("case_01J00000000000000000000001")
    except ErroDoAgente:
        falhou_explicitamente = True
    else:
        falhou_explicitamente = False
    checar(
        falhou_explicitamente,
        "paginação sem progresso falha em vez de liberar um estado parcial",
    )

    print("\n7. Qualificação da parte com o CPF que os documentos revelaram")

    class ClienteQualificador(ClienteFalso):
        qualificadas: list[tuple[str, str, str]] = []
        parte_documento: str | None = None

        def caso(self, caso_ref):
            return {
                "id": caso_ref,
                "parties": [
                    {
                        "id": "party_1",
                        "role": "CLAIMANT",
                        "name": "Maria Santos",
                        "document": ClienteQualificador.parte_documento,
                    },
                    {
                        "id": "party_2",
                        "role": "RESPONDENT",
                        "name": "Empresa X",
                        "document": "12345678000199",
                    },
                ],
            }

        def qualificar_parte(self, caso_ref, parte_ref, *, documento):
            ClienteQualificador.qualificadas.append((caso_ref, parte_ref, documento))
            ClienteQualificador.parte_documento = documento
            return {"id": parte_ref, "document": documento}

    espelho.Cliente = ClienteQualificador  # type: ignore[assignment]
    ClienteFalso.fatos_devolvidos = [
        {"type": "PERSON.CPF", "value": {"digits": "12345678900"}, "status": "EXTRACTED"},
        {"type": "PERSON.CPF", "value": {"digits": "52998224725"}, "status": "CONFIRMED"},
    ]

    aplicado = espelho.qualificar_reclamante("case_01J00000000000000000000001")
    checar(aplicado == "52998224725", "o CPF confirmado vence o apenas extraído")
    checar(
        ClienteQualificador.qualificadas == [("case_01J00000000000000000000001", "party_1", "52998224725")],
        "só a parte reclamante é qualificada, e uma vez",
    )

    ClienteQualificador.qualificadas = []
    checar(
        espelho.qualificar_reclamante("case_01J00000000000000000000001") is None
        and ClienteQualificador.qualificadas == [],
        "parte que já tem documento não é sobrescrita — quem digitou vence o que foi lido",
    )

    ClienteQualificador.parte_documento = None
    ClienteFalso.fatos_devolvidos = [
        {"type": "PERSON.CPF", "value": {"digits": "11122233344"}, "status": "REJECTED"}
    ]
    checar(
        espelho.qualificar_reclamante("case_01J00000000000000000000001") is None,
        "CPF de fato rejeitado não qualifica ninguém",
    )
    espelho.Cliente = ClienteFalso  # type: ignore[assignment]

    print("\n8. O motivo da recusa chega em português")
    from app.agente import motivos

    checar(
        "CPF/CNPJ" in motivos.explicar("PARTY_FIELD_MISSING:document"),
        "código de qualificação incompleta vira frase que diz o que fazer",
    )
    checar(
        "data de admissão" in motivos.explicar("FACT_MISSING:EMPLOYMENT.ADMISSION_DATE"),
        "o tipo de fato aparece no vocabulário do escritório",
    )
    checar(
        motivos.explicar("ALGO_QUE_NAO_EXISTE") == "ALGO_QUE_NAO_EXISTE",
        "código desconhecido aparece como está, em vez de virar 'há uma pendência'",
    )
    checar(
        len(motivos.explicar_todos(["PARTIES_MISSING", "PARTIES_MISSING"])) == 1,
        "o mesmo motivo não é repetido na tela",
    )

    print("\n9. Envio da entrevista ao agente")

    class ClienteEntrevistador(ClienteFalso):
        enviadas: list[tuple[str, str]] = []
        resposta: dict = {}

        def enviar_entrevista(self, caso_ref, *, entrevista_id, transcricao, realizada_em, entrevistador):
            ClienteEntrevistador.enviadas.append((caso_ref, entrevista_id))
            return ClienteEntrevistador.resposta

    espelho.Cliente = ClienteEntrevistador  # type: ignore[assignment]

    pasta = armazenamento.DIR_ARQUIVOS / caso_id / "entrevistas"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho_entrevista = pasta / "atendimento.txt"
    caminho_entrevista.write_text("CLIENTE: entrei em 2018.", encoding="utf-8")
    entrevista = armazenamento.registrar_entrevista(
        caso_id,
        arquivo="atendimento.txt",
        caminho=caminho_entrevista,
        texto="CLIENTE: entrei em 2018.",
    )

    # Primeiro cenário: o agente está sem provedor de IA e não lê.
    ClienteEntrevistador.resposta = {"failure": "AI_UNAVAILABLE", "facts_recorded": 0}
    espelho.enviar_entrevista(caso_id, entrevista["id"])
    checar(
        not armazenamento.obter_entrevista(entrevista["id"])["enviada"],
        "leitura que falhou não marca a entrevista como lida — dá para tentar de novo",
    )

    ClienteEntrevistador.resposta = {
        "failure": "",
        "facts_recorded": 6,
        "summary": "Cliente relatou lesão de ombro.",
        "open_questions": ["Conferir CTPS."],
    }
    espelho.enviar_entrevista(caso_id, entrevista["id"])
    guardada = armazenamento.obter_entrevista(entrevista["id"])
    checar(guardada["enviada"] and guardada["fatos_gerados"] == 6, "a leitura bem-sucedida fica registrada")
    checar(
        guardada["resumo"].startswith("Cliente relatou"),
        "o resumo fica guardado aqui também — o dossiê explica a entrevista sem o agente",
    )

    ClienteEntrevistador.enviadas = []
    repetida = espelho.enviar_entrevista(caso_id, entrevista["id"])
    checar(
        repetida.get("ja_enviada") and ClienteEntrevistador.enviadas == [],
        "reenviar não chama o agente de novo — criaria fatos alegados em duplicata",
    )
    espelho.Cliente = ClienteFalso  # type: ignore[assignment]

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())

