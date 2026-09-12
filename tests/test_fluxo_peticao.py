"""O caminho inteiro, da entrevista à petição — sem banco e sem modelo.

POR QUE SEM BANCO

`tests/test_casos.py` acredita que redireciona o banco mexendo em
`armazenamento.CAMINHO_BANCO`; isso valia no tempo do SQLite e hoje não
redireciona nada — o banco vem de `SQLSERVER_*` (ver `app/banco.py`). Aqui o
armazenamento é substituído em memória, função por função, para este teste poder
rodar em qualquer máquina e nunca encostar num banco de verdade.

O QUE ELE PROTEGE, NA ORDEM DO FLUXO

1. `transcricao` escolhe a entrevista certa (a mais recente COM texto).
2. `estado` sabe dizer o que já existe antes de qualquer geração.
3. `gerar_completo` devolve as sete seções, monta o .docx e não vaza o contexto
   do prompt para a tela.
4. Gerar de novo **guarda a versão anterior** antes de sobrescrever — era o
   buraco: revisar por prompt arquivava, gerar de novo apagava.
5. Editar à mão preserva o texto do advogado e regrava o .docx.
6. Revisar por prompt versiona, volta para `IN_REVIEW` e registra a crítica.
7. Resposta estranha do modelo (sem `choices`) vira erro em português, não 500.
"""

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import armazenamento  # noqa: E402
from app import analise_documentos, jurimetria_caso, peticao_criticas, peticao_skills  # noqa: E402
from app import casos as casos_ocr  # noqa: E402
from app import peticao_local as pl  # noqa: E402
from app.agente import peticao_fluxo  # noqa: E402


def checar(condicao: bool, texto: str, detalhe: str = "") -> bool:
    print(("  PASS  " if condicao else "  FALHA ") + texto + (f"\n          {detalhe}" if not condicao and detalhe else ""))
    return condicao


CASO = "caso-1"

# ------------------------------------------------------------ banco em memória

BANCO: dict[str, object] = {}


def _zerar_banco() -> None:
    BANCO.clear()
    BANCO["peticao"] = None
    BANCO["docx"] = b""
    BANCO["versoes"] = []
    BANCO["criticas"] = []


def _obter_caso(caso_id: str):
    return {"id": caso_id, "cliente": "Maria Aparecida", "categoria": "doenca_ocupacional"}


def _listar_entrevistas(caso_id: str):
    # Fora de ordem e com uma sem texto de propósito: `transcricao` tem de
    # escolher a mais recente ENTRE as que têm texto.
    return [
        {"id": "e1", "criado_em": "2026-09-01T10:00:00+00:00", "texto": "relato antigo", "arquivo": "e1.txt"},
        {"id": "e3", "criado_em": "2026-09-05T10:00:00+00:00", "texto": "   ", "arquivo": "e3.txt"},
        {"id": "e2", "criado_em": "2026-09-03T10:00:00+00:00", "texto": "relato mais novo", "arquivo": "e2.txt"},
    ]


def _listar_entregas(caso_id: str):
    return [{"id": "d1", "arquivo": "cat.pdf"}, {"id": "d2", "arquivo": "vazio.pdf"}]


def _obter_entrega(entrega_id: str):
    textos = {"d1": "CAT emitida em 2024", "d2": ""}
    return {"id": entrega_id, "extracao": {"texto_completo": textos.get(entrega_id, "")}}


def _obter_peticao_local(caso_id: str):
    dados = BANCO["peticao"]
    if dados is None:
        return None
    copia = dict(dados)  # type: ignore[arg-type]
    copia["_docx"] = BANCO["docx"]
    return copia


def _salvar_peticao_local(caso_id: str, dados, docx: bytes) -> None:
    if not docx:
        raise ValueError("O DOCX da petição está vazio.")
    BANCO["peticao"] = {k: v for k, v in dados.items() if k != "_docx"}
    BANCO["docx"] = docx


def _registrar_versao_peticao(caso_id: str, dados) -> None:
    versoes = BANCO["versoes"]
    identificador = f"{caso_id}:{int(dados.get('version') or 1)}"
    for item in versoes:  # type: ignore[union-attr]
        if item["id"] == identificador:
            item["dados"] = dict(dados)
            return
    versoes.append(  # type: ignore[union-attr]
        {"id": identificador, "versao": int(dados.get("version") or 1), "dados": dict(dados)}
    )


def _listar_versoes_peticao(caso_id: str):
    return sorted(BANCO["versoes"], key=lambda v: v["versao"])  # type: ignore[arg-type]


