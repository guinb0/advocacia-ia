"""Petição inicial gerada no Acervo — entrevista + OCR, sem agente."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from xml.etree import ElementTree

import httpx

from . import (
    analise_documentos,
    armazenamento,
    jurimetria_caso,
    peticao_criticas,
    peticao_skills,
    rag,
)
from . import casos as casos_ocr

log = logging.getLogger("peticao_local")

ID_LOCAL = "local"
DOCX_STYLE_VERSION = 4
LOGO_LARA_MELO = Path(__file__).with_name("assets") / "lara-melo-logo.png"
MODELO_VISUAL_GERAL = "peticao_visual_geral"
SECOES_PADRAO = (
    ("HEADING", "Endereçamento e qualificação"),
    ("FACTS", "Dos fatos"),
    ("LEGAL_GROUNDS", "Do direito"),
    ("CLAIMS", "Dos pedidos"),
    ("EVIDENCE", "Das provas"),
    ("VALUE", "Do valor da causa"),
    ("CLOSING", "Fechamento"),
)


class ErroPeticao(RuntimeError):
    pass


def extrair_identidade_visual(conteudo: bytes) -> tuple[bytes, str, str]:
    """Extrai logo e fonte do modelo geral sem copiar fatos ou texto da peça."""
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
            nomes = set(arquivo.namelist())
            imagens = [
                nome
                for nome in nomes
                if nome.startswith("word/media/")
                and nome.lower().endswith((".png", ".jpg", ".jpeg"))
            ]
            if not imagens:
                raise ErroPeticao("O modelo geral precisa ter uma logo PNG ou JPEG.")

            # Logos normalmente estão no cabeçalho. Se houver mais imagens no
            # documento, prioriza a que está relacionada por um header.
            alvos_cabecalho: list[str] = []
            for nome in sorted(nomes):
                if not nome.startswith("word/_rels/header") or not nome.endswith(".rels"):
                    continue
                raiz = ElementTree.fromstring(arquivo.read(nome))
                for relacao in raiz:
                    alvo = relacao.attrib.get("Target", "")
                    if "image" in relacao.attrib.get("Type", "") and alvo:
                        alvos_cabecalho.append("word/" + alvo.lstrip("/"))
            candidatos = [nome for nome in alvos_cabecalho if nome in nomes] or imagens
            logo_nome = candidatos[0]
            logo = arquivo.read(logo_nome)

            fonte = "Arial"
            if "word/styles.xml" in nomes:
                raiz = ElementTree.fromstring(arquivo.read("word/styles.xml"))
                ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                for fontes in raiz.iter(f"{ns}rFonts"):
                    encontrada = fontes.attrib.get(f"{ns}ascii") or fontes.attrib.get(f"{ns}hAnsi")
                    if encontrada and len(encontrada) <= 80:
                        fonte = encontrada
                        break
            logo_nome_minusculo = logo_nome.lower()
            extensao = ".jpg" if logo_nome_minusculo.endswith((".jpg", ".jpeg")) else ".png"
            return logo, fonte, extensao
    except ErroPeticao:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as erro:
        raise ErroPeticao("Não foi possível ler a identidade visual deste .docx.") from erro


_NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _primeiro_val(raiz, tag: str, attr: str = "val") -> str | None:
    for el in raiz.iter(f"{_NS_W}{tag}"):
        v = el.attrib.get(f"{_NS_W}{attr}")
        if v:
            return v
    return None


def analisar_estilo(conteudo: bytes) -> dict[str, Any]:
    """O que dá para captar do padrão do escritório, além de logo e fonte.

    Tamanho da fonte, espaçamento entre linhas, alinhamento e margens — é o que a
    tela mostra como "identificamos isto no seu documento". Tudo best-effort: o
    atributo que não estiver no arquivo simplesmente não entra, e nada aqui
    interrompe o cadastro do modelo.
    """
    atributos: dict[str, Any] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
            nomes = set(arquivo.namelist())
            if "word/styles.xml" in nomes:
                estilos = ElementTree.fromstring(arquivo.read("word/styles.xml"))
                sz = _primeiro_val(estilos, "sz")  # em meios-pontos
                if sz and sz.isdigit():
                    atributos["tamanho_fonte_pt"] = round(int(sz) / 2, 1)
                linha = None
                for sp in estilos.iter(f"{_NS_W}spacing"):
                    linha = sp.attrib.get(f"{_NS_W}line")
                    if linha:
                        break
                if linha and linha.isdigit():
                    # 240 = simples, 360 = 1,5, 480 = duplo.
                    atributos["espacamento_linha"] = round(int(linha) / 240, 2)
                jc = _primeiro_val(estilos, "jc")
                if jc:
                    atributos["alinhamento"] = {
                        "both": "justificado",
                        "left": "à esquerda",
                        "center": "centralizado",
                        "right": "à direita",
                    }.get(jc, jc)
            if "word/document.xml" in nomes:
                doc = ElementTree.fromstring(arquivo.read("word/document.xml"))
                for mar in doc.iter(f"{_NS_W}pgMar"):
                    def cm(lado: str) -> float | None:
                        v = mar.attrib.get(f"{_NS_W}{lado}")
                        return round(int(v) / 1440 * 2.54, 1) if v and v.lstrip("-").isdigit() else None

                    margens = {lado: cm(lado) for lado in ("top", "right", "bottom", "left")}
                    if any(v is not None for v in margens.values()):
                        atributos["margens_cm"] = margens
                    break
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        return atributos
    return atributos


def identidade_visual() -> tuple[bytes, str, str, str]:
    """Identidade vigente: banco em produção; Lara & Melo como reserva segura."""
    try:
        registro = armazenamento.obter_modelo(MODELO_VISUAL_GERAL)
    except Exception:
        log.warning("modelo visual indisponível no banco; usando Lara & Melo", exc_info=True)
        registro = None
    if registro:
        logo, fonte, extensao = extrair_identidade_visual(registro["conteudo"])
        return logo, fonte, extensao, registro["nome_arquivo"]
    return LOGO_LARA_MELO.read_bytes(), "Arial", ".png", "Padrão Lara & Melo"


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def existe(caso_id: str) -> bool:
    return armazenamento.obter_peticao_local(caso_id) is not None


def carregar(caso_id: str) -> dict[str, Any] | None:
    dados = armazenamento.obter_peticao_local(caso_id)
    if dados is None:
        return None
    dados.pop("_docx", None)
    return dados


def _salvar(caso_id: str, dados: dict[str, Any]) -> dict[str, Any]:
    dados["updated_at"] = _agora()
    dados["docx_style_version"] = DOCX_STYLE_VERSION
    armazenamento.salvar_peticao_local(
        caso_id,
        dados,
        montar_docx(dados.get("sections") or []),
    )
    return dados


def _llm_json(
    instrucao: str, entrada: str, *, timeout: float = 180.0
) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroPeticao("DEEPSEEK_API_KEY ausente — configure no .env.")
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    modelo = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    try:
        resposta = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": modelo,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": instrucao},
                    {"role": "user", "content": entrada[:120_000]},
                ],
            },
            timeout=timeout,
        )
        resposta.raise_for_status()
        conteudo = resposta.json()["choices"][0]["message"]["content"]
        saida = json.loads(conteudo)
    # `IndexError` e `TypeError` não estavam aqui, e é justamente o que um
    # provedor devolve quando filtra a resposta: HTTP 200 com `choices: []`. O
    # erro subia cru e a tela mostrava 500 sem dizer nada ao advogado, que ficava
    # sem saber se devia tentar de novo — e devia.
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError) as erro:
        log.warning("petição local: LLM falhou: %s", erro)
        raise ErroPeticao("O modelo não respondeu — tente de novo.") from erro
    if not isinstance(saida, dict):
        # JSON válido que não é objeto (uma lista, um número) quebraria adiante,
        # no `.get` de quem chamou, longe daqui.
        log.warning("petição local: LLM devolveu %s em vez de objeto", type(saida).__name__)
        raise ErroPeticao("O modelo não respondeu no formato esperado — tente de novo.")
    return saida


def _categoria_do_caso(caso_id: str) -> str:
    caso = armazenamento.obter_caso(caso_id) or {}
    return str(caso.get("categoria") or "")


#: Quantas lições de uma categoria entram automaticamente no prompt das próximas
#: gerações — a retroalimentação da issue "Permitir alteração da petição por
#: prompt com rastreabilidade" ("a IA vai aprendendo até sair do jeitinho que
#: eles querem").
#:
#: Era 5, e 5 quebrava a promessa: medido contra o banco, gravadas 7 correções na
#: mesma categoria, a IA lembrava da 3ª à 7ª e ESQUECIA as duas primeiras — o
#: escritório reensinava o que já tinha ensinado. 20 cabe no prompt e cobre o que
#: uma categoria acumula em meses; repetidas não gastam vaga (`_chave`), e o que
#: for marcado "só deste caso" nem chega aqui.
CRITICAS_RECENTES_POR_CATEGORIA = 20


def _com_skill_do_escritorio(caso_id: str, instrucao: str) -> str:
    """Acrescenta o que o escritório já ensinou sobre esta categoria de caso.

    Duas fontes, nesta ordem — configuração explícita primeiro, aprendizado
    implícito depois:

    1. A skill cadastrada em `peticao_skills` (issue "Configurar skill por
       modelo de petição") — instrução deliberada, escrita pra isso.
    2. As últimas críticas que advogados fizeram em petições desta MESMA
       categoria, mesmo em OUTROS casos (`peticao_criticas`) — retroalimentação
       automática: o escritório não precisa repetir a mesma correção caso após
       caso, porque a próxima geração já nasce considerando as anteriores.

    Vem DEPOIS do contrato do prompt (papel, formato do JSON), nunca antes: as
    duas são conteúdo — o que destacar, como abordar a categoria —, e não podem
    mudar o formato que `_normalizar_secoes` espera receber de volta. Sem nada
    cadastrado, `instrucao` volta intocada — mesmo comportamento de antes desta
    configuração existir.
    """
    categoria = _categoria_do_caso(caso_id)
    skill = peticao_skills.instrucoes_da_categoria(categoria).strip()
    try:
        peticao_criticas.inicializar()
        criticas = peticao_criticas.ultimas_da_categoria(
            categoria, limite=CRITICAS_RECENTES_POR_CATEGORIA
        )
    except Exception:
        # Mesma régua de `instrucoes_da_categoria`: uma oscilação de rede no
        # pgvector não pode derrubar a geração por causa de um reforço opcional.
        criticas = []

    blocos = [instrucao]
    if skill:
        blocos.append(
            "=== ORIENTAÇÃO DO ESCRITÓRIO PARA ESTA CATEGORIA DE CASO ===\n" + skill
        )
    if criticas:
        listadas = "\n".join(f"- {c}" for c in criticas)
        blocos.append(
            "=== CORREÇÕES QUE O ESCRITÓRIO JÁ PEDIU EM PETIÇÕES DESTA CATEGORIA ===\n"
            f"{listadas}\n"
            "Aplique estas correções diretamente, sem repetir o erro que motivou cada uma."
        )
    if len(blocos) == 1:
        return instrucao
    blocos.append("Aplique o que vier acima sem contrariar o formato de resposta pedido.")
    return "\n\n".join(blocos)


def _documentos_ocr(caso_id: str) -> list[dict[str, str]]:
    """O texto de OCR de cada anexo, em UMA consulta (ver `_documentos_do_caso`).

    Era um `obter_entrega` por arquivo, e a geração da petição abre este caminho
    junto com o da análise: num caso de 46 anexos davam ~180 idas ao banco antes de
    a primeira palavra ir para o modelo.
    """
    documentos = []
    for entrega in armazenamento.listar_extracoes_do_caso(caso_id):
        texto = str((entrega.get("extracao") or {}).get("texto_completo") or "").strip()
        if not texto:
            continue
        documentos.append(
            {
                "arquivo": str(entrega.get("arquivo") or ""),
                "texto": texto[:8000],
            }
        )
    return documentos


def _identidade_do_reclamante(caso_id: str, caso: dict[str, Any]) -> list[str]:
    """Quem é o autor da ação, com a autoridade do CADASTRO — não da transcrição.

    O CASO QUE OBRIGOU ISTO

    Caso `da5a030b`: cliente GUILHERME NUNES BEZERRA, com CPF no cadastro. A
    transcrição da entrevista tem, de passagem, "...tado chamado Roosevelt e aí
    eles machucaram com a moto da empresa..." — um terceiro citado na conversa, ou
    um erro do reconhecimento de voz. A petição saiu qualificando "ROOSEVELT
    RIVERS DA SILVA" como reclamante, e com "CPF [PENDENTE]" logo ao lado, num
    caso em que o CPF estava gravado.

    O nome do autor é a única coisa de uma petição que não se pode errar, e o
    sistema já o sabe. Antes ele ia como uma linha solta ("CLIENTE: ...") no alto
    de 4 mil caracteres de transcrição, sem dizer que aquilo era a fonte da
    verdade; o modelo preferiu o nome que aparecia no meio da conversa.

    Aqui a identidade vai num bloco próprio, dito como autoritativo, com o que o
    cadastro tem (o CPF vem da consulta por CPF da entrevista, ver
    `app/consultas.py`). Duas instruções acompanham: nome diferente deste é de
    TERCEIRO, e dado que está nesta lista não sai como [PENDENTE].
    """
    try:
        qualificacao = armazenamento.obter_qualificacao(caso_id) or {}
    except Exception:  # noqa: BLE001 - cadastro ausente não impede a geração
        log.warning("qualificação indisponível para o caso %s", caso_id, exc_info=True)
        qualificacao = {}

    campos = (
        ("Nome completo", caso.get("cliente")),
        ("CPF", qualificacao.get("cpf")),
        ("Data de nascimento", qualificacao.get("nascimento")),
        ("Sexo", qualificacao.get("sexo")),
        ("Nome da mãe", qualificacao.get("nome_mae")),
        ("Endereço", qualificacao.get("endereco")),
        ("CEP", qualificacao.get("cep")),
        ("Telefone", caso.get("telefone")),
        ("E-mail", qualificacao.get("email")),
    )
    conhecidos = [f"- {rotulo}: {valor}" for rotulo, valor in campos if str(valor or "").strip()]
    if not conhecidos:
        return []

    return [
        "=== IDENTIDADE DO RECLAMANTE (vem do CADASTRO do caso) ===",
        *conhecidos,
        "",
        "Esta lista é a ÚNICA fonte válida para qualificar o autor da ação. Nome que "
        "apareça na transcrição ou nos documentos e seja diferente do nome acima é de "
        "TERCEIRO (colega, condutor, médico, testemunha, vítima) — nunca do autor. "
        "E não escreva [PENDENTE] para dado que esteja nesta lista: use o valor.",
        "",
    ]


def _montar_contexto(caso_id: str, texto_entrevista: str) -> str:
    caso = armazenamento.obter_caso(caso_id) or {}
    situacao = casos_ocr.montar_situacao(caso_id) or {}
    categoria = (
        (situacao.get("categoria") or {}).get("nome") or caso.get("categoria") or ""
    )
    progresso = situacao.get("progresso") or {}

    linhas = [
        *_identidade_do_reclamante(caso_id, caso),
        f"CATEGORIA: {categoria}",
        "",
        "=== ENTREVISTA (transcrição) ===",
        texto_entrevista[:55_000],
    ]

    documentos = _documentos_ocr(caso_id)
    if documentos:
        linhas.append("\n=== DOCUMENTOS (texto extraído por OCR) ===")
        for doc in documentos[:20]:
            linhas.append(f"\n--- {doc['arquivo']} ---\n{doc['texto']}")

    try:
        achados = analise_documentos.analisar(caso_id).get("achados") or []
    except Exception as erro:
        log.warning("petição local: análise de documentos: %s", erro)
        achados = []

    if achados:
        linhas.append("\n=== ACHADOS (cruzamento entrevista × documentos) ===")
        for achado in achados[:15]:
            marca = "CONTRADIZ entrevista — " if achado.get("contradiz") else ""
            linhas.append(
                f"- {marca}{achado.get('informacao', '')} "
                f"({achado.get('documento', '')}): "
                f'"{str(achado.get("citacao", ""))[:200]}"'
            )

    obrig = progresso.get("obrigatorios_total")
    entregues = progresso.get("obrigatorios_entregues")
    if obrig is not None:
        linhas.append(
            f"\n=== CHECKLIST ===\n{entregues}/{obrig} obrigatórios entregues"
        )

    return "\n".join(linhas)[:110_000]


def analisar(caso_id: str, *, texto_entrevista: str) -> dict[str, Any]:
    contexto = _montar_contexto(caso_id, texto_entrevista)
    saida = _llm_json(
        _com_skill_do_escritorio(
            caso_id,
            """Você é advogado trabalhista. Cruze a ENTREVISTA com os DOCUMENTOS (OCR).
Devolva JSON:
{
  "resumo": "síntese jurídica em 4-8 frases",
  "cruzamento_entrevista_documentos": "o que a entrevista diz vs. documentos",
  "pontos_fortes": ["pontos com prova ou relato consistente"],
  "lacunas": ["o que falta provar ou documentar"],
  "fatos_confirmados": ["fatos sustentados por documento"],
  "fatos_so_na_entrevista": ["alegações sem prova documental"],
  "observacoes": "alertas ao advogado"
}
Não invente fatos. Diferencie alegação de fato documentado.""",
        ),
        contexto,
    )
    return {
        "resumo": str(saida.get("resumo") or "").strip(),
        "cruzamento_entrevista_documentos": str(
            saida.get("cruzamento_entrevista_documentos") or ""
        ).strip(),
        "pontos_fortes": [
            str(x) for x in (saida.get("pontos_fortes") or []) if str(x).strip()
        ],
        "lacunas": [str(x) for x in (saida.get("lacunas") or []) if str(x).strip()],
        "fatos_confirmados": [
            str(x) for x in (saida.get("fatos_confirmados") or []) if str(x).strip()
        ],
        "fatos_so_na_entrevista": [
            str(x)
            for x in (saida.get("fatos_so_na_entrevista") or [])
            if str(x).strip()
        ],
        "observacoes": str(saida.get("observacoes") or "").strip(),
        "contexto": contexto[:80_000],
    }


def _normalizar_secoes(brutas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    por_codigo = {str(s.get("code") or ""): s for s in brutas}
    secoes: list[dict[str, Any]] = []
    for codigo, rotulo in SECOES_PADRAO:
        item = por_codigo.get(codigo) or {}
        conteudo = str(item.get("content") or "").strip()
        if not conteudo and codigo in por_codigo:
            conteudo = str(por_codigo[codigo].get("texto") or "").strip()
        secoes.append(
            {
                "code": codigo,
                "label": str(item.get("label") or rotulo),
                "content": conteudo,
                "written_by": "agent",
                "supporting_fact_ids": [],
                "cited_precedent_ids": [],
            }
        )
    return secoes


def _analisar_jurimetria_da_minuta(
    secoes: list[dict[str, Any]], *, texto_para_uf: str = ""
) -> tuple[dict[str, Any], str]:
    """Compara a minuta pronta com decisões reais e gera apêndice auditável.

    `texto_para_uf` foca a busca no TRT do estado do caso (mesmo critério do
    painel), para o apêndice da peça citar precedentes daquela jurisdição — e
    não do acervo nacional — quando o estado é identificável nos documentos.
    """
    consulta = "\n\n".join(
        str(secao.get("content") or "")
        for secao in secoes
        if secao.get("code") in {"FACTS", "LEGAL_GROUNDS", "CLAIMS", "EVIDENCE"}
    ).strip()
    jurisdicao = ""
    try:
        similares, jurisdicao, _uf = jurimetria_caso.buscar_focada(
            consulta, texto_para_uf=texto_para_uf
        )
    except Exception as erro:
        log.warning("petição local: jurimetria indisponível: %s", erro)
        aviso = (
            "A base de processos semelhantes não respondeu durante a geração. "
            "Nenhum percentual ou conclusão jurimétrica foi estimado."
        )
        return {"disponivel": False, "aviso": aviso, "precedentes": []}, aviso
    if not similares:
        aviso = "Nenhum processo suficientemente semelhante foi localizado."
        return {"disponivel": False, "aviso": aviso, "precedentes": []}, aviso

    estatisticas = rag._estatisticas_amostra(similares)
    usados = similares[:10]
    referencias = {
        f"P{indice}": trecho.referencia()
        for indice, trecho in enumerate(usados, start=1)
    }
    contexto = []
    for indice, trecho in enumerate(usados, start=1):
        ref = referencias[f"P{indice}"]
        contexto.append(
            f"[P{indice}] processo={ref.get('processo') or ref.get('identificador')} "
            f"resultado={ref.get('resultado') or 'INDEFINIDO'} "
            f"órgão={ref.get('vara') or 'não informado'} "
            f"tipo={ref.get('tipo_documento') or 'não informado'} "
            f"similaridade={ref.get('similaridade')}\n{trecho.texto[:2800]}"
        )

    leitura: dict[str, Any] = {}
    try:
        leitura = _llm_json(
            """Compare a MINUTA somente com as DECISÕES fornecidas. Identifique
fundamentos recorrentes, distinções e riscos. Não trate frequência como probabilidade
de êxito nem atribua causa ao desfecho sem texto expresso. Toda conclusão deve citar
P1, P2 etc. Não invente referência. Responda JSON:
{"sintese":"...","fundamentos":[{"ponto":"...","impacto":"...","processos":["P1"]}],
"riscos":[{"ponto":"...","distincao":"...","processos":["P2"]}]}""",
            f"MINUTA:\n{consulta[:30_000]}\n\nDECISÕES:\n" + "\n\n".join(contexto),
            timeout=150,
        )
    except ErroPeticao as erro:
        log.warning("petição local: leitura jurimétrica falhou: %s", erro)

    validos = set(referencias)

    def itens_validos(chave: str) -> list[dict[str, Any]]:
        itens = []
        for bruto in leitura.get(chave) or []:
            if not isinstance(bruto, dict):
                continue
            refs = [
                str(ref) for ref in bruto.get("processos") or [] if str(ref) in validos
            ]
            if refs:
                itens.append({**bruto, "processos": refs})
        return itens[:6]

    fundamentos = itens_validos("fundamentos")
    riscos = itens_validos("riscos")
    merito = estatisticas["desfechos_merito"]
    semelhanca = estatisticas["similaridade_amostra"]
    linhas = [
        (
            f"Amostra: {estatisticas['processos_analisados']} processos; similaridade "
            f"mediana {semelhanca['mediana']:.3f} (mínima {semelhanca['minima']:.3f}; "
            f"máxima {semelhanca['maxima']:.3f})."
        ),
    ]
    if merito["processos"]:
        linhas.append(
            f"Desfechos de mérito: {merito['processos']}; procedentes ou parcialmente "
            f"procedentes: {merito['favoraveis']} ({merito['percentual']:.1f}%)."
        )
    linhas.extend(
        [estatisticas["aviso"], "", str(leitura.get("sintese") or "").strip()]
    )
    if fundamentos:
        linhas.extend(["", "Fundamentos que orientaram a minuta:"])
        for item in fundamentos:
            linhas.append(
                f"• {item.get('ponto', '')}: {item.get('impacto', '')} "
                f"[{', '.join(item['processos'])}]"
            )
    if riscos:
        linhas.extend(["", "Riscos e distinções relevantes:"])
        for item in riscos:
            linhas.append(
                f"• {item.get('ponto', '')}: {item.get('distincao', '')} "
                f"[{', '.join(item['processos'])}]"
            )
    linhas.extend(["", "Decisões consultadas:"])
    for indice, trecho in enumerate(usados, start=1):
        ref = referencias[f"P{indice}"]
        processo = ref.get("processo") or ref.get("identificador") or "não informado"
        linhas.append(
            f"[P{indice}] Processo {processo} — {ref.get('resultado') or 'desfecho não informado'}; "
            f"{ref.get('vara') or 'órgão não informado'}; similaridade {trecho.similaridade:.3f}."
        )
    resultado = {
        "disponivel": True,
        "origem": "embeddings_advocacia_ia",
        "consulta_vetorial": True,
        "jurisdicao": jurisdicao,
        "estatisticas": estatisticas,
        "sintese": str(leitura.get("sintese") or "").strip(),
        "fundamentos": fundamentos,
        "riscos": riscos,
        "precedentes": [
            {"indice": indice, **referencia}
            for indice, referencia in referencias.items()
        ],
        "aviso": estatisticas["aviso"],
    }
    return resultado, "\n".join(linhas).strip()


def redigir(
    caso_id: str, *, analise: dict[str, Any], texto_entrevista: str
) -> tuple[list[dict[str, Any]], list[str]]:
    contexto = analise.get("contexto") or _montar_contexto(caso_id, texto_entrevista)
    saida = _llm_json(
        _com_skill_do_escritorio(
            caso_id,
            """Redija uma PETIÇÃO INICIAL trabalhista completa em português formal.
Use SOMENTE fatos da entrevista e documentos — não invente.
Marque com [PENDENTE: motivo] o que depender só de alegação sem prova.
JSON:
{
  "secoes": [
    {"code": "HEADING", "label": "Endereçamento e qualificação", "content": "..."},
    {"code": "FACTS", "label": "Dos fatos", "content": "..."},
    {"code": "LEGAL_GROUNDS", "label": "Do direito", "content": "..."},
    {"code": "CLAIMS", "label": "Dos pedidos", "content": "..."},
    {"code": "EVIDENCE", "label": "Das provas", "content": "..."},
    {"code": "VALUE", "label": "Do valor da causa", "content": "..."},
    {"code": "CLOSING", "label": "Fechamento", "content": "..."}
  ],
  "pendencias": ["fatos sem comprovação documental"]
}
Cada content em parágrafos separados por linha em branco.""",
        ),
        (
            f"ANÁLISE:\n{analise.get('resumo', '')}\n"
            f"Cruzamento: {analise.get('cruzamento_entrevista_documentos', '')}\n"
            f"Lacunas: {', '.join(analise.get('lacunas') or [])}\n"
            f"Confirmados: {', '.join(analise.get('fatos_confirmados') or [])}\n\n"
            f"MATERIAL:\n{contexto[:90_000]}"
        ),
        timeout=240.0,
    )
    secoes = _normalizar_secoes(saida.get("secoes") or [])
    if not any(s["content"] for s in secoes):
        raise ErroPeticao("O modelo não devolveu texto da petição.")
    return secoes, [str(p) for p in (saida.get("pendencias") or []) if str(p).strip()]


def gerar(caso_id: str, *, texto_entrevista: str) -> dict[str, Any]:
    """Analisa e redige em uma chamada única à DeepSeek."""
    contexto = _montar_contexto(caso_id, texto_entrevista)
    saida = _llm_json(
        _com_skill_do_escritorio(
            caso_id,
            """Você é advogado trabalhista e redator de petições iniciais.
Em UMA resposta, organize o material do caso e redija uma minuta completa.
Use a entrevista como ALEGAÇÃO e os documentos como prova. Não invente fatos.
Onde faltar dado indispensável, escreva [PENDENTE: explicação].

Devolva JSON exatamente com:
{
  "analise": {
    "resumo": "síntese jurídica",
    "cruzamento_entrevista_documentos": "confronto entre relato e provas",
    "pontos_fortes": ["..."], "lacunas": ["..."],
    "fatos_confirmados": ["..."], "fatos_so_na_entrevista": ["..."],
    "observacoes": "alertas para revisão",
    "acoes_sugeridas": [
      {"titulo":"nome da ação adicional ou conexa", "motivo":"por que os fatos podem justificar esta peça", "pedidos":["pedido possível"], "prioridade":"principal|alternativa|avaliar"}
    ]
  },
  "secoes": [
    {"code":"HEADING","label":"Endereçamento e qualificação","content":"..."},
    {"code":"FACTS","label":"Dos fatos","content":"..."},
    {"code":"LEGAL_GROUNDS","label":"Do direito","content":"..."},
    {"code":"CLAIMS","label":"Dos pedidos","content":"..."},
    {"code":"EVIDENCE","label":"Das provas","content":"..."},
    {"code":"VALUE","label":"Do valor da causa","content":"..."},
    {"code":"CLOSING","label":"Fechamento","content":"..."}
  ],
  "pendencias": ["..."]
}
Em `acoes_sugeridas`, inclua de zero a três peças DIFERENTES da minuta principal,
somente se os fatos realmente apontarem para elas. Não sugira duplicata, recurso,
ou peça sem base mínima; quando não houver outra ação cabível, devolva [].
Cada content deve conter parágrafos separados por linha em branco.""",
        ),
        contexto,
        timeout=240.0,
    )
    bruto_analise = saida.get("analise") or {}
    analise = {
        "resumo": str(bruto_analise.get("resumo") or "").strip(),
        "cruzamento_entrevista_documentos": str(
            bruto_analise.get("cruzamento_entrevista_documentos") or ""
        ).strip(),
        "pontos_fortes": [str(x) for x in bruto_analise.get("pontos_fortes") or []],
        "lacunas": [str(x) for x in bruto_analise.get("lacunas") or []],
        "fatos_confirmados": [
            str(x) for x in bruto_analise.get("fatos_confirmados") or []
        ],
        "fatos_so_na_entrevista": [
            str(x) for x in bruto_analise.get("fatos_so_na_entrevista") or []
        ],
        "observacoes": str(bruto_analise.get("observacoes") or "").strip(),
        "acoes_sugeridas": [
            {
                "titulo": str(item.get("titulo") or "").strip(),
                "motivo": str(item.get("motivo") or "").strip(),
                "pedidos": [str(p).strip() for p in item.get("pedidos") or [] if str(p).strip()],
                "prioridade": str(item.get("prioridade") or "avaliar").strip().lower(),
            }
            for item in bruto_analise.get("acoes_sugeridas") or []
            if isinstance(item, dict) and str(item.get("titulo") or "").strip()
        ][:3],
    }
    secoes = _normalizar_secoes(saida.get("secoes") or [])
    if not any(secao["content"] for secao in secoes):
        raise ErroPeticao("O modelo não devolveu texto da petição.")
    jurimetria, _ = _analisar_jurimetria_da_minuta(secoes, texto_para_uf=contexto)
    pendencias = [str(p) for p in saida.get("pendencias") or [] if str(p).strip()]
    agora = _agora()
    anterior = carregar(caso_id) or {}
    versao = int(anterior.get("version") or 0) + 1
    # A versão que está sendo substituída vai para o histórico ANTES de ser
    # sobrescrita — `peticoes_locais` guarda só a atual (chave é o caso).
    #
    # `revisar_com_prompt` já fazia isto e gerar de novo não: o advogado clicava
    # "Gerar de novo" (a tela até avisa que "cria uma nova versão") e a minuta
    # anterior — com as correções que ele já tinha feito à mão — desaparecia sem
    # deixar cópia. O painel de rastreabilidade mostrava um salto de versão sem
    # nada atrás dele. Vem antes de `_salvar` de propósito: se o histórico falhar,
    # a petição anterior continua inteira no lugar e é só tentar de novo.
    if anterior:
        armazenamento.registrar_versao_peticao(caso_id, anterior)
    dados = {
        "id": ID_LOCAL,
        "document_type": "INITIAL_PETITION",
        "status": "IN_REVIEW",
        "version": versao,
        "title": "Petição inicial",
        "created_at": anterior.get("created_at") or agora,
        "updated_at": agora,
        "analise": analise,
        "jurimetria": jurimetria,
        "sections": secoes,
        "readiness": {
            "ready": True,
            "blocking_issues": [],
            "warnings": analise.get("lacunas") or [],
            "pendencias": pendencias or analise.get("fatos_so_na_entrevista") or [],
            "completo": not pendencias and not analise.get("lacunas"),
        },
        "review": {
            "findings": [],
            "summary": analise.get("observacoes", ""),
            "blocking": 0,
        },
        "blocking_findings": 0,
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    }
    _salvar(caso_id, dados)
    return dados


#: Quantas peças anexas um caso pode ter. Três é o teto do que a análise sugere
#: (`acoes_sugeridas`), e é também o limite do que um advogado revisa de uma vez —
#: peça que ninguém lê é token gasto e risco de ir a protocolo sem conferência.
MAX_ANEXAS_POR_CASO = 3


def id_da_anexa(caso_id: str, titulo: str) -> str:
    """Identificador estável da peça a partir do título.

    Determinístico de propósito: mandar redigir "Ação de danos morais" duas vezes
    substitui a peça em vez de criar uma segunda igual. O caso entra no id porque
    o mesmo título aparece em casos diferentes.
    """
    limpo = re.sub(r"[^a-z0-9]+", "-", _sem_acento(titulo).lower()).strip("-")
    return f"{caso_id}:{limpo[:60] or 'peca'}"


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn"
    )


def listar_anexas(caso_id: str) -> list[dict[str, Any]]:
    """As outras peças já redigidas deste caso, como a tela as mostra."""
    saida = []
    for linha in armazenamento.listar_peticoes_anexas(caso_id):
        dados = linha.get("dados") or {}
        saida.append(
            {
                "id": linha["id"],
                "titulo": linha.get("titulo") or "",
                "motivo": linha.get("motivo") or "",
                "gerada_por": linha.get("gerada_por") or "",
                "criado_em": linha.get("criado_em"),
                "atualizado_em": linha.get("atualizado_em"),
                "pendencias": dados.get("pendencias") or [],
                "secoes": len(dados.get("sections") or []),
            }
        )
    return saida


def obter_anexa(peca_id: str) -> dict[str, Any] | None:
    """Uma peça anexa com as seções, no mesmo formato que `para_api` devolve para
    a petição inicial — é o que a tela usa para abrir a peça em edição."""
    registro = armazenamento.obter_peticao_anexa(peca_id)
    if not registro:
        return None
    return para_api(registro["dados"])


def salvar_secoes_anexa(peca_id: str, secoes: list[dict[str, str]]) -> dict[str, Any]:
    """Grava o texto editado de uma peça anexa. Mesma lógica de `salvar_secoes`,
    para a peça irmã em vez da petição inicial — ver `armazenamento.salvar_peticao_anexa`.
    """
    registro = armazenamento.obter_peticao_anexa(peca_id)
    if not registro:
        raise ErroPeticao("Peça não encontrada.")

    dados = dict(registro["dados"])
    por_codigo = {s["code"]: s.get("content", "") for s in secoes if s.get("code")}
    for secao in dados.get("sections") or []:
        if secao.get("code") in por_codigo:
            secao["content"] = por_codigo[secao["code"]]
    dados["updated_at"] = _agora()

    armazenamento.salvar_peticao_anexa(
        registro["caso_id"],
        peca_id,
        titulo=str(registro.get("titulo") or dados.get("title") or ""),
        motivo=str(registro.get("motivo") or ""),
        dados=dados,
        docx=montar_docx(dados.get("sections") or []),
        gerada_por=str(registro.get("gerada_por") or ""),
    )
    return para_api(dados)


def gerar_anexa(
    caso_id: str,
    *,
    titulo: str,
    motivo: str = "",
    pedidos: list[str] | None = None,
    texto_entrevista: str,
    gerada_por: str = "",
) -> dict[str, Any]:
    """Redige UMA das outras ações sugeridas, a partir do material do mesmo caso.

    POR QUE NÃO É A MESMA FUNÇÃO DA PETIÇÃO INICIAL

    `gerar` produz A peça do caso: versiona, guarda o anterior no histórico, entra
    em revisão, é revisada por prompt e aprovada. Estas são peças irmãs, redigidas
    do mesmo material para OUTRA ação — o escritório quer levar duas ações do mesmo
    acidente, e até aqui o banco não permitia (a chave de `peticoes_locais` é o
    caso, então a segunda peça apagava a primeira).

    A minuta principal NÃO é tocada aqui. É o ponto: quem clica em "gerar esta
    peça" na sugestão não pode perder a petição inicial que já revisou.

    O TÍTULO DA SUGESTÃO VAI NO PROMPT COMO ALVO

    Sem isso o modelo redigiria outra petição inicial — o material é o mesmo, e é
    o pedido que muda. O título e os pedidos que a análise sugeriu entram como o
    que esta peça deve postular, e o resto do contexto (identidade do reclamante,
    entrevista, documentos, achados) é o mesmo de `_montar_contexto`.
    """
    titulo = (titulo or "").strip()
    if not titulo:
        raise ErroPeticao("Diga qual peça deve ser redigida.")

    peca_id = id_da_anexa(caso_id, titulo)
    existentes = {linha["id"] for linha in armazenamento.listar_peticoes_anexas(caso_id)}
    if peca_id not in existentes and len(existentes) >= MAX_ANEXAS_POR_CASO:
        raise ErroPeticao(
            f"Este caso já tem {MAX_ANEXAS_POR_CASO} peças além da petição inicial. "
            "Baixe e apague uma antes de redigir outra."
        )

    contexto = _montar_contexto(caso_id, texto_entrevista)
    alvo = [f"PEÇA A REDIGIR: {titulo}"]
    if motivo.strip():
        alvo.append(f"POR QUE ELA CABE NESTE CASO: {motivo.strip()}")
    if pedidos:
        alvo.append("PEDIDOS QUE A ANÁLISE APONTOU: " + "; ".join(p for p in pedidos if p))

    saida = _llm_json(
        _com_skill_do_escritorio(
            caso_id,
            """Você é advogado trabalhista e vai redigir UMA peça específica, indicada
em "PEÇA A REDIGIR", usando o material do caso (entrevista, documentos, achados).

Esta NÃO é a petição inicial do caso — ela já existe. Redija a peça pedida, com os
pedidos próprios dela. Se o material não sustentar a peça, diga isso em `pendencias`
e escreva o que for possível com [PENDENTE: explicação] no que faltar.

Use SOMENTE fatos da entrevista e dos documentos — não invente. A qualificação do
autor sai do bloco IDENTIDADE DO RECLAMANTE, nunca de nome citado na conversa.

JSON:
{
  "secoes": [
    {"code":"HEADING","label":"Endereçamento e qualificação","content":"..."},
    {"code":"FACTS","label":"Dos fatos","content":"..."},
    {"code":"LEGAL_GROUNDS","label":"Do direito","content":"..."},
    {"code":"CLAIMS","label":"Dos pedidos","content":"..."},
    {"code":"EVIDENCE","label":"Das provas","content":"..."},
    {"code":"VALUE","label":"Do valor da causa","content":"..."},
    {"code":"CLOSING","label":"Fechamento","content":"..."}
  ],
  "pendencias": ["o que falta para esta peça em particular"]
}
Cada content em parágrafos separados por linha em branco.""",
        ),
        "\n".join(alvo) + "\n\n" + contexto,
        timeout=240.0,
    )

    secoes = _normalizar_secoes(saida.get("secoes") or [])
    if not any(secao["content"] for secao in secoes):
        raise ErroPeticao("O modelo não devolveu texto desta peça.")

    agora = _agora()
    dados = {
        "id": peca_id,
        "document_type": "ADDITIONAL_CLAIM",
        "title": titulo,
        "motivo": motivo.strip(),
        "created_at": agora,
        "updated_at": agora,
        "sections": secoes,
        "pendencias": [str(p) for p in saida.get("pendencias") or [] if str(p).strip()],
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    }
    armazenamento.salvar_peticao_anexa(
        caso_id,
        peca_id,
        titulo=titulo,
        motivo=motivo,
        dados=dados,
        docx=montar_docx(secoes),
        gerada_por=gerada_por,
    )
    return {
        "id": peca_id,
        "titulo": titulo,
        "motivo": motivo.strip(),
        "pendencias": dados["pendencias"],
        "secoes": len(secoes),
        "criado_em": agora,
        "atualizado_em": agora,
        "gerada_por": gerada_por,
    }


def ler_docx_anexa(peca_id: str) -> tuple[str, bytes]:
    """Título e .docx de uma peça anexa, para o download."""
    registro = armazenamento.obter_peticao_anexa(peca_id)
    if not registro:
        raise ErroPeticao("Peça não encontrada.")
    conteudo = bytes(registro.get("_docx") or b"")
    if not conteudo:
        # Regrava a partir do JSON: o texto é a verdade, o binário é derivado.
        conteudo = montar_docx((registro.get("dados") or {}).get("sections") or [])
    return str(registro.get("titulo") or "Peça"), conteudo


def ler_pdf_anexa(peca_id: str) -> tuple[str, bytes]:
    from . import docx_pdf

    titulo, docx = ler_docx_anexa(peca_id)
    try:
        return titulo, docx_pdf.converter(docx)
    except docx_pdf.ErroConversaoDocx as erro:
        raise ErroPeticao(str(erro)) from erro


def _revisar_secoes_via_llm(
    caso_id: str, secoes_atuais: list[dict[str, Any]], prompt_critica: str
) -> list[dict[str, Any]]:
    """O miolo da revisão por prompt: aplica a crítica sobre as seções atuais.

    Compartilhado entre `revisar_com_prompt` (a petição inicial, com versão,
    histórico e crítica registrada) e `revisar_anexa_com_prompt` (as outras
    peças, sem nada disso — ver o cabeçalho de `armazenamento.salvar_peticao_anexa`
    sobre por que elas não têm histórico). O que os dois merecem por igual é a
    MESMA qualidade de revisão: mesmo prompt, mesmo cuidado de preservar o texto
    que a crítica não pediu para mudar.
    """
    minuta_atual = "\n\n".join(
        f"### {s.get('label', s.get('code'))}\n{s.get('content', '')}"
        for s in secoes_atuais
    )

    saida = _llm_json(
        _com_skill_do_escritorio(
            caso_id,
            """Você é advogado trabalhista revisando uma peça já redigida.
Aplique a CRÍTICA do advogado sobre a MINUTA ATUAL. Mude SOMENTE o que a crítica pede;
preserve o restante do texto tal como está, palavra por palavra onde a crítica não manda
mexer. Não invente fatos novos que não estejam na minuta atual. Devolva as SETE seções
completas, mesmo as que não mudaram. JSON:
{
  "secoes": [
    {"code": "HEADING", "label": "Endereçamento e qualificação", "content": "..."},
    {"code": "FACTS", "label": "Dos fatos", "content": "..."},
    {"code": "LEGAL_GROUNDS", "label": "Do direito", "content": "..."},
    {"code": "CLAIMS", "label": "Dos pedidos", "content": "..."},
    {"code": "EVIDENCE", "label": "Das provas", "content": "..."},
    {"code": "VALUE", "label": "Do valor da causa", "content": "..."},
    {"code": "CLOSING", "label": "Fechamento", "content": "..."}
  ]
}
Cada content em parágrafos separados por linha em branco.""",
        ),
        f"MINUTA ATUAL:\n{minuta_atual}\n\nCRÍTICA DO ADVOGADO:\n{prompt_critica}",
        timeout=240.0,
    )
    secoes = _normalizar_secoes(saida.get("secoes") or [])
    if not any(secao["content"] for secao in secoes):
        raise ErroPeticao("O modelo não devolveu texto da peça revisada.")
    return secoes


def revisar_anexa_com_prompt(peca_id: str, *, prompt_critica: str) -> dict[str, Any]:
    """Reescreve uma peça anexa a partir de uma crítica em linguagem natural.

    Mesmo recurso que `revisar_com_prompt` oferece à petição inicial — a
    diferença é que a peça anexa não versiona nem guarda a crítica em
    `peticao_criticas` (ela já não tem histórico nenhum, nem para "gerar de
    novo"; ver `armazenamento.salvar_peticao_anexa`). A revisão sobrescreve o
    texto atual da peça, e é isso que a tela avisa antes de aplicar.
    """
    prompt_critica = prompt_critica.strip()
    if not prompt_critica:
        raise ErroPeticao("Escreva o que deve mudar nesta peça.")

    registro = armazenamento.obter_peticao_anexa(peca_id)
    if not registro:
        raise ErroPeticao("Peça não encontrada.")

    dados = dict(registro["dados"])
    secoes_atuais = dados.get("sections") or []
    if not secoes_atuais:
        raise ErroPeticao("Esta peça não tem seções para revisar.")

    secoes = _revisar_secoes_via_llm(registro["caso_id"], secoes_atuais, prompt_critica)
    dados["sections"] = secoes
    dados["updated_at"] = _agora()

    armazenamento.salvar_peticao_anexa(
        registro["caso_id"],
        peca_id,
        titulo=str(registro.get("titulo") or dados.get("title") or ""),
        motivo=str(registro.get("motivo") or ""),
        dados=dados,
        docx=montar_docx(secoes),
        gerada_por=str(registro.get("gerada_por") or ""),
    )
    return para_api(dados)


def revisar_com_prompt(
    caso_id: str, *, prompt_critica: str, usuario: str, generaliza: bool = True
) -> dict[str, Any]:
    """Reescreve a petição a partir de uma crítica em linguagem natural.

    Issue "Permitir alteração da petição por prompt com rastreabilidade":
    advogado ou gestor descreve o que quer mudar ("os pedidos estão fracos,
    separe dano moral do material") e o sistema aplica sobre a petição ATUAL —
    não gera do zero, então o que já estava bom continua igual.

    Três coisas ficam registradas, em ordem:

    1. A versão anterior vai para `peticao_versoes` **antes** de ser
       sobrescrita — rastreabilidade por caso, requisito da issue.
    2. A crítica em si vai para `peticao_criticas`, com quem pediu e em cima de
       qual versão — o "log" e a "instrução armazenada" que a issue pede, e
       também o que alimenta a retroalimentação automática entre casos (ver
       `_com_skill_do_escritorio`). Com `generaliza=False` ela fica só na
       rastreabilidade deste caso e NÃO instrui as próximas petições: é o que
       impede um "troque o nome do cliente" de virar regra da categoria.
    3. A nova versão volta **sempre** para `IN_REVIEW`, mesmo que a anterior já
       estivesse `APPROVED` — decisão do escritório: revisão por prompt nunca
       substitui uma versão aprovada sem passar de novo pela aprovação humana.
    """
    prompt_critica = prompt_critica.strip()
    if not prompt_critica:
        raise ErroPeticao("Escreva o que deve mudar na petição.")

    atual = carregar(caso_id)
    if not atual:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")

    secoes_atuais = [
        s for s in atual.get("sections") or [] if s.get("code") != "JURIMETRY"
    ]
    if not secoes_atuais:
        raise ErroPeticao("Esta petição não tem seções para revisar.")

    secoes = _revisar_secoes_via_llm(caso_id, secoes_atuais, prompt_critica)

    # 1) snapshot da versão anterior — antes de sobrescrever.
    armazenamento.registrar_versao_peticao(caso_id, atual)

    versao_origem = int(atual.get("version") or 1)
    versao_resultado = versao_origem + 1
    novos_dados = {
        **atual,
        "version": versao_resultado,
        "status": "IN_REVIEW",
        "sections": secoes,
    }
    _salvar(caso_id, novos_dados)

    # 2) a crítica em si — log + instrução armazenada + insumo da retroalimentação.
    try:
        peticao_criticas.inicializar()
        peticao_criticas.registrar(
            caso_id=caso_id,
            categoria=_categoria_do_caso(caso_id),
            versao_origem=versao_origem,
            versao_resultado=versao_resultado,
            prompt=prompt_critica,
            usuario=usuario,
            generaliza=generaliza,
        )
    except Exception:
        # A revisão já foi salva — perder o registro da crítica é ruim, mas não pode
        # desfazer o trabalho do advogado por uma oscilação do pgvector. Fica no log
        # do servidor; quem ler a rastreabilidade do caso vai notar a lacuna.
        log.exception("crítica de petição não pôde ser registrada (caso %s)", caso_id)

    return novos_dados


def historico_de_criticas(caso_id: str) -> list[dict[str, Any]]:
    """A rastreabilidade que a issue pede: cada crítica deste caso, quem pediu, quando."""
    try:
        peticao_criticas.inicializar()
        return peticao_criticas.listar_por_caso(caso_id)
    except Exception:
        log.warning("histórico de críticas indisponível (caso %s)", caso_id, exc_info=True)
        return []


def historico_de_versoes(caso_id: str) -> list[dict[str, Any]]:
    """As versões anteriores desta petição — o que ela era antes de cada revisão."""
    return armazenamento.listar_versoes_peticao(caso_id)


def salvar_secoes(caso_id: str, secoes: list[dict[str, str]]) -> dict[str, Any]:
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    por_codigo = {s["code"]: s.get("content", "") for s in secoes if s.get("code")}
    dados["sections"] = [
        secao
        for secao in dados.get("sections") or []
        if secao.get("code") != "JURIMETRY"
    ]
    for secao in dados["sections"]:
        if secao["code"] in por_codigo:
            secao["content"] = por_codigo[secao["code"]]
    return _salvar(caso_id, dados)


def atualizar_status(caso_id: str, *, status: str) -> dict[str, Any]:
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    dados["status"] = status
    return _salvar(caso_id, dados)


def para_api(dados: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": dados.get("id", ID_LOCAL),
        "document_type": dados.get("document_type", "INITIAL_PETITION"),
        "status": dados.get("status", "IN_REVIEW"),
        "version": dados.get("version", 1),
        "title": dados.get("title", "Petição inicial"),
        "readiness": dados.get("readiness") or {},
        "review": dados.get("review") or {},
        "jurimetria": dados.get("jurimetria") or {},
        "blocking_findings": dados.get("blocking_findings", 0),
        "model": dados.get("model"),
        "created_at": dados.get("created_at", _agora()),
        "sections": [
            secao
            for secao in dados.get("sections") or []
            if secao.get("code") != "JURIMETRY"
        ],
    }


def progresso(caso_id: str, desde: str) -> dict[str, Any]:
    dados = carregar(caso_id)
    if not dados:
        return {
            "status": "RUNNING",
            "completed_steps": 0,
            "generation_id": None,
            "blocking_findings": 0,
        }
    criado = str(dados.get("updated_at") or dados.get("created_at") or "")
    if criado and criado >= desde:
        return {
            "status": "DONE",
            "completed_steps": len(dados.get("sections") or []),
            "generation_id": ID_LOCAL,
            "blocking_findings": dados.get("blocking_findings", 0),
        }
    return {
        "status": "RUNNING",
        "completed_steps": 0,
        "generation_id": None,
        "blocking_findings": 0,
    }


def _paragrafo_xml(texto: str, *, negrito: bool = False) -> str:
    linhas = texto.split("\n")
    partes: list[str] = []
    for linha in linhas:
        if not linha.strip():
            partes.append("<w:p/>")
            continue
        texto_xml = escape(linha)
        if negrito:
            partes.append(
                f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
                f'<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{texto_xml}</w:t></w:r></w:p>'
            )
        else:
            partes.append(
                f'<w:p><w:r><w:t xml:space="preserve">{texto_xml}</w:t></w:r></w:p>'
            )
    return "".join(partes)


def montar_docx(secoes: list[dict[str, Any]]) -> bytes:
    logo, fonte, logo_extensao, _origem_visual = identidade_visual()
    fonte_xml = escape(fonte, {'"': "&quot;"})
    logo_arquivo = f"logo-escritorio{logo_extensao}"
    logo_content_type = "image/jpeg" if logo_extensao == ".jpg" else "image/png"
    corpo: list[str] = []
    for secao in secoes:
        if secao.get("code") == "JURIMETRY":
            continue
        rotulo = str(secao.get("label") or secao.get("code") or "").strip()
        conteudo = str(secao.get("content") or "").strip()
        if rotulo and secao.get("code") not in ("HEADING",):
            corpo.append(_paragrafo_xml(rotulo.upper(), negrito=True))
        if conteudo:
            corpo.append(_paragrafo_xml(conteudo))
        corpo.append("<w:p/>")

    documento_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {"".join(corpo)}
    <w:sectPr>
      <w:headerReference w:type="default" r:id="rIdHeader"/>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1985" w:right="1417" w:bottom="1417" w:left="1701" w:header="360"/>
    </w:sectPr>
  </w:body>
</w:document>"""

    cabecalho_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing>
    <wp:inline distT="0" distB="0" distL="0" distR="0">
      <wp:extent cx="1600200" cy="905010"/><wp:docPr id="1" name="Logo do escritório"/>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="logo-escritorio"/><pic:cNvPicPr/></pic:nvPicPr>
          <pic:blipFill><a:blip r:embed="rIdLogo"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
          <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1600200" cy="905010"/></a:xfrm>
            <a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
        </pic:pic>
      </a:graphicData></a:graphic>
    </wp:inline>
  </w:drawing></w:r></w:p>
</w:hdr>"""

    estilos_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault><w:rPr>
      <w:rFonts w:ascii="{fonte_xml}" w:hAnsi="{fonte_xml}" w:eastAsia="{fonte_xml}" w:cs="{fonte_xml}"/>
      <w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="pt-BR"/>
    </w:rPr></w:rPrDefault>
    <w:pPrDefault><w:pPr><w:jc w:val="both"/><w:spacing w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as arquivo:
        arquivo.writestr(
            "[Content_Types].xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="{logo_extensao.lstrip('.')}" ContentType="{logo_content_type}"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>""",
        )
        arquivo.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        arquivo.writestr("word/document.xml", documento_xml)
        arquivo.writestr("word/header1.xml", cabecalho_xml)
        arquivo.writestr("word/styles.xml", estilos_xml)
        arquivo.writestr(f"word/media/{logo_arquivo}", logo)
        arquivo.writestr(
            "word/_rels/document.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""",
        )
        arquivo.writestr(
            "word/_rels/header1.xml.rels",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdLogo" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{logo_arquivo}"/>
</Relationships>""",
        )
    return buffer.getvalue()


def ler_docx(caso_id: str) -> bytes:
    dados = armazenamento.obter_peticao_local(caso_id)
    if not dados:
        raise ErroPeticao("Petição não encontrada.")
    conteudo = bytes(dados.get("_docx") or b"")
    if int(dados.get("docx_style_version") or 0) < DOCX_STYLE_VERSION:
        return montar_docx(dados.get("sections") or [])
    return conteudo or montar_docx(dados.get("sections") or [])


def ler_pdf(caso_id: str) -> bytes:
    from . import docx_pdf

    try:
        return docx_pdf.converter(ler_docx(caso_id))
    except docx_pdf.ErroConversaoDocx as erro:
        raise ErroPeticao(str(erro)) from erro