def _montar_situacao(caso_id: str):
    return {
        "categoria": {"nome": "Doença ocupacional"},
        "progresso": {"obrigatorios_total": 23, "obrigatorios_entregues": 4},
    }


def instalar_dublês() -> None:
    """Troca TODO acesso externo por versões em memória."""
    armazenamento.obter_caso = _obter_caso
    armazenamento.listar_entrevistas = _listar_entrevistas
    armazenamento.listar_entregas = _listar_entregas
    armazenamento.obter_entrega = _obter_entrega
    armazenamento.obter_peticao_local = _obter_peticao_local
    armazenamento.salvar_peticao_local = _salvar_peticao_local
    armazenamento.registrar_versao_peticao = _registrar_versao_peticao
    armazenamento.listar_versoes_peticao = _listar_versoes_peticao
    armazenamento.obter_modelo = lambda codigo: None  # cai na logo Lara & Melo
    casos_ocr.montar_situacao = _montar_situacao
    analise_documentos.analisar = lambda caso_id: {"achados": []}
    # Jurimetria fora do ar é o caso comum numa máquina de desenvolvimento — e o
    # fluxo tem de seguir gerando a peça mesmo assim.
    jurimetria_caso.buscar_focada = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pgvector fora"))
    peticao_skills.instrucoes_da_categoria = lambda categoria: ""
    peticao_criticas.inicializar = lambda: None
    peticao_criticas.ultimas_da_categoria = lambda categoria, limite=20: []
    peticao_criticas.registrar = lambda **kwargs: BANCO["criticas"].append(kwargs)  # type: ignore[union-attr]
    peticao_criticas.listar_por_caso = lambda caso_id: list(BANCO["criticas"])  # type: ignore[arg-type]


# ------------------------------------------------------------ modelo de mentira

SECOES_FALSAS = [
    {"code": "HEADING", "label": "Endereçamento e qualificação", "content": "EXCELENTÍSSIMO"},
    # `&` e `<` de propósito: vão para o XML do .docx e precisam sair escapados.
    {"code": "FACTS", "label": "Dos fatos", "content": "Admitida em 2019 & dispensada\n\nem 2024 < prazo"},
    {"code": "LEGAL_GROUNDS", "label": "Do direito", "content": "Art. 7º"},
    {"code": "CLAIMS", "label": "Dos pedidos", "content": "a) reintegração"},
    {"code": "EVIDENCE", "label": "Das provas", "content": "CAT anexa"},
    {"code": "VALUE", "label": "Do valor da causa", "content": "R$ 50.000,00"},
    {"code": "CLOSING", "label": "Fechamento", "content": "Termos em que pede deferimento"},
]


def _resposta_de_geracao() -> dict:
    return {
        "analise": {
            "resumo": "Doença ocupacional com CAT emitida.",
            "cruzamento_entrevista_documentos": "A CAT confirma o relato.",
            "pontos_fortes": ["CAT"],
            "lacunas": ["falta laudo"],
            "fatos_confirmados": ["emissão da CAT"],
            "fatos_so_na_entrevista": ["pressão da chefia"],
            "observacoes": "conferir o laudo",
            "acoes_sugeridas": [
                {"titulo": "Ação de danos morais", "motivo": "assédio relatado", "pedidos": ["dano moral"], "prioridade": "AVALIAR"},
                {"titulo": "", "motivo": "sem título — deve ser descartada", "pedidos": [], "prioridade": "x"},
            ],
        },
        "secoes": SECOES_FALSAS,
        "pendencias": ["laudo médico"],
    }


def _resposta_de_revisao() -> dict:
    revisadas = [dict(s) for s in SECOES_FALSAS]
    revisadas[3]["content"] = "a) reintegração\n\nb) dano moral em pedido próprio"
    return {"secoes": revisadas}


#: A função de verdade, guardada antes de qualquer dublê — a etapa 9 precisa dela.
LLM_REAL = pl._llm_json


def dublar_modelo(resposta) -> None:
    """`_llm_json` passa a devolver `resposta` (ou o que a função devolver)."""
    pl._llm_json = lambda instrucao, entrada, timeout=180.0: (
        resposta() if callable(resposta) else resposta
    )


# ------------------------------------------------------------------- as etapas


def testar_transcricao() -> int:
    falhas = 0
    dados = peticao_fluxo.transcricao(CASO)
    falhas += not checar(dados["entrevista_id"] == "e2", f"usa a entrevista mais recente COM texto (usou {dados['entrevista_id']})")
    falhas += not checar(dados["caracteres"] == len("relato mais novo"), "conta os caracteres do texto escolhido")
    return falhas


def testar_estado_inicial() -> int:
    falhas = 0
    estado = peticao_fluxo.estado(CASO)
    falhas += not checar(estado["peticao_pronta"] is False, "sem petição salva, o fluxo diz que não está pronta")
    falhas += not checar(estado["analise"] is None, "sem geração, não existe análise")
    falhas += not checar(
        estado["preparacao"]["documentos_lidos"] == 1,
        f"conta só os documentos COM texto de OCR (contou {estado['preparacao']['documentos_lidos']})",
    )
    falhas += not checar(estado["preparacao"]["checklist_obrigatorios"] == 23, "traz o checklist obrigatório do caso")
    return falhas


def testar_geracao() -> int:
    falhas = 0
    dublar_modelo(_resposta_de_geracao)
    resultado = peticao_fluxo.gerar_completo(CASO)
    peticao = resultado["peticao"]

    falhas += not checar(resultado["status"] == "DONE", "a geração termina concluída")
    falhas += not checar(peticao["version"] == 1, f"a primeira petição é a versão 1 (veio {peticao['version']})")
    falhas += not checar(
        [s["code"] for s in peticao["sections"]] == [c for c, _ in pl.SECOES_PADRAO],
        "devolve as sete seções, na ordem padrão",
    )
    falhas += not checar(
        "contexto" not in (resultado["analise"] or {}),
        "o contexto do prompt NÃO vai para a tela (é a entrevista inteira do cliente)",
    )
    falhas += not checar(
        peticao["jurimetria"].get("disponivel") is False and bool(peticao["jurimetria"].get("aviso")),
        "jurimetria fora do ar não derruba a geração — vira aviso",
    )
    falhas += not checar(
        [a["titulo"] for a in resultado["analise"]["acoes_sugeridas"]] == ["Ação de danos morais"],
        "ação sugerida sem título é descartada",
    )
    falhas += not checar(
        resultado["analise"]["acoes_sugeridas"][0]["prioridade"] == "avaliar",
        "a prioridade é normalizada em minúsculas",
    )
    return falhas


def testar_docx() -> int:
    falhas = 0
    conteudo = pl.ler_docx(CASO)
    falhas += not checar(bool(conteudo), "o .docx foi gravado junto com a minuta")
    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        nomes = set(arquivo.namelist())
        documento = arquivo.read("word/document.xml").decode("utf-8")
    falhas += not checar(
        {"word/document.xml", "word/styles.xml", "word/header1.xml"} <= nomes,
        f"o pacote tem documento, estilos e cabeçalho ({sorted(nomes)})",
    )
    falhas += not checar(
        any(nome.startswith("word/media/") for nome in nomes), "a logo do escritório entra no pacote"
    )
    falhas += not checar("DOS FATOS" in documento, "cada seção entra com o rótulo em maiúsculas")
    falhas += not checar(
        "2019 &amp; dispensada" in documento and "&lt; prazo" in documento,
        "texto com & e < é escapado — senão o Word recusa o arquivo inteiro",
    )
    return falhas


def testar_gerar_de_novo_guarda_a_anterior() -> int:
    """O buraco: revisar por prompt arquivava a versão; gerar de novo a apagava."""
    falhas = 0
    dublar_modelo(_resposta_de_geracao)
    resultado = peticao_fluxo.gerar_completo(CASO)
    falhas += not checar(resultado["peticao"]["version"] == 2, "gerar de novo cria a versão seguinte")
    versoes = pl.historico_de_versoes(CASO)
    falhas += not checar(
        [v["versao"] for v in versoes] == [1],
        f"a versão 1 fica recuperável no histórico (histórico: {[v['versao'] for v in versoes]})",
    )
    falhas += not checar(
        bool((versoes[0]["dados"].get("sections") or [])) if versoes else False,
        "o que foi arquivado é a petição inteira, com as seções",
    )
    return falhas


def testar_edicao_a_mao() -> int:
    falhas = 0
    dados = pl.salvar_secoes(CASO, [{"code": "FACTS", "content": "Texto corrigido pelo advogado"}])
    fatos = next(s for s in dados["sections"] if s["code"] == "FACTS")
    falhas += not checar(fatos["content"] == "Texto corrigido pelo advogado", "a edição do advogado é gravada")
    outra = next(s for s in dados["sections"] if s["code"] == "CLAIMS")
    falhas += not checar(outra["content"] == "a) reintegração", "seção não enviada continua intacta")
    with zipfile.ZipFile(io.BytesIO(pl.ler_docx(CASO))) as arquivo:
        documento = arquivo.read("word/document.xml").decode("utf-8")
    falhas += not checar(
        "Texto corrigido pelo advogado" in documento, "o .docx é regravado com o texto editado"
    )
    return falhas


def testar_revisao_por_prompt() -> int:
    falhas = 0
    antes = pl.carregar(CASO)["version"]
    dublar_modelo(_resposta_de_revisao)
    dados = pl.revisar_com_prompt(
        CASO, prompt_critica="separe o dano moral", usuario="ana", generaliza=True
    )
    falhas += not checar(dados["version"] == antes + 1, f"a revisão cria a versão seguinte (v{dados['version']})")
    falhas += not checar(dados["status"] == "IN_REVIEW", "revisão por prompt volta para revisão humana")
    pedidos = next(s for s in dados["sections"] if s["code"] == "CLAIMS")
    falhas += not checar("dano moral em pedido próprio" in pedidos["content"], "a crítica foi aplicada aos pedidos")
    falhas += not checar(
        [v["versao"] for v in pl.historico_de_versoes(CASO)] == [1, antes],
        f"a versão revisada foi arquivada antes de ser sobrescrita ({[v['versao'] for v in pl.historico_de_versoes(CASO)]})",
    )
    falhas += not checar(
        bool(BANCO["criticas"]) and BANCO["criticas"][0]["usuario"] == "ana",  # type: ignore[index]
        "a crítica fica registrada com quem pediu",
    )
    falhas += not checar(
        "_docx" not in pl.para_api(dados), "o binário do .docx nunca vai na resposta da API"
    )
    return falhas


def testar_revisao_vazia() -> int:
    falhas = 0
    try:
        pl.revisar_com_prompt(CASO, prompt_critica="   ", usuario="ana")
        falhas += not checar(False, "crítica em branco é recusada")
    except pl.ErroPeticao:
        falhas += not checar(True, "crítica em branco é recusada com erro em português")
    return falhas


def testar_resposta_estranha_do_modelo() -> int:
    """Provedor que responde 200 com `choices` vazio não pode virar 500 na tela."""
    import os

    import httpx

    class RespostaFalsa:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"choices": []}

    falhas = 0
    dublê_atual = pl._llm_json
    post_original = httpx.post
    chave_antes = os.environ.get("DEEPSEEK_API_KEY")
    pl._llm_json = LLM_REAL
    httpx.post = lambda *a, **k: RespostaFalsa()
    os.environ["DEEPSEEK_API_KEY"] = "teste"
    try:
        pl._llm_json("instrucao", "entrada")
        falhas += not checar(False, "resposta sem `choices` vira ErroPeticao")
    except pl.ErroPeticao:
        falhas += not checar(True, "resposta sem `choices` vira ErroPeticao, não erro interno")
    except Exception as erro:
        falhas += not checar(
            False, "resposta sem `choices` vira ErroPeticao", f"veio {type(erro).__name__}: {erro}"
        )
    finally:
        httpx.post = post_original
        pl._llm_json = dublê_atual
        if chave_antes is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = chave_antes
    return falhas


def testar_entrevista_sem_conteudo() -> int:
    """Caso sem NENHUMA entrevista com texto não gera petição — e diz por quê.

    É o contrato de que a tela depende desde que a transcrição vazia deixou de
    ser gravada como se fosse a entrevista (ver `lib/transcricao.ts`): quando não
    houve áudio nem relato, o certo é recusar com explicação, e não redigir uma
    peça a partir de nada.
    """
    from app.agente.cliente import ErroDoAgente

    falhas = 0
    original = armazenamento.listar_entrevistas
    armazenamento.listar_entrevistas = lambda caso_id: [
        {"id": "e9", "criado_em": "2026-09-09T10:00:00+00:00", "texto": "", "arquivo": "e9.txt"}
    ]
    try:
        peticao_fluxo.transcricao(CASO)
        falhas += not checar(False, "entrevista sem texto é recusada")
    except ErroDoAgente as erro:
        falhas += not checar(
            "transcrição" in str(erro).lower(), f"a recusa explica o que falta ({erro})"
        )
    finally:
        armazenamento.listar_entrevistas = original

    # E o `estado` continua respondendo, para a tela poder mostrar o resto.
    armazenamento.listar_entrevistas = lambda caso_id: []
    try:
        estado = peticao_fluxo.estado(CASO)
        falhas += not checar(
            estado["entrevista"] is None and estado["peticao_pronta"] is True,
            "sem entrevista, o fluxo segue informando o que já existe",
        )
    finally:
        armazenamento.listar_entrevistas = original
    return falhas


def testar_skill_por_categoria() -> int:
    """A skill do escritório chega ao prompt — issue "Configurar skill por modelo de petição".

    Os critérios da issue que dão para medir aqui: cada categoria tem a SUA skill,
    mexer numa não afeta as outras, e o processamento usa a correspondente. O que
    decide isso é `_com_skill_do_escritorio`, e ele é chamado em toda geração.

    A ordem também é conferida: o contrato do prompt (o formato do JSON que
    `_normalizar_secoes` espera de volta) vem ANTES da orientação do escritório.
    Se a skill viesse primeiro, uma instrução do tipo "responda em tópicos"
    poderia mudar o formato e a petição inteira voltaria ilegível.
    """
    falhas = 0
    skills = {
        "doenca_ocupacional": "Cite sempre o nexo causal e o CID.",
        "assalto_carteiro": "Descreva o risco da atividade externa.",
    }
    peticao_skills.instrucoes_da_categoria = lambda categoria: skills.get(categoria, "")
    peticao_criticas.ultimas_da_categoria = lambda categoria, limite=20: (
        ["separe dano moral de material"] if categoria == "doenca_ocupacional" else []
    )
    try:
        contrato = "Devolva JSON: {\"secoes\": []}"
        montado = pl._com_skill_do_escritorio(CASO, contrato)

        falhas += not checar(
            "Cite sempre o nexo causal e o CID." in montado,
            "a skill da categoria do caso entra no prompt",
        )
        falhas += not checar(
            "Descreva o risco da atividade externa." not in montado,
            "a skill de OUTRA categoria não vaza para este caso",
        )
        falhas += not checar(
            "separe dano moral de material" in montado,
            "as correções já ensinadas na categoria também entram",
        )
        falhas += not checar(
            montado.index(contrato) < montado.index("Cite sempre o nexo"),
            "o formato de resposta vem antes da orientação do escritório",
        )

        # Categoria sem skill cadastrada: o prompt tem de voltar INTOCADO, que é o
        # comportamento de antes de a configuração existir.
        peticao_skills.instrucoes_da_categoria = lambda categoria: ""
        peticao_criticas.ultimas_da_categoria = lambda categoria, limite=20: []
        falhas += not checar(
            pl._com_skill_do_escritorio(CASO, contrato) == contrato,
            "sem skill nem correção, o prompt padrão não é alterado",
        )

        # pgvector fora do ar não pode derrubar a geração por causa de um reforço
        # opcional — é o motivo de as duas leituras serem protegidas.
        def explode(*a, **k):
            raise RuntimeError("pgvector fora")

        peticao_criticas.ultimas_da_categoria = explode
        try:
            igual = pl._com_skill_do_escritorio(CASO, contrato) == contrato
        except Exception as erro:
            igual = False
            falhas += not checar(False, "banco de skills fora do ar não derruba a geração", str(erro))
        else:
            falhas += not checar(igual, "banco de skills fora do ar não derruba a geração")
    finally:
        peticao_skills.instrucoes_da_categoria = lambda categoria: ""
        peticao_criticas.ultimas_da_categoria = lambda categoria, limite=20: []
    return falhas


def main_teste() -> int:
    instalar_dublês()
    _zerar_banco()
    falhas = 0
    for titulo, teste in (
        ("1. A entrevista que vira petição", testar_transcricao),
        ("2. Estado antes de gerar", testar_estado_inicial),
        ("3. Geração da minuta", testar_geracao),
        ("4. O arquivo .docx", testar_docx),
        ("5. Gerar de novo sem perder o anterior", testar_gerar_de_novo_guarda_a_anterior),
        ("6. Edição à mão", testar_edicao_a_mao),
        ("7. Revisão por prompt", testar_revisao_por_prompt),
        ("8. Crítica em branco", testar_revisao_vazia),
        ("9. Resposta estranha do modelo", testar_resposta_estranha_do_modelo),
        ("10. Entrevista sem conteúdo", testar_entrevista_sem_conteudo),
        ("11. Skill por categoria de petição", testar_skill_por_categoria),
    ):
        print(f"\n{titulo}")
        falhas += teste()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
