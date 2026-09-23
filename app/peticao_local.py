"""Petição inicial gerada no Acervo — entrevista + OCR, sem agente."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import unicodedata
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from xml.etree import ElementTree

import httpx

from . import (
    analise_documentos,
    armazenamento,
    conferencia_peticao,
    jurimetria_caso,
    peticao_aprendizado,
    peticao_criticas,
    peticao_skills,
    rag,
)
from . import casos as casos_ocr

log = logging.getLogger("peticao_local")

ID_LOCAL = "local"
#: Sobe a cada mudança no LAYOUT do .docx. `ler_docx` regrava o binário quando a
#: versão salva é menor (ver o fim do módulo): sem incrementar aqui, as petições
#: já geradas continuariam saindo com o layout antigo, e a mudança pareceria não
#: ter surtido efeito justamente em quem já tem peça no sistema.
#:
#: 5 — layout medido na petição de referência do escritório (Auxílio-Acidente,
#: 8 páginas): corpo serifado, margens 3,0 / 1,89 cm e texto começando em 4,66 cm,
#: abaixo do timbre.
#: 6 — recuo de 1,25 cm na primeira linha de cada parágrafo, medido na mesma
#: peça de referência (corpo em 3,0 cm, primeira linha em 4,25 cm), e negrito
#: inline no nome do autor.
#: 10 — formatação vinda do editor da tela (itálico, sublinhado, tamanho, cor e
#: alinhamento por parágrafo) interpretada no .docx.
DOCX_STYLE_VERSION = 10
LOGO_LARA_MELO = Path(__file__).with_name("assets") / "lara-melo-logo.png"
#: Fonte usada quando o escritório ainda não subiu um modelo visual próprio.
#:
#: Era "Arial". A petição de referência é composta em LiberationSerif — a métrica
#: livre equivalente à Times New Roman —, e peça jurídica saindo em fonte sem
#: serifa destoava do que o escritório protocola. Quem sobe um modelo continua
#: mandando na fonte: este valor só vale na ausência dele.
FONTE_PADRAO = "Times New Roman"
MODELO_VISUAL_GERAL = "peticao_visual_geral"
MODELO_VISUAL_CONFIG = "peticao_visual_config"
MODELO_VISUAL_LOGO = "peticao_visual_logo"
CONFIGURACAO_VISUAL_PADRAO: dict[str, Any] = {
    "fonte": "",
    "tamanho_fonte_pt": 12,
    "espacamento_linha": 1.5,
    "recuo_primeira_linha_cm": 1.25,
    "margem_superior_cm": 3.74,
    "margem_direita_cm": 1.89,
    "margem_inferior_cm": 1.25,
    "margem_esquerda_cm": 3.0,
    "alinhamento_corpo": "justificado",
    "alinhamento_titulos": "esquerda",
    "altura_logo_cm": 2.36,
    "preferir_tabelas": False,
}
SECOES_PADRAO = (
    ("HEADING", "Endereçamento e qualificação"),
    # As preliminares saíram de dentro do DO DIREITO e viraram seção própria,
    # ANTES dos fatos — que é onde o escritório as põe. `_normalizar_secoes`
    # percorre esta tupla na ordem, então basta a posição aqui para a peça
    # inteira (prompt, tela, .docx e revisão) passar a respeitá-la.
    ("PRELIMINARY", "Das preliminares"),
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

            # Reserva de quando o .docx enviado não declara `rFonts`: cai no mesmo
            # padrão serifado do resto do sistema, e não mais em Arial.
            fonte = FONTE_PADRAO
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


def extrair_fonte_visual(conteudo: bytes) -> str:
    """Lê a fonte mesmo quando o arquivo de referência não traz uma logo."""
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
            if "word/styles.xml" not in arquivo.namelist():
                return FONTE_PADRAO
            raiz = ElementTree.fromstring(arquivo.read("word/styles.xml"))
            for fontes in raiz.iter(f"{_NS_W}rFonts"):
                fonte = fontes.attrib.get(f"{_NS_W}ascii") or fontes.attrib.get(f"{_NS_W}hAnsi")
                if fonte and len(fonte) <= 80:
                    return fonte
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError):
        pass
    return FONTE_PADRAO


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
                tabelas = list(doc.iter(f"{_NS_W}tbl"))
                if tabelas:
                    colunas = []
                    for tabela in tabelas:
                        primeira_linha = next(iter(tabela.iter(f"{_NS_W}tr")), None)
                        if primeira_linha is not None:
                            colunas.append(len(list(primeira_linha.iter(f"{_NS_W}tc"))))
                    atributos["tabelas"] = {
                        "quantidade": len(tabelas),
                        "colunas_detectadas": sorted({n for n in colunas if n}),
                    }
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
    logo_separada = armazenamento.obter_modelo(MODELO_VISUAL_LOGO)
    if logo_separada:
        extensao = Path(str(logo_separada["nome_arquivo"])).suffix.lower()
        extensao = ".jpg" if extensao in {".jpg", ".jpeg"} else ".png"
        fonte = extrair_fonte_visual(registro["conteudo"]) if registro else FONTE_PADRAO
        return bytes(logo_separada["conteudo"]), fonte, extensao, logo_separada["nome_arquivo"]
    if registro:
        try:
            logo, fonte, extensao = extrair_identidade_visual(registro["conteudo"])
            return logo, fonte, extensao, registro["nome_arquivo"]
        except ErroPeticao:
            return LOGO_LARA_MELO.read_bytes(), extrair_fonte_visual(registro["conteudo"]), ".png", "Logo padrão"
    return LOGO_LARA_MELO.read_bytes(), FONTE_PADRAO, ".png", "Padrão Lara & Melo"


def configuracao_visual() -> dict[str, Any]:
    """Preferências visuais editáveis, com limites seguros para gerar DOCX válido."""
    configuracao = dict(CONFIGURACAO_VISUAL_PADRAO)
    try:
        registro = armazenamento.obter_modelo(MODELO_VISUAL_CONFIG)
        if registro:
            recebida = json.loads(bytes(registro["conteudo"]).decode("utf-8"))
            if isinstance(recebida, dict):
                configuracao.update({k: v for k, v in recebida.items() if k in configuracao})
    except Exception:
        log.warning("configuração visual indisponível; usando padrão", exc_info=True)
    for campo in ("tamanho_fonte_pt", "espacamento_linha", "recuo_primeira_linha_cm", "margem_superior_cm", "margem_direita_cm", "margem_inferior_cm", "margem_esquerda_cm", "altura_logo_cm"):
        try:
            configuracao[campo] = float(configuracao[campo])
        except (TypeError, ValueError):
            configuracao[campo] = CONFIGURACAO_VISUAL_PADRAO[campo]
    return configuracao


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


#: Teto de saída do modelo, em tokens.
#:
#: NÃO estava definido, e era ESTE o motivo real das peças curtas. Sem o campo, a
#: DeepSeek aplica o padrão dela (4096 tokens), e nenhuma instrução de "escreva
#: mais" vence um corte no transporte: o prompt podia pedir quatro parágrafos por
#: tese e doze julgados que a resposta parava no mesmo tamanho. A mediana do
#: acervo do escritório é de 144 parágrafos por peça — não cabe em 4096.
#:
#: E 8192 também não coube (18/09): a revisão devolve a peça INTEIRA em JSON, e numa
#: inicial de 23 mil caracteres com uma seção nova pedida pelo chat a resposta
#: parou em exatos 8192 tokens, no meio dos pedidos. JSON sem fechar virava "o
#: modelo não respondeu" — três vezes seguidas no mesmo caso. Por isso 100000 (a
#: API aceita até 393216, medido). Omitir o campo NÃO serve — volta ao padrão de 4096.
MAX_TOKENS_RESPOSTA = int(os.getenv("PETICAO_MAX_TOKENS", "100000"))


def _llm_json(
    instrucao: str, entrada: str, *, timeout: float = 180.0
) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroPeticao("DEEPSEEK_API_KEY ausente — configure no .env.")
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    modelo = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    # Duas tentativas, não uma: um pedido grande — criar um tópico novo reescreve
    # a peça inteira — já leva dezenas de segundos, e um timeout de rede isolado
    # (a resposta estava a caminho, a conexão caiu) derrubava o pedido inteiro na
    # hora, sem tentar de novo. Quem lia via "o modelo não respondeu" depois de
    # já ter esperado o tempo todo — e tinha de repetir o pedido do zero. Não
    # cobre o corte por tamanho (`finish_reason == "length"`): repetir um pedido
    # que já estourou o teto falharia do mesmo jeito, então esse caso sai direto
    # com a mensagem própria, sem consumir a segunda tentativa.
    ultimo_erro: Exception | None = None
    for tentativa in (1, 2):
        try:
            resposta = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {chave}"},
                json={
                    "model": modelo,
                    "temperature": 0.2,
                    "max_tokens": MAX_TOKENS_RESPOSTA,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": instrucao},
                        {"role": "user", "content": entrada[:120_000]},
                    ],
                },
                timeout=timeout,
            )
            resposta.raise_for_status()
            escolha = resposta.json()["choices"][0]
            conteudo = escolha["message"]["content"]
            if escolha.get("finish_reason") == "length":
                # Cortado pelo teto de saída: o JSON chega sem fechar. Dizer "não
                # respondeu" mandava tentar de novo um pedido que falha igual.
                log.warning(
                    "petição local: resposta cortada no teto de %s tokens", MAX_TOKENS_RESPOSTA
                )
                raise ErroPeticao(
                    "A resposta do modelo passou do tamanho máximo e foi cortada. Peça a"
                    " alteração em partes menores."
                )
            saida = json.loads(conteudo)
        except ErroPeticao:
            raise
        # `IndexError` e `TypeError` não estavam aqui, e é justamente o que um
        # provedor devolve quando filtra a resposta: HTTP 200 com `choices: []`. O
        # erro subia cru e a tela mostrava 500 sem dizer nada ao advogado, que ficava
        # sem saber se devia tentar de novo — e devia.
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError) as erro:
            ultimo_erro = erro
            log.warning(
                "petição local: LLM falhou (tentativa %s/2): %s", tentativa, erro
            )
            continue
        if not isinstance(saida, dict):
            # JSON válido que não é objeto (uma lista, um número) quebraria adiante,
            # no `.get` de quem chamou, longe daqui.
            log.warning("petição local: LLM devolveu %s em vez de objeto", type(saida).__name__)
            ultimo_erro = None
            break
        return saida

    if ultimo_erro is not None:
        raise ErroPeticao("O modelo não respondeu — tente de novo.") from ultimo_erro
    raise ErroPeticao("O modelo não respondeu no formato esperado — tente de novo.")


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


def _com_skill_do_escritorio(caso_id: str, instrucao: str, *, revisao: bool = False) -> str:
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
    # A orientação GERAL vem primeiro; a da categoria, se existir, complementa.
    #
    # A configuração da tela passou a ser única (ver `peticao_skills.CATEGORIA_GERAL`):
    # o que o escritório ensina sobre como redigir não muda com o tipo da ação, e
    # manter uma cópia por categoria obrigava a reescrever a mesma instrução cinco
    # vezes — e a lembrar de atualizar as cinco.
    #
    # As skills já escritas por categoria continuam sendo LIDAS de propósito.
    # Parar de lê-las sumiria em silêncio com o que o escritório já tinha
    # ensinado: não haveria aviso na tela, e o sintoma apareceria semanas depois,
    # como petição saindo diferente sem ninguém saber por quê.
    skill = "\n\n".join(
        parte
        for parte in (
            peticao_skills.instrucoes_gerais().strip(),
            peticao_skills.instrucoes_da_categoria(categoria).strip(),
        )
        if parte
    )
    regras = peticao_aprendizado.regras_para_contexto(categoria=categoria)
    try:
        # Compatibilidade com as correções históricas anteriores ao aprendizado
        # estruturado. Assim que existirem regras ativas, histórico cru não entra
        # no prompt: uma lista de comentários não é uma base de conhecimento.
        criticas = []
        if not regras:
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
        cabecalho = (
            "=== ORIENTAÇÃO DO ESCRITÓRIO PARA ESTA CATEGORIA DE CASO (padrão de redação do trecho que for alterado) ===\n"
            if revisao
            else "=== ORIENTAÇÃO DO ESCRITÓRIO PARA ESTA CATEGORIA DE CASO ===\n"
        )
        blocos.append(cabecalho + skill)
    if regras:
        listadas = "\n".join(
            f"- [{r.get('tipo', 'PREFERENCE')}; confiança {float(r.get('confidence') or 0):.2f}; "
            f"{int(r.get('observacoes') or 0)} confirmação(ões)] {r.get('texto', '')}"
            for r in regras
        )
        if revisao:
            blocos.append(
                "=== REGRAS APRENDIDAS ATIVAS DO ESCRITÓRIO (referência contextual) ===\n"
                + listadas
                + "\nA crítica atual prevalece; não use regra aprendida para alterar seção não pedida."
            )
        else:
            blocos.append(
                "=== REGRAS APRENDIDAS ATIVAS DO ESCRITÓRIO ===\n"
                + listadas
                + "\nAplique apenas quando compatíveis com os fatos, a área e este tipo de peça."
            )
    if criticas:
        listadas = "\n".join(f"- {c}" for c in criticas)
        if revisao:
            blocos.append(
                "=== CORREÇÕES JÁ PEDIDAS EM PETIÇÕES DESTA CATEGORIA (somente referência) ===\n"
                f"{listadas}\n"
                "Nesta revisão NÃO aplique estas correções por conta própria: elas só orientam "
                "a redação do trecho que a CRÍTICA DO ADVOGADO mandar mudar."
            )
        else:
            blocos.append(
                "=== CORREÇÕES QUE O ESCRITÓRIO JÁ PEDIU EM PETIÇÕES DESTA CATEGORIA ===\n"
                f"{listadas}\n"
                "Aplique estas correções diretamente, sem repetir o erro que motivou cada uma."
            )
    if bool(configuracao_visual().get("preferir_tabelas")):
        blocos.append(
            "=== PREFERÊNCIA VISUAL DO ESCRITÓRIO ===\n"
            "Os modelos de referência usam tabelas. Quando houver dados comprovados "
            "naturalmente estruturados (cronologia, contrato, valores, documentos ou "
            "histórico médico), prefira uma tabela Markdown no ponto apropriado. Isso "
            "é preferência, não obrigação; não crie tabela sem utilidade nem invente células."
        )
    if len(blocos) == 1:
        return instrucao
    if revisao:
        blocos.append(
            "A CRÍTICA DO ADVOGADO tem prioridade sobre tudo acima: o que ela não pede não muda. "
            "Responda no formato pedido."
        )
    else:
        blocos.append("Aplique o que vier acima sem contrariar o formato de resposta pedido.")
    return "\n\n".join(blocos)


def documentos_ocr(caso_id: str) -> list[dict[str, str]]:
    """O texto de OCR de cada anexo, em UMA consulta (ver `_documentos_do_caso`).

    Pública porque o chat da petição (`agente/chat_peticao.py`) lê os mesmos anexos
    para responder "o que o laudo diz?". Duas leituras do mesmo OCR divergiriam no
    dia em que uma delas passasse a cortar o texto noutro ponto.

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


def anexos_do_caso(caso_id: str) -> list[dict[str, Any]]:
    """TODOS os anexos do caso, lidos ou não, com o que o OCR já organizou.

    `documentos_ocr` serve à geração: só o texto, e só de quem tem texto. O chat da
    petição precisa de mais, e a falta disso foi medida numa reclamação real: o
    advogado pediu o número de um documento que estava no caso, o chat procurou pelo
    NOME do arquivo (`IMG_….jpg`), não achou, e afirmou que o documento não existia —
    porque o anexo sem texto sumia da lista e o prompt dizia que o que não está na
    lista não existe.

    Aqui vai cada entrega com o tipo classificado ("CTPS", "RG"), os campos já
    extraídos (número, série, data) e a situação da leitura (`lido`, `na_fila`,
    `processando`, `erro`, `sem_texto`). O texto vai INTEIRO: quem busca precisa achar
    o número no fim do documento, e o corte é feito por quem mostra o trecho.
    Duas consultas, como `documentos_ocr` — não uma por arquivo.
    """
    extracoes = {e["id"]: e.get("extracao") or {} for e in armazenamento.listar_extracoes_do_caso(caso_id)}
    anexos: list[dict[str, Any]] = []
    for entrega in armazenamento.listar_entregas(caso_id):
        extracao = extracoes.get(str(entrega.get("id"))) or {}
        texto = str(extracao.get("texto_completo") or "").strip()
        tipo = extracao.get("tipo") if isinstance(extracao.get("tipo"), dict) else {}
        semantica = extracao.get("classificacao_semantica")
        semantica = semantica if isinstance(semantica, dict) else {}
        # O tipo determinístico só reconhece documento de identidade e comprovante;
        # para o resto ele devolve "Documento não identificado" e quem sabe o que o
        # anexo é, é a leitura semântica. Medido no caso-gabarito: 6 de 8 anexos
        # chegavam ao chat como "não identificado" com a semântica certa ao lado.
        candidatos = (
            tipo.get("descricao") if str(tipo.get("codigo") or "") not in ("", "desconhecido") else "",
            semantica.get("documento"),
            entrega.get("identificacao_ia"),
            tipo.get("descricao"),
            entrega.get("tipo_detectado"),
        )
        descricao = next(
            (
                str(c).strip()
                for c in candidatos
                if str(c or "").strip()
                and str(c).strip().lower() not in ("desconhecido", "documento não identificado", "indefinido")
            ),
            "",
        )
        campos = [
            {"rotulo": str(c.get("rotulo") or c.get("nome") or ""), "valor": str(c.get("valor") or "")}
            for c in (extracao.get("campos") or [])
            if isinstance(c, dict) and str(c.get("valor") or "").strip()
        ]
        status = str(entrega.get("status_proc") or "").lower()
        if texto:
            situacao = "lido"
        elif status in ("na_fila", "processando", "erro"):
            situacao = status
        else:
            situacao = "sem_texto"
        anexos.append(
            {
                "id": str(entrega.get("id") or ""),
                "arquivo": str(entrega.get("arquivo") or ""),
                "tipo": descricao,
                "campos": campos,
                "texto": texto,
                "situacao": situacao,
            }
        )
    return anexos


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

    documentos = documentos_ocr(caso_id)
    if documentos:
        linhas.append("\n=== DOCUMENTOS (texto extraído por OCR) ===")
        for numero, doc in enumerate(documentos[:20], 1):
            linhas.append(f"\n--- DOCUMENTO {numero:02d}: {doc['arquivo']} ---\n{doc['texto']}")

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
            """Você é advogado. Cruze a ENTREVISTA com os DOCUMENTOS (OCR) e identifique
a natureza jurídica mais adequada aos fatos, sem presumir relação de trabalho.
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


def _normalizar_secoes_da_revisao(brutas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normaliza a peça candidata sem impor as oito seções da geração inicial."""
    resultado: list[dict[str, Any]] = []
    usados: set[str] = set()
    for indice, item in enumerate(brutas):
        if not isinstance(item, dict):
            continue
        conteudo = str(item.get("content") or item.get("texto") or "").strip()
        if not conteudo:
            continue
        base = re.sub(r"[^A-Z0-9_]+", "_", str(item.get("code") or item.get("label") or "SECAO").upper()).strip("_")
        codigo = base[:48] or "SECAO"
        if codigo in usados:
            codigo = f"{codigo[:42]}_{indice + 1}"
        usados.add(codigo)
        resultado.append({
            "code": codigo,
            "label": str(item.get("label") or codigo.replace("_", " ").title()).strip(),
            "content": conteudo,
            "written_by": "agent",
            "supporting_fact_ids": [],
            "cited_precedent_ids": [],
        })
    return resultado


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
        # O TIPO do erro vai para o log, e não só a mensagem: "timeout de
        # conexão" e "senha recusada" apareciam iguais aqui, e mandavam procurar
        # o problema em lugares opostos (rede x credencial). A busca já tenta as
        # três camadas de jurisdição com repetição (ver `jurimetria_caso`), então
        # chegar aqui significa que nenhuma delas respondeu.
        log.warning(
            "petição local: jurimetria indisponível (%s): %s",
            type(erro).__name__,
            str(erro)[:200],
        )
        aviso = (
            "A base de processos semelhantes não respondeu durante a geração, "
            "nem no acervo nacional. Nenhum percentual ou conclusão jurimétrica "
            "foi estimado — a minuta segue válida, sem o apêndice comparativo."
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
    contexto += _precedentes_para_redigir(contexto)
    contexto += _legislacao_para_redigir(contexto)
    saida = _llm_json(
        _com_skill_do_escritorio(
            caso_id,
            CONTRATO_DE_REDACAO
            + """Redija uma PETIÇÃO INICIAL completa, adequada à natureza da ação indicada
pelos fatos e pela análise, em português formal.
Use SOMENTE fatos da entrevista e documentos — não invente.
Marque com [PENDENTE: motivo] o que depender só de alegação sem prova.

ENDEREÇAMENTO (seção HEADING): abra por "Ao Juízo ..." indicando a vara e a
comarca cabíveis — não use a fórmula "EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A)
JUIZ(A)". O nome do autor vem em NEGRITO, escrito entre asteriscos duplos, assim:
**NOME COMPLETO DO CLIENTE**, seguido da qualificação corrida.

PADRÃO DO ESCRITÓRIO: quando houver orientação ou peça de referência acima,
siga-a — ela manda sobre o critério geral. Onde ela não disser nada, escolha a
forma que julgar melhor para a peça, sem inventar fato.

TABELAS: você pode usar tabela quando ela tornar dados comprovados mais claros
(cronologia, contrato, documentos, valores ou histórico médico), ou quando o
advogado pedir. Escreva-a em Markdown, com cabeçalho e linha separadora, no
EXATO ponto do `content` em que ela deve aparecer. O sistema a converterá em
tabela nativa e editável do Word. Não simule tabela com tabs/espaços, não
invente dados para preencher célula e omita linhas sem informação comprovada.
JSON:
{
  "secoes": [
    {"code": "HEADING", "label": "Endereçamento e qualificação", "content": "..."},
    {"code": "PRELIMINARY", "label": "Das preliminares", "content": "..."},
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
        # 360s e não 240s: com o teto de saída dobrado a resposta é fisicamente
        # maior, e manter o prazo antigo trocaria "peça curta" por "o modelo não
        # respondeu" — que é pior, porque perde o trabalho inteiro.
        timeout=360.0,
    )
    secoes = _normalizar_secoes(saida.get("secoes") or [])
    if not any(s["content"] for s in secoes):
        raise ErroPeticao("O modelo não devolveu texto da petição.")
    return secoes, [str(p) for p in (saida.get("pendencias") or []) if str(p).strip()]


def _precedentes_para_redigir(contexto: str) -> str:
    """Julgados semelhantes ANTES de redigir, para a IA poder citá-los.

    A jurimetria já existia, mas rodava depois (`_analisar_jurimetria_da_minuta`,
    chamada com a minuta pronta): ela virava um apêndice auditável e NUNCA
    chegava ao prompt. Por isso o advogado pedia jurisprudência e o texto saía
    sem nenhuma — o modelo não tinha como citar o que não recebeu.

    A consulta aqui é o próprio material do caso (entrevista + documentos), e não
    a minuta, justamente porque a minuta ainda não existe neste ponto.

    Falha não interrompe a geração: sem base, a peça sai como saía antes.
    """
    try:
        similares, _jurisdicao, _uf = jurimetria_caso.buscar_focada(
            contexto[:12_000], texto_para_uf=contexto
        )
    except Exception as erro:
        log.warning("petição local: precedentes indisponíveis na redação: %s", erro)
        return ""
    if not similares:
        return ""
    # DOZE julgados, e não seis: com seis o modelo citava um ou dois e dava a
    # fundamentação por cumprida. O trecho de cada um caiu de 2200 para 1800
    # caracteres de propósito — dobrar a quantidade sem encolher o recorte
    # empurraria o prompt para perto do teto e o que entra por último é
    # justamente o que o modelo menos aproveita.
    linhas = ["\n\n=== JULGADOS SEMELHANTES (use no DO DIREITO) ==="]
    usados = list(similares[:18])
    for indice, trecho in enumerate(usados, start=1):
        ref = trecho.referencia()
        linhas.append(
            f"\n[J{indice}] processo={ref.get('processo') or ref.get('identificador')} "
            f"resultado={ref.get('resultado') or 'não informado'} "
            f"órgão={ref.get('vara') or 'não informado'}\n{trecho.texto[:1800]}"
        )
    linhas.append(
        f"\nSão {len(usados)} julgados REAIS, vindos do acervo do escritório. Use os "
        "que de fato se aplicarem a estes fatos, citados pelo número do processo e "
        "com a razão de decidir explicada — e diga em uma frase por que cada um "
        "alcança este caso. NÃO cite julgado só porque tem palavras parecidas: "
        "compare atividade, questão decidida e fundamento determinante, e reconheça "
        "a distinção quando houver. Se nenhum destes servir para um ponto, escreva "
        "[PESQUISAR PRECEDENTE ATUAL E APLICÁVEL SOBRE ESTE PONTO] em vez de forçar "
        "um precedente pouco aderente. Nunca invente processo, ementa ou número."
    )
    return "\n".join(linhas)


def _legislacao_para_redigir(contexto: str) -> str:
    """O texto legal oficial do acervo, ANTES de redigir.

    Mesmo buraco que `_precedentes_para_redigir` fechou para os julgados, e pelo
    mesmo motivo: a legislação federal está vetorizada e completa no pgvector
    (CLT com 819 trechos, CF/88, CPC, Código Civil, CPP e outras), mas NADA dela
    chegava ao prompt. A IA fundamentava de memória — e artigo citado de memória
    é artigo que sai com número errado numa peça que vai a protocolo.

    `rag.buscar_legislacao` já filtra `f.tipo='lei'`, então acórdão não entra
    aqui: julgado tem o canal dele e os dois não se misturam no prompt.

    Falha não interrompe a geração: sem base, a peça sai como saía antes.
    """
    try:
        # Mais de um núcleo jurídico costuma coexistir na mesma inicial
        # (competência, mérito, prova, consectários). Dez trechos favoreciam a
        # primeira tese e deixavam as demais com fundamentação de memória.
        trechos = rag.buscar_legislacao(contexto[:12_000], limite=14)
    except Exception as erro:
        log.warning("petição local: legislação indisponível na redação: %s", erro)
        return ""
    if not trechos:
        return ""
    linhas = ["\n\n=== LEGISLAÇÃO DO ACERVO (use no DO DIREITO) ==="]
    for indice, trecho in enumerate(trechos, start=1):
        titulo = trecho.titulo or trecho.identificador or "lei"
        linhas.append(f"\n[L{indice}] {titulo}\n{trecho.texto[:1500]}")
    linhas.append(
        f"\nSão {len(trechos)} dispositivos legais OFICIAIS do acervo do "
        "escritório. Para CADA norma que usar, identifique a espécie, número e "
        "denominação (quando houver), o artigo/parágrafo/inciso, sintetize com "
        "precisão o comando normativo e explique a consequência dele PARA ESTES "
        "fatos; uma referência solta como 'art. 927 do CC' é insuficiente. "
        "Transcreva só o excerto indispensável quando ele sustentar diretamente a "
        "tese, sem colar lei em bloco. Nunca invente número de artigo nem cite "
        "dispositivo que não esteja acima — se o que você precisa não estiver aqui, "
        "fundamente sem inventar."
    )
    return "\n".join(linhas)


def _padroes_conteudisticos_para_redigir(contexto: str) -> str:
    """Traz técnica de peças do escritório para influenciar diretamente a minuta.

    Não são fontes jurídicas nem fatos do novo caso. Entram como exemplos de
    densidade argumentativa, ordem de teses e completude de pedidos, com barreira
    explícita contra contaminação entre clientes.
    """
    try:
        trechos = rag.buscar_pecas_conteudisticas(contexto[:12_000], limite=8)
    except Exception as erro:
        log.warning("petição local: acervo de peças indisponível na redação: %s", erro)
        return ""
    if not trechos:
        return ""
    linhas = ["\n\n=== PADRÕES CONTEUDÍSTICOS DO ACERVO DO ESCRITÓRIO ==="]
    for indice, trecho in enumerate(trechos, start=1):
        classe = "peça complexa" if trecho["categoria"] == "pecas_complexas" else "peça simples"
        linhas.append(f"\n[P{indice}] referência interna ({classe}; arquivo: {trecho['arquivo']})\n{trecho['texto'][:1_000]}")
    linhas.append(
        "\nEstas referências internas servem APENAS para elevar a qualidade: aproveite a "
        "estrutura lógica, a profundidade, os contrapontos, a explicação de cada fundamento "
        "e a completude dos pedidos quando forem compatíveis com ESTE caso. NUNCA copie ou "
        "transporte nomes, CPF, endereço, empresa, datas, valores, documentos, fatos, pedido "
        "ou citação jurídica de outra referência. Toda afirmação da nova peça deve nascer do "
        "material deste caso e toda norma ou precedente deve estar no bloco oficial próprio."
    )
    return "\n".join(linhas)


# ------------------------------------------------ conferência contra os autos


def _fontes_da_conferencia(
    caso_id: str, *, texto_entrevista: str | None = None, material: str = ""
) -> conferencia_peticao.Fontes:
    """O que a peça pode afirmar: anexos, entrevista, cadastro e o material do acervo.

    `numerados` repete a numeração do bloco DOCUMENTOS de `_montar_contexto` — é por
    ela que a peça cita "Documento NN", e é contra ela que a citação é conferida.
    """
    if texto_entrevista is None:
        entrevistas = [e for e in armazenamento.listar_entrevistas(caso_id) if str(e.get("texto") or "").strip()]
        texto_entrevista = str(entrevistas[0]["texto"]) if entrevistas else ""
    caso = armazenamento.obter_caso(caso_id) or {}
    try:
        qualificacao = armazenamento.obter_qualificacao(caso_id) or {}
    except Exception:  # noqa: BLE001 — cadastro ausente só estreita as fontes
        qualificacao = {}
    return conferencia_peticao.Fontes(
        anexos=anexos_do_caso(caso_id),
        numerados=[d["arquivo"] for d in documentos_ocr(caso_id)[:20]],
        entrevista=texto_entrevista,
        cadastro=" ".join(str(v) for v in [caso.get("cliente"), *qualificacao.values()] if v),
        material=material,
    )


def _achados_da_peca(secoes: list[dict[str, Any]], violacoes: list[Any]) -> list[dict[str, Any]]:
    """Os achados de forma (`avaliar_documento`) e os da conferência, no formato da tela."""
    return [
        *(_achado_legivel(a) for a in peticao_aprendizado.avaliar_documento(secoes)),
        *conferencia_peticao.como_achados(violacoes),
    ]


def _achado_legivel(achado: dict[str, Any]) -> dict[str, Any]:
    """Achado antigo (`code`, `critic`) no formato que a tela espera.

    A tela faz `achado.category.toLowerCase()`: achado sem `category` derrubava o
    cartão inteiro da petição. Os de `avaliar_documento` nasciam assim.
    """
    if achado.get("category") and achado.get("message"):
        return achado
    codigo = str(achado.get("code") or achado.get("critic") or "AVISO")
    mensagens = {
        "MISSING_SECTION": "Seção obrigatória sem texto.",
        "FACTS_TOO_SHORT": "Os fatos estão curtos demais para sustentar os pedidos.",
        "GROUNDS_TOO_SHORT": "A fundamentação está curta demais.",
        "PENDING_INFORMATION": "A peça tem pontos marcados como [PENDENTE] para completar antes do protocolo.",
    }
    return {
        "severity": "BLOCKING" if str(achado.get("severity") or "").upper() == "BLOCKING" else "WARNING",
        "category": codigo,
        "section": str(achado.get("section") or ""),
        "message": str(achado.get("message") or mensagens.get(codigo, codigo)),
        "detail": achado.get("detail"),
    }


def _conferir_contra_os_autos(
    caso_id: str,
    secoes: list[dict[str, Any]],
    *,
    texto_entrevista: str | None = None,
    material: str = "",
    corrigir: bool = True,
) -> tuple[list[dict[str, Any]], list[Any], dict[str, Any]]:
    """Confere a peça contra os autos e, se `corrigir`, pede UMA rodada de correção.

    Devolve as seções (corrigidas e com as citações não verificadas carimbadas), as
    violações que SOBRARAM e o registro do que aconteceu, para o trace da geração.

    A correção é uma revisão com a lista exata dos defeitos — não uma nova geração —
    para não trocar um defeito conhecido por outro desconhecido. Se ela falhar ou não
    resolver, a peça sai RETIDA com os achados: nunca em silêncio.
    """
    fontes = _fontes_da_conferencia(caso_id, texto_entrevista=texto_entrevista, material=material)
    violacoes = conferencia_peticao.conferir(secoes, fontes)
    iniciais = [v.codigo for v in violacoes if v.bloqueia]
    corrigiu = False
    if corrigir and iniciais:
        try:
            corrigidas, info = _revisar_secoes_via_llm(
                caso_id, secoes, conferencia_peticao.instrucao_de_correcao(violacoes, fontes)
            )
            if info.get("alterou"):
                # Só o CONTEÚDO das seções devolvidas muda. A revisão descarta seção
                # vazia e pode renomear código; aqui a estrutura é a das oito seções
                # da geração, e perder uma na correção seria trocar defeito por defeito.
                por_codigo = {s["code"]: s["content"] for s in corrigidas}
                secoes = [
                    {**s, "content": por_codigo[s["code"]]} if s["code"] in por_codigo else s
                    for s in secoes
                ]
                corrigiu = True
                violacoes = conferencia_peticao.conferir(secoes, fontes)
        except ErroPeticao:
            log.warning("petição local: correção da conferência falhou (caso %s)", caso_id, exc_info=True)
    secoes = conferencia_peticao.marcar_citacoes_nao_verificadas(secoes, violacoes)
    registro = {
        "violacoes_iniciais": iniciais,
        "rodada_de_correcao": corrigiu,
        "violacoes_restantes": [v.codigo for v in violacoes if v.bloqueia],
        "citacoes_nao_verificadas": sum(1 for v in violacoes if v.codigo == "CITACAO_NAO_VERIFICADA"),
    }
    if iniciais:
        log.warning("petição local: conferência do caso %s: %s", caso_id, registro)
    return secoes, violacoes, registro


def _aplicar_conferencia(dados: dict[str, Any], secoes: list[dict[str, Any]], violacoes: list[Any]) -> None:
    """Grava na peça os achados e quantos deles a retêm."""
    achados = _achados_da_peca(secoes, violacoes)
    bloqueantes = sum(1 for a in achados if a["severity"] == "BLOCKING")
    dados["review"] = {**(dados.get("review") or {}), "findings": achados, "blocking": bloqueantes}
    dados["blocking_findings"] = bloqueantes


def _reconferir(caso_id: str, dados: dict[str, Any]) -> None:
    """Depois de edição humana: confere de novo, sem correção automática.

    Quem editou foi o advogado — reescrever por cima dele seria pior que o defeito.
    Mas o achado volta a refletir o texto que ELE deixou, inclusive sumindo quando
    ele corrige.
    """
    secoes = [s for s in dados.get("sections") or [] if s.get("code") != "JURIMETRY"]
    try:
        _, violacoes, _ = _conferir_contra_os_autos(caso_id, secoes, corrigir=False)
    except Exception:  # noqa: BLE001 — conferência não pode impedir salvar a edição
        log.warning("petição local: reconferência falhou (caso %s)", caso_id, exc_info=True)
        return
    _aplicar_conferencia(dados, secoes, violacoes)


def gerar(caso_id: str, *, texto_entrevista: str) -> dict[str, Any]:
    """Analisa e redige em uma chamada única à DeepSeek."""
    generation_id = str(uuid.uuid4())
    regras_aplicadas = peticao_aprendizado.regras_para_contexto(
        categoria=_categoria_do_caso(caso_id)
    )
    peticao_aprendizado.registrar_execucao(
        generation_id=generation_id, caso_id=caso_id,
        skill_name="learned_preferences_retrieval", itens_recuperados=[
            {"id": r.get("id"), "tipo": r.get("tipo"), "confidence": r.get("confidence")}
            for r in regras_aplicadas
        ], confidence=max((float(r.get("confidence") or 0) for r in regras_aplicadas), default=None),
    )
    contexto = _montar_contexto(caso_id, texto_entrevista)
    precedentes = _precedentes_para_redigir(contexto)
    legislacao = _legislacao_para_redigir(contexto)
    padroes = _padroes_conteudisticos_para_redigir(contexto)
    contexto += precedentes + legislacao + padroes
    # O QUE FALTOU, DITO AO MODELO E GRAVADO NA PEÇA.
    #
    # As três buscas caem para "" em silêncio (banco fora, embeddings sem crédito — o
    # 402 do OpenRouter de 18/09/2026). O contrato de redação continuava dizendo "você
    # trabalha com o ACERVO", o modelo acreditava ter fonte e citava súmula de memória.
    insumos = {
        "precedentes": bool(precedentes),
        "legislacao": bool(legislacao),
        "pecas_modelo": bool(padroes),
    }
    if not precedentes and not legislacao:
        contexto += (
            "\n\n=== AVISO: NENHUMA FONTE DO ACERVO FOI RECUPERADA NESTA GERAÇÃO ===\n"
            "Não há julgado, súmula, tema nem texto de lei no material. NÃO cite súmula,"
            " OJ, tema ou processo por número: onde a tese precisar de precedente, escreva"
            " [PESQUISAR PRECEDENTE ATUAL E APLICÁVEL SOBRE ESTE PONTO]. Artigo de lei só"
            " quando for indispensável e de redação notória; na dúvida, [CONFERIR: art. ...]."
        )

    # As críticas DESTE caso, já aplicadas na geração.
    #
    # `_com_skill_do_escritorio` injeta as críticas da CATEGORIA (lições que valem
    # para todo caso parecido). As deste caso específico — inclusive as marcadas
    # "só deste caso", que de propósito não instruem a categoria — ficavam de
    # fora, e gerar de novo desfazia tudo o que o advogado já tinha corrigido
    # aqui. Ele reescrevia as mesmas críticas a cada geração.
    try:
        peticao_criticas.inicializar()
        deste_caso = [
            str(c.get("prompt") or "").strip()
            for c in peticao_criticas.listar_por_caso(caso_id)
            if str(c.get("prompt") or "").strip()
        ][-20:]
    except Exception:
        log.warning("petição local: críticas do caso indisponíveis", exc_info=True)
        deste_caso = []
    if deste_caso:
        contexto += (
            "\n\n=== CORREÇÕES JÁ PEDIDAS NESTE CASO (aplique TODAS desde já) ===\n"
            + "\n".join(f"- {c}" for c in deste_caso)
            + "\nEstas correções já foram cobradas nesta peça. A minuta nova deve "
            "nascer com todas aplicadas, sem precisar que sejam pedidas de novo."
        )
    contexto += (
        # Este bloco é FORMATO — onde cada coisa entra na peça. O mérito (estrutura
        # da tese, anti-alucinação, auditoria) mora em `CONTRATO_DE_REDACAO`, que vai
        # na instrução. Antes daqui saíam três regras que o escritório revogou: cota
        # de quatro parágrafos por tese, dois julgados obrigatórios e a fórmula
        # fiscal do valor da causa. Ficaram no histórico do git, não no prompt.
        "\n\n=== PADRÃO OBRIGATÓRIO DA PEÇA ===\n"
        "A seção PRELIMINARY reúne a matéria preliminar, numerada, ANTES dos fatos: "
        "'I – DO JUÍZO 100% DIGITAL' e 'II – DA GRATUIDADE DA JUSTIÇA' pertencem a "
        "ela, cada uma com subtítulo próprio e texto desenvolvido; a seção "
        "LEGAL_GROUNDS não repete nenhuma das duas. "
        # A gratuidade é obrigatória no padrão e pede prova — foi para "cumprir" isso
        # que o modelo inventou "declaração de hipossuficiência anexa (Documento 09)".
        "Na gratuidade, só diga que a declaração de hipossuficiência está anexa se "
        "ela estiver entre os DOCUMENTOS; senão, escreva [PENDENTE: juntar declaração "
        "de hipossuficiência assinada]. "
        f"DATA DE HOJE: {datetime.now().strftime('%d/%m/%Y')} — use-a para prazos, "
        "prescrição e para saber se a estabilidade ainda está em curso. "
        "Os julgados e os dispositivos do material abaixo são REAIS e vieram do "
        "acervo: prefira-os a qualquer citação de memória, e cite apenas os que "
        "alcançarem estes fatos, dizendo por quê. Artigo ou processo citado de "
        "memória, fora do que está no material, é erro grave — a peça vai a "
        "protocolo. Sem precedente verificável para um ponto, escreva "
        "[PESQUISAR PRECEDENTE ATUAL E APLICÁVEL SOBRE ESTE PONTO]. "
        "Use subtítulos em CAIXA ALTA iniciados por DO/DA/DOS/DAS. "
        "A seção CLAIMS traz cada pedido com seu valor individual quando exigido "
        "(art. 840 da CLT), e cada pedido decorre de tese já fundamentada. "
        "A seção VALUE traz o valor da causa COERENTE com a soma dos pedidos, sem "
        "fórmula fiscal automática e SEM título de seção. "
        # "Nestes termos," vem do acervo do escritório (85 iniciais medidas);
        # "Termos em que", que estava aqui antes, não aparece em nenhuma delas.
        "A seção CLOSING deve conter apenas 'Nestes termos,', 'Pede deferimento.', "
        "local/data e advogado/OAB, sem escrever o título FECHAMENTO dentro do "
        "conteúdo e sem usar a fórmula 'Termos em que'."
    )
    instrucao_base = (
            CONTRATO_DE_REDACAO
            + """Você é advogado e redator de petições iniciais.
Em UMA resposta, organize o material do caso e redija uma minuta completa.
Use a entrevista como ALEGAÇÃO e os documentos como prova. Não invente fatos.
Onde faltar dado indispensável, escreva [PENDENTE: explicação].

ENDEREÇAMENTO (seção HEADING): abra por "Ao Juízo ..." indicando a vara e a
comarca cabíveis — não use a fórmula "EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A)
JUIZ(A)". O nome do autor vem em NEGRITO, escrito entre asteriscos duplos, assim:
**NOME COMPLETO DO CLIENTE**, seguido da qualificação corrida.

PADRÃO DO ESCRITÓRIO: quando houver orientação ou peça de referência acima,
siga-a — ela manda sobre o critério geral. Onde ela não disser nada, escolha a
forma que julgar melhor para a peça, sem inventar fato.

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
    {"code":"PRELIMINARY","label":"Das preliminares","content":"..."},
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
Cada content deve conter parágrafos separados por linha em branco."""
    )
    instrucao = _com_skill_do_escritorio(caso_id, instrucao_base)
    # Sem orientação do escritório a instrução volta intocada — e a peça sai do
    # prompt genérico. Isso tem de constar da peça, não só do log.
    insumos["orientacao_do_escritorio"] = instrucao != instrucao_base
    saida = _llm_json(
        instrucao,
        contexto,
        # 360s e não 240s: com o teto de saída dobrado a resposta é fisicamente
        # maior, e manter o prazo antigo trocaria "peça curta" por "o modelo não
        # respondeu" — que é pior, porque perde o trabalho inteiro.
        timeout=360.0,
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
    # Antes de qualquer coisa ler a peça: o que ela afirma e os autos não sustentam
    # (documento inexistente, número sem origem, pedido sem valor, tópico contra o
    # cliente, súmula de memória). Ver `conferencia_peticao`.
    secoes, violacoes, conferencia = _conferir_contra_os_autos(
        caso_id, secoes, texto_entrevista=texto_entrevista, material=contexto
    )
    jurimetria, _ = _analisar_jurimetria_da_minuta(secoes, texto_para_uf=contexto)
    pendencias = [str(p) for p in saida.get("pendencias") or [] if str(p).strip()]
    achados_criticos = peticao_aprendizado.avaliar_documento(secoes)
    peticao_aprendizado.registrar_avaliacao(
        generation_id=generation_id, caso_id=caso_id, tipo="post_generation", achados=achados_criticos
    )
    for nome in ("legal_critic", "style_critic", "consistency_check", "document_generation"):
        peticao_aprendizado.registrar_execucao(
            generation_id=generation_id, caso_id=caso_id, skill_name=nome,
            status="DONE", itens_recuperados=achados_criticos if nome != "document_generation" else [],
            confidence=1.0 if not achados_criticos else .72,
        )
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
        "generation_id": generation_id,
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
            "warnings": [*_avisos_de_insumo(insumos), *(analise.get("lacunas") or [])],
            "pendencias": pendencias or analise.get("fatos_so_na_entrevista") or [],
            "completo": not pendencias and not analise.get("lacunas"),
        },
        "review": {"summary": analise.get("observacoes", "")},
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        # Trace é explicabilidade operacional: fontes/regras/etapas. Não contém
        # cadeia de pensamento privada do modelo nem texto sensível do caso.
        "trace": {
            "generation_id": generation_id,
            "learned_rules": [
                {"id": r.get("id"), "tipo": r.get("tipo"), "confidence": r.get("confidence"),
                 "observacoes": r.get("observacoes")}
                for r in regras_aplicadas
            ],
            "skills": ["learned_preferences_retrieval", "legal_critic", "style_critic",
                       "consistency_check", "document_generation"],
            "evaluations": achados_criticos,
            "insumos": insumos,
            "conferencia": conferencia,
        },
    }
    _aplicar_conferencia(dados, secoes, violacoes)
    _salvar(caso_id, dados)
    return dados


def _avisos_de_insumo(insumos: dict[str, bool]) -> list[str]:
    """O que faltou na geração, em frase — aparece em «O que faltava quando a peça foi gerada»."""
    nomes = {
        "orientacao_do_escritorio": "a orientação do escritório (skill e regras aprendidas)",
        "pecas_modelo": "as peças-modelo do acervo do escritório",
        "precedentes": "os julgados do acervo",
        "legislacao": "o texto de lei do acervo",
    }
    faltou = [nomes[chave] for chave, presente in insumos.items() if not presente and chave in nomes]
    if not faltou:
        return []
    return [
        "Gerada SEM " + ", ".join(faltou) + " — o acervo não respondeu. A peça saiu do modelo"
        " genérico; gere de novo quando o acervo voltar."
    ]


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


def salvar_secoes_anexa(
    peca_id: str, secoes: list[dict[str, str]], usuario: str = ""
) -> dict[str, Any]:
    """Grava o texto editado de uma peça anexa. Mesma lógica de `salvar_secoes`,
    para a peça irmã em vez da petição inicial — ver `armazenamento.salvar_peticao_anexa`.
    """
    registro = armazenamento.obter_peticao_anexa(peca_id)
    if not registro:
        raise ErroPeticao("Peça não encontrada.")

    dados, anterior, _alterou = _aplicar_edicao_manual(dict(registro["dados"]), secoes, usuario)
    if anterior is not None:
        armazenamento.registrar_versao_peticao(registro["caso_id"], anterior, chave=peca_id)
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
    contexto += _precedentes_para_redigir(contexto)
    contexto += _legislacao_para_redigir(contexto)
    # A ação alternativa parte também da minuta principal: só a entrevista
    # bruta faz o modelo perder datas, valores, documentos e nomes já extraídos.
    principal = carregar(caso_id)
    secoes_principais = (principal or {}).get("sections") or []
    if secoes_principais:
        contexto += "\n\n=== MINUTA PRINCIPAL (referência factual; não copie pedidos) ===\n"
        contexto += "\n\n".join(
            f"### {secao.get('label') or secao.get('code')}\n{secao.get('content') or ''}"
            for secao in secoes_principais
            if secao.get("code") != "JURIMETRY"
        )
    alvo = [f"PEÇA A REDIGIR: {titulo}"]
    if motivo.strip():
        alvo.append(f"POR QUE ELA CABE NESTE CASO: {motivo.strip()}")
    if pedidos:
        alvo.append("PEDIDOS QUE A ANÁLISE APONTOU: " + "; ".join(p for p in pedidos if p))

    saida = _llm_json(
        _com_skill_do_escritorio(
            caso_id,
            CONTRATO_DE_REDACAO
            + """Você é advogado e vai redigir UMA peça específica, indicada
em "PEÇA A REDIGIR", usando o material do caso (entrevista, documentos, achados).

Esta NÃO é a petição inicial do caso — ela já existe. Redija a peça pedida, com os
pedidos próprios dela. Se o material não sustentar a peça, diga isso em `pendencias`
e escreva o que for possível com [PENDENTE: explicação] no que faltar.

Use SOMENTE fatos da entrevista e dos documentos — não invente. A qualificação do
autor sai do bloco IDENTIDADE DO RECLAMANTE, nunca de nome citado na conversa.

QUALIDADE INEGOCIÁVEL: esta peça alternativa deve ter a mesma profundidade,
estrutura e padrão profissional da petição principal. Não entregue resumo,
modelo genérico ou esqueleto só porque é uma ação concorrente. Desenvolva
integralmente fatos, provas, nexo, dispositivos legais, subsunção e consequência
jurídica. Inclua todas as preliminares cabíveis, cada tese específica da ação,
pedidos individualizados coerentes com a fundamentação, provas requeridas, valor
da causa calculado e fechamento. Reaproveite a riqueza factual da minuta principal
quando pertinente, mas não copie pedidos de outra ação nem reduza o texto ao
mínimo. Se uma tese não couber nesta ação, não a invente: explique a distinção
em `pendencias`.

JSON:
{
  "secoes": [
    {"code":"HEADING","label":"Endereçamento e qualificação","content":"..."},
    {"code":"PRELIMINARY","label":"Das preliminares","content":"..."},
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
        # 360s e não 240s: com o teto de saída dobrado a resposta é fisicamente
        # maior, e manter o prazo antigo trocaria "peça curta" por "o modelo não
        # respondeu" — que é pior, porque perde o trabalho inteiro.
        timeout=360.0,
    )

    secoes = _normalizar_secoes(saida.get("secoes") or [])
    if not any(secao["content"] for secao in secoes):
        raise ErroPeticao("O modelo não devolveu texto desta peça.")

    agora = _agora()
    existente = armazenamento.obter_peticao_anexa(peca_id)
    versao_anexa = 1
    if existente and existente.get("dados"):
        armazenamento.registrar_versao_peticao(caso_id, existente["dados"], chave=peca_id)
        versao_anexa = int(existente["dados"].get("version") or 1) + 1
    dados = {
        "id": peca_id,
        "document_type": "ADDITIONAL_CLAIM",
        "title": titulo,
        "motivo": motivo.strip(),
        "version": versao_anexa,
        "created_at": agora,
        "updated_at": agora,
        "sections": secoes,
        "pendencias": [str(p) for p in saida.get("pendencias") or [] if str(p).strip()],
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "docx_style_version": DOCX_STYLE_VERSION,
        "revisao": {"tipo": "geracao", "usuario": gerada_por, "em": agora, "alteradas": []},
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
    dados = registro.get("dados") or {}
    if int(dados.get("docx_style_version") or 0) < DOCX_STYLE_VERSION:
        conteudo = montar_docx(dados.get("sections") or [])
    if not conteudo:
        # Regrava a partir do JSON: o texto é a verdade, o binário é derivado.
        conteudo = montar_docx(dados.get("sections") or [])
    return str(registro.get("titulo") or "Peça"), conteudo


def ler_pdf_anexa(peca_id: str) -> tuple[str, bytes]:
    from . import docx_pdf

    titulo, docx = ler_docx_anexa(peca_id)
    try:
        return titulo, docx_pdf.converter(docx)
    except docx_pdf.ErroConversaoDocx as erro:
        raise ErroPeticao(str(erro)) from erro


#: Contrato de redação do escritório, escrito pelo advogado responsável.
#:
#: Vale para os TRÊS pontos que redigem peça — geração principal, `redigir` e peça
#: anexa. Constante única de propósito: quando isto morava copiado em cada
#: instrução, uma mudança pegava num lugar e nos outros não, e a diferença só
#: aparecia semanas depois numa peça que saiu fora do padrão.
CONTRATO_DE_REDACAO = """Você elabora peças jurídicas profissionais destinadas à revisão e ao protocolo por advogado.

POSTURA PROFISSIONAL: atue como advogado brasileiro sênior, com mais de quarenta
anos de prática forense multidisciplinar. Quando o material da tarefa trouxer os
blocos do ACERVO JURÍDICO do escritório (legislação, julgados, peças), consuma os
dispositivos recuperados sempre que forem pertinentes e prefira-os à memória.
Quando o material NÃO trouxer esses blocos, você não tem fonte nesta tarefa: não
simule que tem. Nunca invente lei, artigo, vigência, precedente ou fato.
O acervo é fonte para pesquisa e fundamentação, não autorização para citar norma
irrelevante ou despejar artigos sem subsunção.

IDENTIFICAÇÃO E EXPLICAÇÃO DA LEI: toda vez que citar uma norma, descreva-a de
forma profissional no próprio raciocínio: espécie e número da norma (e sua
denominação, quando houver), artigo/parágrafo/inciso invocado, o conteúdo jurídico
relevante e o efeito que ele produz no caso. Não escreva apenas “nos termos do art.
X” nem use citação ornamental. Exemplo de padrão: “O art. X da Lei nº Y/AAAA,
que assegura/proíbe/condiciona Z, incide porque o documento/fato A demonstra B;
daí decorre o pedido C.” Não transcreva a lei por volume: use a passagem necessária
e, em seguida, faça a subsunção concreta.

USO INTENSIVO E CRÍTICO DO ACERVO: em cada tópico jurídico material (competência,
preliminar, responsabilidade, cada espécie de dano, estabilidade, prescrição,
prova, consectários e pedido), procure no material recuperado a norma e o julgado
pertinentes. Desenvolva o tópico em camadas — regra legal explicada, fato e prova
específicos, aplicação, objeção previsível e consequência processual — em vez de
um único parágrafo conclusivo. Não use o acervo como enfeite, mas também não deixe
de usá-lo quando houver fonte aderente. Se a fonte não cobrir o ponto, declare a
pendência de pesquisa em vez de simular erudição.

EXIGÊNCIA DE EXCELÊNCIA E COMPLETUDE: entregue peça pronta para revisão final de
advogado experiente, nunca um rascunho genérico. Antes de responder, faça uma
varredura silenciosa de: competência e partes; fatos e cronologia; prova disponível
e a produzir; prescrição/prazos, preliminares e tutela urgente quando cabíveis;
teses principais, subsidiárias e defesas previsíveis; legislação aplicável;
jurisprudência verificável; pedidos, consectários, provas, valor da causa, ônus,
gratuidade, honorários e fechamento. Inclua tudo que os fatos sustentarem e diga
expressamente em [PENDENTE: ...] o que depender de dado ainda não fornecido. Não
omita questão relevante por economia de texto, mas não invente para preencher.

PROIBIDO texto vazio de conteúdo, como "resta evidente", "é pacífico" ou
"conforme entendimento consolidado", sem indicar fato, prova, norma e raciocínio
que tornem a conclusão defensável neste caso concreto.

NATUREZA DA AÇÃO, PARTES E COMPETÊNCIA: antes de redigir, identifique pelo pedido e
pelos fatos se a medida é trabalhista, cível, previdenciária ou de outra jurisdição.
Não chame automaticamente as partes de reclamante/reclamada nem trate toda pessoa
jurídica como empregadora: esses termos só cabem em reclamação trabalhista. Em
ação cível use autor/réu; em demanda previdenciária, autor e INSS, quando for o
caso. Escolha vara e competência compatíveis com a ação. O endereçamento sempre
começa por "Ao Juízo da ...", nunca por "Excelentíssimo(a) Senhor(a) Doutor(a)
Juiz(a)". Não invente comarca, vara, relação de trabalho ou qualidade das partes:
sinalize o dado ausente como [PENDENTE: ...].

Sua prioridade NÃO é produzir texto longo. É produzir fundamentação juridicamente
precisa, estrategicamente estruturada, verificável e conectada aos fatos e às provas.

ESTRUTURA DE CADA TESE, obrigatória:
FATO RELEVANTE -> PROVA DISPONÍVEL -> QUESTÃO JURÍDICA -> NORMA APLICÁVEL ->
JURISPRUDÊNCIA (quando necessária) -> SUBSUNÇÃO -> CONSEQUÊNCIA/PEDIDO.
Nada de enumerar artigos nem de explicar a lei em abstrato sem mostrar por que ela
alcança ESTES fatos.

NÃO TRATE FATO CONTROVERTIDO COMO PROVADO. Nunca afirme "há nexo causal evidente",
"a doença decorreu do trabalho" ou "a incapacidade está comprovada" quando isso
depender de perícia ou de prova ainda não produzida. Escreva, por exemplo: "os
elementos documentais e fáticos constituem indícios de nexo causal ou concausal,
cuja confirmação deverá ocorrer mediante prova pericial". Separe sempre fato
documentalmente comprovado, alegação da parte, indício, conclusão médica,
conclusão jurídica e questão dependente de perícia. Nunca atribua a um documento
conclusão que ele não contém: receituário com CID mostra diagnóstico, não nexo.

TESES PRINCIPAL E SUBSIDIÁRIA. Quando couber, não dependa de uma só: nexo causal
direto como principal e concausalidade como subsidiária (art. 21, I, da Lei
8.213/91), sem confundir causalidade, concausalidade, doença preexistente,
degenerativa e agravamento pelo trabalho.

UMA FUNDAMENTAÇÃO POR PATOLOGIA. Para cada doença ou grupo, analise atividade
exercida, exposição, fator de risco, evolução temporal, documentação médica,
mecanismo causal, norma aplicável, necessidade de perícia, dano e incapacidade.
Em doenças osteomusculares verifique art. 7º, XXII e XXVIII, da Constituição,
arts. 157 e ss. da CLT, arts. 19, 20 e 21 da Lei 8.213/91, a NR efetivamente
aplicável e arts. 186, 927, 949 e 950 do Código Civil. Não cite NR nem dispositivo
sem relação concreta com os fatos.

RESPONSABILIDADE CIVIL, elemento a elemento: CONDUTA/OMISSÃO + CULPA (quando
exigida) + DANO + NEXO. Não presuma culpa porque houve doença; aponte a conduta
patronal concreta. Havendo atividade de risco, enfrente o art. 927, parágrafo
único, do Código Civil e mantenha a responsabilidade subjetiva como alternativa.

DANO MATERIAL E PENSIONAMENTO nunca genéricos. No art. 950, analise redução da
capacidade, percentual, parcial ou total, temporária ou permanente, atividade
afetada, readaptação, base remuneratória e concausa. Quando depender de perícia,
diga isso e formule o pedido de forma compatível.

DANO MORAL não se presume da doença. Demonstre LESÃO + REPERCUSSÃO CONCRETA NA
VIDA DA PARTE + RESPONSABILIDADE + NEXO, com arts. 223-A a 223-G da CLT quando
aplicáveis. Ao sugerir valor, explique o critério e não invente precedente.

PROVA PERICIAL: quando a causa depender de conhecimento técnico, crie seção
própria e formule quesitos (diagnóstico, data de início, compatibilidade entre
atividade e patologia, nexo, concausa, agravamento, fatores extralaborais,
incapacidade e percentual, caráter temporário ou permanente, limitações,
readaptação, tratamento, prognóstico). Avalie se cabe também análise ergonômica.

DOCUMENTOS: antes de fundamentar, monte mentalmente a matriz FATO | PROVA | O QUE
A PROVA REALMENTE DEMONSTRA | TESE. Informação sem documento vira pedido de
produção de prova, não afirmação. Aponte o que deve ser requerido à parte
contrária ou a órgão público.
Quando um fato for extraído de anexo, indique no texto a prova correspondente
como "Documento NN — nome do arquivo", usando exatamente a numeração do bloco
DOCUMENTOS recebido. Não cite documento que não esteja no contexto.
A referência "(Documento NN)" só acompanha frase cujo conteúdo ESTEJA naquele
documento. Fato que só aparece na entrevista leva "conforme relato do autor" — nunca
o número de um documento que não o contém (a CAT não prova que a trava estava
quebrada só porque descreve a queda).
NUNCA diga que um documento está "anexo", "juntado", "acostado" ou "incluso" se ele
não estiver no bloco DOCUMENTOS — inclusive declaração de hipossuficiência,
procuração, laudo, exame e cartão de ponto. Se a peça precisar dele, escreva
[PENDENTE: juntar <documento>].
Todo número de documento do cliente (CPF, RG, CTPS, PIS, NB, CAT, CNPJ, data) sai
copiado dos DOCUMENTOS, da qualificação ou da entrevista. Número que não está lá não
entra: vira [PENDENTE: <dado>].

JURISPRUDÊNCIA — REGRA ANTI-ALUCINAÇÃO. É PROIBIDO inventar número de processo,
súmula, tema, ementa, acórdão, relator, tribunal ou data. Só cite súmula, OJ, tema
ou julgado que esteja NO MATERIAL RECEBIDO — a sua memória não é verificação: é
dela que saiu "Súmula 6 do TST" para acúmulo de função, quando a Súmula 6 trata de
equiparação salarial. Toda citação é conferida depois contra o material; a que não
estiver lá sai carimbada na peça como não verificada. Prioridade: precedente
vinculante do STF; tema repetitivo e precedente qualificado do TST; súmula e OJ
do TST; SDI; Turmas do TST; TRT competente. Não use precedente só porque tem
palavras parecidas: compare fatos, atividade, questão decidida e fundamento
determinante, e explique em uma frase por que ele se aplica; reconheça a distinção
quando existir. Se não houver precedente verificável para o ponto, escreva
[PESQUISAR PRECEDENTE ATUAL E APLICÁVEL SOBRE ESTE PONTO] em vez de inventar.

PEDIDOS: cada um decorre de tese já fundamentada, com valor individual quando
exigido (art. 840 da CLT). Não há pedido sem fundamentação nem fundamentação sem
pedido. O valor da causa deve ser coerente com a soma dos pedidos — não atribua
valor arbitrário nem recorra automaticamente a fórmula fiscal.
Na reclamação trabalhista, TODO pedido de pagamento traz o valor NA PRÓPRIA LINHA do
pedido — "a apurar em liquidação" não basta (art. 840, § 1º, da CLT). O valor é
ESTIMADO com o critério escrito ao lado, a partir dos dados dos documentos (ex.:
"2 h/dia × 22 dias × 22 meses × valor-hora de R$ 10,82 × 1,5"). É PROIBIDO criar
pedido ou parcela sem fato que o sustente, e PROIBIDO ajustar parcela para o total
dar número redondo: o valor da causa é a soma, seja ela qual for.

O QUE NÃO SERVE AO CLIENTE NÃO ENTRA NA PEÇA. Verba que você concluiu ser indevida
(multa sem atraso, direito que os fatos não dão) não vira tópico "não se aplica" na
petição: a peça é do cliente. Essa conclusão vai em `analise.observacoes`.
E o contrário também vale: tirar o tópico NÃO é motivo para PEDIR a verba. Se os
documentos mostram que a rescisão foi paga e homologada no prazo, a multa do art. 477
simplesmente não aparece — nem como tópico, nem como pedido.
Gratuidade, citação, provas, custas e honorários não levam valor próprio: não
escreva "R$ 0,00" para eles nem coloque custas como pedido com valor.

GRATUIDADE, HONORÁRIOS E PROCESSO: priorize a CLT vigente; antes de aplicar o CPC
subsidiariamente, verifique se a CLT já disciplina a matéria e se há decisão
vinculante sobre o dispositivo.

ESTABILIDADE ACIDENTÁRIA não se pede automaticamente. Verifique vínculo ativo,
afastamento, espécie e cessação de benefício, dispensa, momento da constatação,
art. 118 da Lei 8.213/91 e Súmula 378 do TST. Não peça reintegração de quem
continua trabalhando sem fundamento específico. Compare o fim da estabilidade com a
DATA DE HOJE (vem no material): se o período já terminou, não peça reintegração — só
a indenização dos salários e consectários DA DISPENSA ATÉ O FIM do período, não de
doze meses cheios.

CAT: a ausência não prova nexo. Analise primeiro se havia elementos que impunham a
comunicação e depois a eventual omissão; não use a falta de CAT de forma circular.

ESTILO: técnico, objetivo, persuasivo, organizado, sem repetição e sem juridiquês
desnecessário. Prefira TRÊS parágrafos fortes e específicos a dez genéricos. Nenhum
parágrafo existe para aumentar o tamanho do texto. Não repita o mesmo artigo nem
copie ementa longa: use só a tese relevante, identificada.

AUDITORIA ANTES DE ENTREGAR: artigo citado corretamente? jurisprudência
verificada? algum fato apresentado como provado sem prova? conclusão que depende
de perícia? contradição entre fatos e pedidos? pedido sem fundamento ou
fundamento sem pedido? valores onde exigidos? valor da causa coerente? súmula ou
precedente vinculante mais apropriado? norma revogada ou superada? tese
subsidiária relevante faltando? os documentos sustentam o alegado? Corrija antes
de responder.

OBJETIVO: uma peça que um advogado possa revisar juridicamente, não um texto que
apenas pareça jurídico. Precisão acima de quantidade; subsunção acima de
transcrição; precedente verificável acima de precedente convincente.

"""


_INSTRUCAO_REVISAO = """Você é advogado revisando uma peça jurídica já redigida.
Aplique a CRÍTICA DO ADVOGADO sobre a MINUTA ATUAL.

Linhas no formato [[FOTO:…]] são fotos inseridas na peça. Copie-as IGUAIS, na mesma
posição em relação ao texto em volta, salvo se a crítica pedir para tirar ou mover a
foto.

Linhas que começam com «> » são CITAÇÕES LITERAIS de documento (com a fonte entre
parênteses). Copie-as IGUAIS, palavra por palavra, salvo se a crítica pedir para tirar,
mover ou alterar a citação. Nunca resuma nem reescreva o que o documento diz.

Marcações de formatação feitas pelo advogado — [[i]]…[[/i]], [[u]]…[[/u]],
[[tam=14]]…[[/tam]], [[cor=#c00000]]…[[/cor]] e [[alin=centro]] no começo da linha —
são parte do texto: mantenha-as em volta das mesmas palavras e no mesmo parágrafo. Se
reescrever um trecho marcado, leve a marcação junto; não crie marcações novas.

ANTES DE ESCREVER, CLASSIFIQUE O PEDIDO:

(a) PONTUAL — troca um nome, separa um pedido, corrige uma data, ajusta um trecho
    determinado. Aqui mude SOMENTE o que foi pedido e preserve o restante palavra
    por palavra.

(b) APROFUNDAMENTO — "fundamentação rasa", "deixa mais robusto", "explique
    melhor", "desenvolve mais", "coloca uma parte maior dos julgados", "melhora
    em todos os pontos". Aqui NÃO faça retoque: REESCREVA as seções envolvidas com
    fundamentação mais completa. Cada parágrafo raso vira argumentação
    desenvolvida na estrutura fato -> prova -> norma -> subsunção -> consequência.
    Desenvolva os julgados e súmulas JÁ citados na minuta, explicando por que
    alcançam estes fatos. Se a crítica disser "em todos os pontos" ou não nomear
    seção, aprofunde TODAS as seções argumentativas (Dos fatos, Do direito, Dos
    pedidos).

    Aprofundar é ganhar PRECISÃO, não linhas: o que falta é subsunção, prova
    apontada e consequência jurídica, não volume. Devolver o mesmo raciocínio com
    outras palavras é FALHAR no pedido — e inflar o texto com parágrafo genérico
    para parecer maior também é.

Em (b) o "preserve palavra por palavra" NÃO se aplica: expandir, reorganizar e
reescrever é justamente o que foi pedido. O limite é outro — nunca invente fato,
prova, número de processo, valor ou data que não estejam na minuta atual. Sem
material novo, aprofunde o RACIOCÍNIO JURÍDICO sobre o que já existe.

NUNCA devolva a minuta inteira igual ao que recebeu. Se o pedido for vago, ambíguo
ou parecer já atendido, NÃO pare: aplique a melhor interpretação possível — o
advogado pediu uma mudança e espera vê-la — e registre em "perguntas" o que
precisaria confirmar com ele. Perguntar é bem-vindo; devolver o texto intacto, não.

Você tem poder total sobre a peça. Pode reescrever, criar, excluir ou reordenar
seções inteiras quando isso decorrer da crítica, inclusive alterar praticamente
100% do documento. Se o pedido for pontual, calibre a alteração para ele; se for
profundo, entregue uma nova versão profunda e completa. Você pode criar e renumerar os títulos e
subtítulos internos (I –, II –, I.1 –) e mover matéria de uma seção para outra —
por exemplo tirar as preliminares do DO DIREITO e levá-las para DAS PRELIMINARES.
Nada aqui é intocável, desde que a crítica do advogado sustente a mudança.

TABELAS: quando a crítica pedir uma tabela, ou quando uma tabela tornar fatos
comprovados mais claros, use Markdown com cabeçalho e linha separadora no ponto
exato da seção solicitado. A exportação transforma esse bloco em tabela Word
nativa e editável. Preserve os parágrafos que vêm antes e depois; nunca use
espaços, tabs ou dados inventados para simular/preencher uma tabela.

Devolva a NOVA PEÇA COMPLETA como lista ordenada de seções. Não há quantidade,
ordem ou código fixos: inclua todas as seções necessárias, inclusive as mantidas.
Cada `code` deve ser estável, curto e único. JSON:
{
  "secoes": [
    {"code": "HEADING", "label": "Endereçamento e qualificação", "content": "..."},
    {"code": "PRELIMINARY", "label": "Das preliminares", "content": "..."},
    {"code": "FACTS", "label": "Dos fatos", "content": "..."},
    {"code": "LEGAL_GROUNDS", "label": "Do direito", "content": "..."},
    {"code": "CLAIMS", "label": "Dos pedidos", "content": "..."},
    {"code": "EVIDENCE", "label": "Das provas", "content": "..."},
    {"code": "VALUE", "label": "Do valor da causa", "content": "..."},
    {"code": "CLOSING", "label": "Fechamento", "content": "..."}
  ],
  "perguntas": ["o que você precisaria confirmar com o advogado; [] se nada"]
}
Cada content em parágrafos separados por linha em branco."""

_INSTRUCAO_CONFERENCIA = """Você confere se a revisão de uma peça jurídica foi feita corretamente.
Recebe o PEDIDO DO ADVOGADO e, para cada seção alterada, o texto ANTES e DEPOIS.
Seja rigoroso: "atendeu" só é true se TUDO o que o pedido manda estiver no texto DEPOIS.

Quando o pedido for de APROFUNDAMENTO ("fundamentação rasa", "mais robusto",
"explique melhor", "em todos os pontos"), duas regras mudam:

- "atendeu" só é true se o texto DEPOIS estiver de fato mais DESENVOLVIDO que o
  ANTES. Mesmo tamanho com palavras trocadas é false.
- "alteradas_sem_pedido" fica VAZIO. Pedido global autoriza mexer em qualquer
  seção argumentativa, e marcar seção ali faria o sistema DESFAZER exatamente a
  ampliação que o advogado pediu.

Responda APENAS JSON:
{"atendeu": true, "faltou": "o que do pedido não foi feito, em uma frase; vazio se atendeu",
 "alteradas_sem_pedido": ["code de seção alterada que o pedido não justifica"]}"""


#: Como o advogado pede APROFUNDAMENTO, e não um retoque pontual.
#:
#: Colhido dos pedidos reais que não estavam funcionando: "Fundamentação muito
#: rasa, melhora isso em todos os pontos", "Deixa os parágrafos mais robustos",
#: "Coloca uma parte maior dos julgados e explique melhor os parágrafos".
#:
#: Sem acento e em minúsculas — a comparação passa por `_sem_acento`.
_SINAIS_DE_APROFUNDAMENTO = (
    "todos os pontos", "em tudo", "mais robust", "robustez", "aprofund",
    "mais denso", "rasa", "raso", "superficial", "explique melhor",
    "explica melhor", "desenvolv", "mais longo", "mais extenso", "amplie",
    "amplia", "detalhe mais", "detalha mais", "mais complet", "enriquec",
    "melhora isso", "melhore isso", "parte maior", "mais fundament",
)


def _pedido_global(prompt_critica: str) -> bool:
    """O advogado pediu para APROFUNDAR, e não para mexer num ponto específico?

    Isto decide se a trava de `alteradas_sem_pedido` vale. Num pedido pontual
    ela protege o texto: impede a IA de reescrever o que ninguém mandou. Num
    pedido de aprofundamento ela fazia o oposto do pedido — a conferência
    marcava as seções como "não pedidas" e o código RESTAURAVA o texto raso.
    O advogado via "Seções alteradas: Dos fatos, Do direito" e um texto do mesmo
    tamanho de antes. Foi o defeito relatado nas versões 8, 9 e 10 da peça.

    Errar para o lado de considerar global é o lado barato: no máximo a IA
    aprofunda uma seção a mais, e o advogado revisa o texto de qualquer forma.
    O caro é o contrário — desfazer em silêncio o que ele pediu três vezes.
    """
    texto = _sem_acento(prompt_critica).lower()
    return any(sinal in texto for sinal in _SINAIS_DE_APROFUNDAMENTO)


def _texto_normalizado(texto: Any) -> str:
    return " ".join(str(texto or "").split())


def _mesclar_revisao(
    secoes_atuais: list[dict[str, Any]], revisadas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    por_codigo = {str(s.get("code") or ""): s for s in revisadas}
    resultado = []
    for atual in secoes_atuais:
        nova = por_codigo.get(str(atual.get("code") or "")) or {}
        conteudo = str(nova.get("content") or "").strip()
        resultado.append({**atual, "content": conteudo, "written_by": "agent"} if conteudo else dict(atual))
    return resultado


def _secoes_alteradas(
    antes: list[dict[str, Any]], depois: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    anteriores = {s.get("code"): _texto_normalizado(s.get("content")) for s in antes}
    return [s for s in depois if _texto_normalizado(s.get("content")) != anteriores.get(s.get("code"))]


def _conferir_revisao(
    prompt_critica: str,
    antes: list[dict[str, Any]],
    alteradas: list[dict[str, Any]],
) -> dict[str, Any]:
    anteriores = {s.get("code"): s for s in antes}
    trechos = "\n\n".join(
        f"### {s.get('code')} — {s.get('label')}\n"
        f"ANTES:\n{(anteriores.get(s.get('code')) or {}).get('content', '')}\n"
        f"DEPOIS:\n{s.get('content', '')}"
        for s in alteradas
    )
    try:
        saida = _llm_json(
            _INSTRUCAO_CONFERENCIA,
            f"PEDIDO DO ADVOGADO:\n{prompt_critica}\n\nSEÇÕES ALTERADAS:\n{trechos}",
            timeout=120.0,
        )
    except ErroPeticao:
        return {"atendeu": None, "faltou": "", "alteradas_sem_pedido": []}
    atendeu = saida.get("atendeu")
    indevidas = saida.get("alteradas_sem_pedido")
    return {
        "atendeu": atendeu if isinstance(atendeu, bool) else None,
        "faltou": str(saida.get("faltou") or "").strip()[:500],
        "alteradas_sem_pedido": [str(c) for c in indevidas if isinstance(c, str)]
        if isinstance(indevidas, list)
        else [],
    }


def _revisar_secoes_via_llm(
    caso_id: str, secoes_atuais: list[dict[str, Any]], prompt_critica: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    instrucao = _com_skill_do_escritorio(caso_id, _INSTRUCAO_REVISAO, revisao=True)
    minuta_atual = "\n\n".join(
        f"### {s.get('code')} — {s.get('label', s.get('code'))}\n{s.get('content', '')}"
        for s in secoes_atuais
    )
    observacao = ""
    perguntas: list[str] = []
    melhor: tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], int] | None = None

    # Três tentativas, e não duas: a SEGUNDA revisão de uma peça é o caso difícil
    # — a minuta já foi corrigida uma vez, e o modelo tende a concluir que "já
    # está bom" e devolver tudo igual. Era exatamente aí que a tela quebrava.
    for tentativa in (1, 2, 3):
        entrada = f"MINUTA ATUAL:\n{minuta_atual}\n\nCRÍTICA DO ADVOGADO:\n{prompt_critica}"
        if observacao:
            entrada += (
                f"\n\nATENÇÃO — A TENTATIVA ANTERIOR FALHOU: {observacao}\n"
                # NÃO repita aqui "mude somente o que a crítica pede": era o que
                # estava escrito, e num pedido de aprofundamento essa frase
                # mandava o modelo fazer o MÍNIMO justamente na segunda chance,
                # depois de a primeira já ter sido rasa demais.
                "Corrija isso agora. Se a crítica pede aprofundamento, reescreva "
                "as seções envolvidas de forma substancialmente mais longa e "
                "densa — não basta trocar palavras."
            )
        # 360s como nas de redação: esta chamada REESCREVE a peça inteira, e com o
        # teto de saída em 8192 a resposta ficou do mesmo tamanho. Pior, ela roda em
        # laço de até três tentativas — estourar o prazo aqui perde a crítica que o
        # advogado acabou de escrever, que é o erro mais caro deste fluxo.
        saida = _llm_json(instrucao, entrada, timeout=360.0)
        perguntas = [
            str(p).strip()
            for p in (saida.get("perguntas") or [])
            if str(p).strip()
        ][:5]
        secoes = _normalizar_secoes_da_revisao(saida.get("secoes") or [])
        alteradas = _secoes_alteradas(secoes_atuais, secoes)
        mudou_estrutura = [s.get("code") for s in secoes_atuais] != [s.get("code") for s in secoes]
        if not alteradas and not mudou_estrutura:
            observacao = (
                "você devolveu a minuta inteira igual. Aplique a melhor interpretação do "
                "pedido e registre em 'perguntas' o que precisar confirmar."
            )
            continue

        conferencia = _conferir_revisao(prompt_critica, secoes_atuais, alteradas)
        # Pedido GLOBAL não tem seção indevida — e isto não é detalhe: era esta
        # trava que desfazia o trabalho. Em "melhora a fundamentação em todos os
        # pontos", a conferência marcava seções como "não pedidas" e o código
        # restaurava o texto raso original. O advogado via "Seções alteradas:
        # Dos fatos, Do direito" e um texto que continuava do mesmo tamanho.
        melhor = (secoes, alteradas, conferencia, tentativa)
        if conferencia["atendeu"] is not False:
            break
        observacao = conferencia["faltou"] or "a revisão não fez tudo o que a crítica pede."

    if melhor is None:
        # NÃO é mais erro, e a diferença importa: levantar aqui abortava a tela e
        # perdia o pedido do advogado. Agora a peça volta intacta com o aviso —
        # quem chama decide não criar versão nova — e as perguntas da IA sobem
        # junto, que é o caminho para destravar o pedido ambíguo.
        return list(secoes_atuais), {
            "alteradas": [],
            "alterou": False,
            "atendeu": None,
            "faltou": "",
            "perguntas": perguntas,
            "tentativas": 3,
        }

    secoes, alteradas, conferencia, tentativas = melhor
    secoes = _preservar_fotos(secoes_atuais, secoes, prompt_critica)
    secoes = _preservar_citacoes(secoes_atuais, secoes, prompt_critica)
    return secoes, {
        "alteradas": [str(s.get("label") or s.get("code")) for s in alteradas],
        "alterou": True,
        "atendeu": conferencia["atendeu"],
        "faltou": "" if conferencia["atendeu"] is not False else conferencia["faltou"],
        "perguntas": perguntas,
        "tentativas": tentativas,
    }


def revisar_anexa_com_prompt(
    peca_id: str, *, prompt_critica: str, usuario: str = ""
) -> dict[str, Any]:
    prompt_critica = prompt_critica.strip()
    if not prompt_critica:
        raise ErroPeticao("Escreva o que deve mudar nesta peça.")

    registro = armazenamento.obter_peticao_anexa(peca_id)
    if not registro:
        raise ErroPeticao("Peça não encontrada.")

    anterior = json.loads(json.dumps(registro["dados"]))
    dados = dict(registro["dados"])
    secoes_atuais = dados.get("sections") or []
    if not secoes_atuais:
        raise ErroPeticao("Esta peça não tem seções para revisar.")

    secoes, conferencia = _revisar_secoes_via_llm(registro["caso_id"], secoes_atuais, prompt_critica)

    # Mesma regra da petição inicial: sem alteração, sem versão nova. Ver o
    # comentário em `revisar_com_prompt`.
    if not conferencia.get("alterou"):
        return para_api({**dados, "revisao": {
            "tipo": "prompt",
            "prompt": prompt_critica,
            "usuario": usuario,
            "em": _agora(),
            **conferencia,
        }})

    armazenamento.registrar_versao_peticao(registro["caso_id"], anterior, chave=peca_id)
    agora = _agora()
    dados["sections"] = secoes
    dados["updated_at"] = agora
    dados["version"] = int(anterior.get("version") or 1) + 1
    dados["revisao"] = {
        "tipo": "prompt",
        "prompt": prompt_critica,
        "usuario": usuario,
        "em": agora,
        **conferencia,
    }

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
    caso_id: str,
    *,
    prompt_critica: str,
    usuario: str,
    generaliza: bool = True,
    origem: str = "painel",
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

    secoes, conferencia = _revisar_secoes_via_llm(caso_id, secoes_atuais, prompt_critica)

    # Nada mudou: devolve a peça como está, SEM versão nova.
    #
    # Antes isto levantava erro e a tela morria — era o defeito da "segunda
    # revisão". Agora é aviso. Mas também não pode virar versão: gravar snapshot
    # e incrementar `version` com o texto idêntico encheria o histórico de
    # versões falsas, e o advogado perderia a referência de quando a peça
    # realmente mudou. As perguntas da IA sobem junto — é com elas que ele
    # reescreve o pedido e destrava.
    if conferencia.get("alterou"):
        # A revisão pedida pelo advogado (ou pelo chat) também passa pela conferência.
        # Sem correção automática: o pedido foi DELE, e reescrever por cima mudaria o
        # que ele pediu. Mas a súmula de memória sai carimbada e o achado aparece na
        # comparação, antes de ele aceitar.
        try:
            secoes, violacoes, _ = _conferir_contra_os_autos(caso_id, secoes, corrigir=False)
            conferencia["conferencia_autos"] = conferencia_peticao.como_achados(violacoes)
        except Exception:  # noqa: BLE001 — conferência não pode perder o pedido do advogado
            log.warning("petição local: conferência da revisão falhou (caso %s)", caso_id, exc_info=True)
        candidato = {
            "id": uuid.uuid4().hex, "status": "PENDING_REVIEW",
            "base_version": int(atual.get("version") or 1), "sections": secoes,
            "prompt": prompt_critica, "usuario": usuario, "generaliza": generaliza,
            "created_at": _agora(), "revisao": {"tipo": "prompt", "prompt": prompt_critica,
                "usuario": usuario, "origem": origem, "em": _agora(), **conferencia},
        }
        novos_dados = {**atual, "revisao_pendente": candidato}
        _salvar(caso_id, novos_dados)
        return novos_dados

    if not conferencia.get("alterou"):
        return {**atual, "revisao": {
            "tipo": "prompt",
            "prompt": prompt_critica,
            "usuario": usuario,
            "origem": origem,
            "em": _agora(),
            **conferencia,
        }}

    # 1) snapshot da versão anterior — antes de sobrescrever.
    armazenamento.registrar_versao_peticao(caso_id, atual)

    versao_origem = int(atual.get("version") or 1)
    versao_resultado = versao_origem + 1
    novos_dados = {
        **atual,
        "version": versao_resultado,
        "status": "IN_REVIEW",
        "sections": secoes,
        "revisao": {
            "tipo": "prompt",
            "prompt": prompt_critica,
            "usuario": usuario,
            # De onde veio o pedido: o campo do painel ou o chat ao lado da peça.
            # Documento jurídico não pode ter edição de origem desconhecida.
            "origem": origem,
            "em": _agora(),
            **conferencia,
        },
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


def aceitar_revisao_pendente(caso_id: str, revisao_id: str) -> dict[str, Any]:
    atual = carregar(caso_id)
    candidata = (atual or {}).get("revisao_pendente") or {}
    if not atual or candidata.get("id") != revisao_id:
        raise ErroPeticao("Revisão pendente não encontrada.")
    if int(candidata.get("base_version") or 0) != int(atual.get("version") or 1):
        raise ErroPeticao("A peça mudou após a revisão; gere uma nova comparação.")
    secoes = candidata.get("sections") or []
    if not secoes:
        raise ErroPeticao("A revisão pendente não contém uma peça válida.")
    diff_aprovado = peticao_aprendizado.diff_semantico(atual.get("sections") or [], secoes)
    armazenamento.registrar_versao_peticao(caso_id, {k: v for k, v in atual.items() if k != "revisao_pendente"})
    agora = _agora()
    dados = {k: v for k, v in atual.items() if k != "revisao_pendente"}
    dados.update({
        "sections": secoes, "version": int(atual.get("version") or 1) + 1,
        "status": "IN_REVIEW", "updated_at": agora,
        "revisao": {"tipo": "prompt", "status": "ACCEPTED", "id": revisao_id,
            "prompt": candidata.get("prompt", ""), "usuario": candidata.get("usuario", ""),
            "em": agora, "semantic_diff": diff_aprovado, **(candidata.get("revisao") or {})},
    })
    _reconferir(caso_id, dados)
    _salvar(caso_id, dados)
    try:
        peticao_criticas.inicializar()
        peticao_criticas.registrar(caso_id=caso_id, categoria=_categoria_do_caso(caso_id),
            versao_origem=int(atual.get("version") or 1), versao_resultado=int(dados["version"]),
            prompt=str(candidata.get("prompt") or ""), usuario=str(candidata.get("usuario") or ""),
            generaliza=bool(candidata.get("generaliza", True)))
    except Exception:
        log.exception("crítica aceita não pôde ser registrada (caso %s)", caso_id)
    try:
        peticao_aprendizado.registrar_feedback(
            caso_id=caso_id, categoria=_categoria_do_caso(caso_id),
            advogado=str(candidata.get("usuario") or ""), texto=str(candidata.get("prompt") or ""),
            geral=bool(candidata.get("generaliza", True)),
            versao_origem=int(atual.get("version") or 1), versao_resultado=int(dados["version"]),
        )
        peticao_aprendizado.registrar_execucao(
            generation_id=str(atual.get("generation_id") or revisao_id), caso_id=caso_id,
            skill_name="semantic_diff", itens_recuperados=diff_aprovado, confidence=1.0,
        )
    except Exception:
        log.exception("aprendizado da revisão aceita não pôde ser registrado (caso %s)", caso_id)
    return dados


def descartar_revisao_pendente(caso_id: str, revisao_id: str) -> dict[str, Any]:
    atual = carregar(caso_id)
    candidata = (atual or {}).get("revisao_pendente") or {}
    if not atual or candidata.get("id") != revisao_id:
        raise ErroPeticao("Revisão pendente não encontrada.")
    dados = {k: v for k, v in atual.items() if k != "revisao_pendente"}
    descartadas = list(dados.get("revisoes_descartadas") or [])[-19:]
    descartadas.append({**candidata, "status": "REJECTED", "rejected_at": _agora()})
    dados["revisoes_descartadas"] = descartadas
    dados["revisao"] = {"tipo": "prompt", "status": "REJECTED", "id": revisao_id,
        "prompt": candidata.get("prompt", ""), "usuario": candidata.get("usuario", ""), "em": _agora()}
    try:
        # Rejeição é evidência auditável, mas nunca vira preferência reaproveitável.
        peticao_aprendizado.registrar_feedback(
            caso_id=caso_id, categoria=_categoria_do_caso(caso_id),
            advogado=str(candidata.get("usuario") or ""), texto=str(candidata.get("prompt") or ""),
            geral=False, versao_origem=int(atual.get("version") or 1),
            versao_resultado=int(atual.get("version") or 1),
        )
    except Exception:
        log.exception("evento de revisão rejeitada não pôde ser registrado (caso %s)", caso_id)
    return _salvar(caso_id, dados)


def historico_de_criticas(caso_id: str) -> list[dict[str, Any]]:
    """A rastreabilidade que a issue pede: cada crítica deste caso, quem pediu, quando."""
    try:
        peticao_criticas.inicializar()
        return peticao_criticas.listar_por_caso(caso_id)
    except Exception:
        log.warning("histórico de críticas indisponível (caso %s)", caso_id, exc_info=True)
        return []


def historico_de_versoes(caso_id: str, peca_id: str | None = None) -> list[dict[str, Any]]:
    """As versões anteriores desta petição — o que ela era antes de cada revisão."""
    if peca_id:
        return armazenamento.listar_versoes_peticao(caso_id, chave=peca_id)
    return armazenamento.listar_versoes_peticao(caso_id)


#: Quanto tempo sem digitar encerra uma "sessão de edição".
#:
#: A tela grava sozinha a cada pausa na digitação. Sem agrupar, cada pausa viraria
#: uma versão nova no histórico — dezenas por parágrafo reescrito, e o histórico
#: deixaria de servir para achar "o que a peça era antes de eu mexer". Edições
#: manuais seguidas do MESMO usuário, com intervalo menor que isto, somam-se na
#: mesma versão; a versão anterior à sessão já foi arquivada na primeira gravação.
JANELA_EDICAO_MANUAL = timedelta(
    minutes=float(os.getenv("PETICAO_JANELA_EDICAO_MINUTOS", "10"))
)


def _continua_sessao_manual(revisao: Any, usuario: str, agora: datetime) -> bool:
    if not isinstance(revisao, dict) or revisao.get("tipo") != "manual":
        return False
    if str(revisao.get("usuario") or "") != usuario:
        return False
    try:
        ultima = datetime.fromisoformat(str(revisao.get("em") or ""))
    except ValueError:
        return False
    if ultima.tzinfo is None:
        ultima = ultima.replace(tzinfo=timezone.utc)
    return timedelta(0) <= agora - ultima <= JANELA_EDICAO_MANUAL


def _aplicar_edicao_manual(
    dados: dict[str, Any], secoes: list[dict[str, str]], usuario: str
) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
    """Aplica o texto editado. Devolve `(dados, anterior, alterou)`.

    `anterior` é a versão a arquivar — `None` quando nada mudou OU quando a edição
    continua a sessão manual em curso (ver `JANELA_EDICAO_MANUAL`), caso em que a
    versão já está aberta e o arquivo do "antes" já foi feito.
    """
    anterior = json.loads(json.dumps(dados))
    por_codigo = {s["code"]: s.get("content", "") for s in secoes if s.get("code")}
    atuais = [secao for secao in dados.get("sections") or [] if secao.get("code") != "JURIMETRY"]
    novas = [
        {**secao, "content": por_codigo[secao["code"]]} if secao.get("code") in por_codigo else secao
        for secao in atuais
    ]
    alteradas = _secoes_alteradas(atuais, novas)
    dados["sections"] = novas
    if not alteradas:
        return dados, None, False
    # Uma edição manual muda a versão-base; a candidata anterior não pode mais
    # ser aceita por cima dela.
    dados.pop("revisao_pendente", None)
    agora = datetime.now(timezone.utc)
    rotulos = [str(s.get("label") or s.get("code")) for s in alteradas]
    revisao_atual = anterior.get("revisao")
    if _continua_sessao_manual(revisao_atual, usuario, agora):
        ja_alteradas = list(revisao_atual.get("alteradas") or [])
        dados["revisao"] = {
            **revisao_atual,
            "em": agora.isoformat(),
            "alteradas": ja_alteradas + [r for r in rotulos if r not in ja_alteradas],
        }
        return dados, None, True
    dados["version"] = int(anterior.get("version") or 1) + 1
    dados["revisao"] = {
        "tipo": "manual",
        "usuario": usuario,
        "em": agora.isoformat(),
        "alteradas": rotulos,
    }
    return dados, anterior, True


def salvar_secoes(
    caso_id: str, secoes: list[dict[str, str]], usuario: str = ""
) -> dict[str, Any]:
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    dados, anterior, alterou = _aplicar_edicao_manual(dados, secoes, usuario)
    if anterior is not None:
        armazenamento.registrar_versao_peticao(caso_id, anterior)
    if alterou:
        _reconferir(caso_id, dados)
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
        "generation_id": dados.get("generation_id"),
        "document_type": dados.get("document_type", "INITIAL_PETITION"),
        "status": dados.get("status", "IN_REVIEW"),
        "version": dados.get("version", 1),
        "title": dados.get("title", "Petição inicial"),
        "readiness": dados.get("readiness") or {},
        # Petições gravadas antes da conferência têm achados sem `category`, e a tela
        # faz `category.toLowerCase()`: normaliza aqui para não derrubar o cartão.
        "review": {
            **(dados.get("review") or {}),
            "findings": [_achado_legivel(a) for a in (dados.get("review") or {}).get("findings") or []],
        },
        "jurimetria": dados.get("jurimetria") or {},
        "blocking_findings": dados.get("blocking_findings", 0),
        "model": dados.get("model"),
        "created_at": dados.get("created_at", _agora()),
        "revisao": dados.get("revisao") or None,
        "revisao_pendente": dados.get("revisao_pendente") or None,
        "trace": dados.get("trace") or {},
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


#: Título de capítulo DENTRO do conteúdo: "I – PRELIMINARES", "II – DOS FATOS".
#: Romano solto, sem subdivisão. Centralizado, como na peça do escritório.
_RE_TITULO_CENTRAL = re.compile(r"^[IVXLC]+\s*[–—-]\s*\S")
#: Subtítulo numerado: "I.1 – Da Gratuidade de Justiça". Fica À ESQUERDA.
_RE_SUBTITULO = re.compile(r"^[IVXLC]+\.\d+\s*[–—-]\s*\S")
#: O endereçamento, em qualquer caixa: "Ao Juízo da Vara do Trabalho de …".
#: Centralizado e convertido para CAIXA ALTA na hora de escrever o parágrafo.
_RE_ENDERECAMENTO = re.compile(r"^(ao|à|a)\s+(ju[íi]zo|exmo|excelent[íi]ssim)", re.I)


def _tipo_de_titulo(linha: str) -> str | None:
    """`"central"`, `"esquerda"` ou `None` para linha de texto comum.

    POR QUE ISTO EXISTE

    O gerador só sabia formatar o RÓTULO da seção ("DOS FATOS"). Tudo que a IA
    escreve dentro do `content` saía como parágrafo justificado — inclusive os
    títulos que a própria peça tem por dentro. Era a diferença de layout que
    sobrava depois de acertar margens, fonte, entrelinha e recuo: comparada com
    a petição de referência, "AO JUÍZO…", "AÇÃO DE CONCESSÃO DE…" e
    "I – PRELIMINARES" apareciam como texto corrido em vez de título.

    As três formas foram medidas na referência, pelo x0 de cada linha (margem
    esquerda em 3,0 cm):

        AÇÃO DE CONCESSÃO DE AUXÍLIO-ACIDENTE   x0 = 5,74 cm  -> centralizado
        I – PRELIMINARES                        x0 = 9,06 cm  -> centralizado
        I.1 – Da Gratuidade de Justiça          x0 = 3,00 cm  -> à esquerda

    Só linha curta e sem ponto final entra. Um parágrafo inteiro em maiúsculas
    — uma citação transcrita, por exemplo — não é título e não pode virar um.
    """
    texto = linha.strip()
    if not texto or len(texto) > 90 or texto.endswith("."):
        return None
    # Título numerado vai à ESQUERDA, subtítulo também.
    #
    # "I – PRELIMINARMENTE", "V – DOS DANOS MATERIAIS" estavam saindo no meio da
    # página porque eu os medi na petição de referência antiga e concluí que eram
    # centralizados. O escritório não quer isso: título numerado acompanha os
    # demais, no canto esquerdo. Sobra UM centralizado na peça inteira — o
    # endereçamento, logo abaixo, que foi pedido expressamente.
    if _RE_SUBTITULO.match(texto) or _RE_TITULO_CENTRAL.match(texto):
        return "esquerda"
    # Endereçamento: centralizado e em CAIXA ALTA, decidido pelo escritório.
    #
    # A IA escreve "Ao Juízo da Vara do Trabalho de Tucuruí/PA" em caixa mista,
    # então nenhuma das regras acima o alcançava e ele saía como parágrafo
    # justificado com recuo, no meio do texto corrido.
    if _RE_ENDERECAMENTO.match(texto):
        return "endereco"
    if not any(c.islower() for c in texto) and any(c.isalpha() for c in texto):
        # TODO o título de seção vai à ESQUERDA — inclusive DOS FATOS, DO DIREITO
        # e DAS PROVAS, que antes iam ao centro. Era essa mistura que deixava a
        # peça "torta": uns títulos centralizados, outros à esquerda, sem critério
        # visível para quem lê. Só o endereçamento e o nome da ação ficam no
        # centro, e os dois têm regra própria.
        return "esquerda"
    return None


#: Linha de citação: `> texto`. É como um trecho de documento entra na peça.
_RE_TRECHO = re.compile(r"^\s*>\s?(.*\S.*)$")


# ------------------------------------------------------------- formatação no texto
#
# O editor da tela deixa a pessoa formatar trechos (itálico, sublinhado, tamanho,
# cor) e parágrafos (alinhamento). A formatação vive NO TEXTO da seção, como
# marcações, pelo mesmo motivo das fotos: assim ela atravessa versão, histórico,
# revisão por IA e chat sem caminho paralelo. Só o .docx sabe o que elas significam.
#
#   **negrito**                      (já existia)
#   [[i]]…[[/i]]   [[u]]…[[/u]]      itálico, sublinhado
#   [[tam=14]]…[[/tam]]              tamanho em pontos
#   [[cor=#c00000]]…[[/cor]]         cor do texto
#   [[alin=centro]] no início da linha   esquerda | centro | direita | justificado
#
# As marcações não atravessam linhas: cada linha é interpretada sozinha. Marcação
# sem par é ignorada em vez de sair literal no documento entregue ao juízo.
_RE_MARCACAO = re.compile(r"\*\*|\[\[(/?)(i|u|tam|cor)(?:=([^\]\s]*))?\]\]")
_RE_ALINHAMENTO_LINHA = re.compile(r"^\s*\[\[alin=(esquerda|centro|direita|justificado)\]\]")
_ALINHAMENTOS_DOCX = {"esquerda": "left", "centro": "center", "direita": "right", "justificado": "both"}
_RE_COR = re.compile(r"^#?[0-9a-fA-F]{6}$")
_TAMANHO_MIN_PT, _TAMANHO_MAX_PT = 6.0, 72.0


def _sem_alinhamento(linha: str) -> tuple[str | None, str]:
    """Separa o `[[alin=…]]` do começo da linha: (valor do docx ou None, resto)."""
    achado = _RE_ALINHAMENTO_LINHA.match(linha)
    if not achado:
        return None, linha
    return _ALINHAMENTOS_DOCX[achado.group(1)], linha[achado.end():]


def _trechos_formatados(linha: str) -> list[tuple[str, dict[str, Any]]]:
    """Quebra uma linha (sem o `[[alin]]`) em trechos de texto com a formatação de cada um."""
    pedacos = list(_RE_MARCACAO.finditer(linha))
    # `**` sem par no fim da linha é texto, como sempre foi (o `re.split` antigo
    # também não o casava): tratá-lo como abertura de negrito apagaria o resto.
    negritos = [m for m in pedacos if m.group(0) == "**"]
    sem_par = negritos[-1] if len(negritos) % 2 else None

    negrito = italico = sublinhado = False
    tamanhos: list[float] = []
    cores: list[str] = []
    saida: list[tuple[str, dict[str, Any]]] = []

    def emitir(texto: str) -> None:
        if not texto:
            return
        formato = {
            "b": negrito,
            "i": italico,
            "u": sublinhado,
            "tam": tamanhos[-1] if tamanhos else None,
            "cor": cores[-1] if cores else None,
        }
        if saida and saida[-1][1] == formato:
            saida[-1] = (saida[-1][0] + texto, formato)
        else:
            saida.append((texto, formato))

    posicao = 0
    for m in pedacos:
        emitir(linha[posicao:m.start()])
        posicao = m.end()
        if m.group(0) == "**":
            if m is sem_par:
                # Sem par: some, exatamente como o `.replace("**", "")` de antes.
                continue
            negrito = not negrito
            continue
        fechando, nome, valor = m.group(1) == "/", m.group(2), m.group(3)
        if nome == "i":
            italico = not fechando
        elif nome == "u":
            sublinhado = not fechando
        elif nome == "tam":
            if fechando:
                if tamanhos:
                    tamanhos.pop()
            else:
                try:
                    tamanhos.append(max(_TAMANHO_MIN_PT, min(_TAMANHO_MAX_PT, float(valor or ""))))
                except ValueError:
                    pass  # `[[tam=abc]]` não vale: a marcação some, o texto fica.
        elif nome == "cor":
            if fechando:
                if cores:
                    cores.pop()
            elif valor and _RE_COR.match(valor):
                cores.append(valor.lstrip("#").upper())
    emitir(linha[posicao:])
    return saida


def _sem_formatacao(texto: str) -> str:
    """O texto da linha sem nenhuma marcação (nem o `[[alin]]`) — para detectar título."""
    _, resto = _sem_alinhamento(texto)
    return "".join(pedaco for pedaco, _ in _trechos_formatados(resto))


def _runs_xml(
    trechos: list[tuple[str, dict[str, Any]]],
    *,
    negrito: bool = False,
    tamanho_pt: float | None = None,
    maiusculas: bool = False,
) -> str:
    """Os `<w:r>` de uma linha. `negrito` força negrito; `tamanho_pt` é o padrão do trecho."""
    runs: list[str] = []
    for texto, formato in trechos:
        if maiusculas:
            texto = texto.upper()
        # Ordem do esquema (CT_RPr): b, i, color, sz, szCs, u. O Word tolera
        # trocas, mas o LibreOffice e o validador não são obrigados a tolerar.
        props = ""
        if negrito or formato["b"]:
            props += "<w:b/>"
        if formato["i"]:
            props += "<w:i/>"
        if formato["cor"]:
            props += f'<w:color w:val="{formato["cor"]}"/>'
        tamanho = formato["tam"] or tamanho_pt
        if tamanho:
            meio_pontos = round(tamanho * 2)
            props += f'<w:sz w:val="{meio_pontos}"/><w:szCs w:val="{meio_pontos}"/>'
        if formato["u"]:
            props += '<w:u w:val="single"/>'
        runs.append(
            f'<w:r>{f"<w:rPr>{props}</w:rPr>" if props else ""}'
            f'<w:t xml:space="preserve">{escape(texto)}</w:t></w:r>'
        )
    return "".join(runs)


def _trecho_xml(texto: str, *, alinhamento: str | None = None) -> str:
    """Citação transcrita: recuo de 4 cm à esquerda, corpo menor e entrelinha simples.

    É a forma da citação direta longa (ABNT) e é o que separa, na leitura do juiz, o
    que o documento diz do que a peça argumenta. Sem o recuo, um trecho copiado de laudo
    ou de conversa parecia texto do próprio advogado.
    """
    # Sem negrito: a citação é o que o documento diz, e sempre saiu assim (o `**`
    # que a IA põe em volta de um trecho não deve virar destaque na transcrição).
    trechos = [(t, {**f, "b": False}) for t, f in _trechos_formatados(texto.strip())]
    # Citação é sempre em corpo menor; o tamanho só muda se a pessoa pediu um.
    return (
        '<w:p><w:pPr><w:spacing w:line="240" w:lineRule="auto" w:after="120"/>'
        f'<w:ind w:left="2268" w:firstLine="0"/><w:jc w:val="{alinhamento or "both"}"/></w:pPr>'
        f'{_runs_xml(trechos, tamanho_pt=10)}</w:p>'
    )


def _paragrafo_xml(
    texto: str, *, negrito: bool = False, centralizado: bool = False, visual: dict[str, Any] | None = None
) -> str:
    linhas = texto.split("\n")
    partes: list[str] = []
    for linha_bruta in linhas:
        if not linha_bruta.strip():
            partes.append("<w:p/>")
            continue
        # O alinhamento escolhido na tela vale sobre qualquer decisão automática
        # (título, fechamento, corpo): foi a pessoa que pediu, olhando a peça.
        alinhamento_pedido, linha = _sem_alinhamento(linha_bruta)
        if not linha.strip():
            partes.append("<w:p/>")
            continue
        citacao = _RE_TRECHO.match(linha)
        if citacao:
            partes.append(_trecho_xml(citacao.group(1), alinhamento=alinhamento_pedido))
            continue
        # Uma linha de TÍTULO já é negrito inteiro, então `**` ali não tem o que
        # converter — e sairia literal no documento entregue ao juízo, que foi o
        # que aconteceu em "RECLAMAÇÃO TRABALHISTA**". Tira o marcador ANTES de
        # detectar (senão o asterisco atrapalha o reconhecimento) e de escrever.
        linha_limpa = _sem_formatacao(linha)
        trechos = _trechos_formatados(linha)
        # Só vale para o CONTEÚDO: quando quem chama já mandou formatar (o
        # rótulo da seção), a decisão é dele e não se sobrepõe.
        titulo = None if (negrito or centralizado) else _tipo_de_titulo(linha_limpa)
        if titulo:
            # O endereçamento é o único que muda o TEXTO, e não só o alinhamento:
            # a IA o escreve em caixa mista ("Ao Juízo da Vara do Trabalho de
            # Tucuruí/PA") e o escritório o quer em caixa alta, centralizado.
            alinhamento = alinhamento_pedido or (
                "center" if titulo == "endereco" or (
                    titulo == "central" or str((visual or {}).get("alinhamento_titulos")) == "centralizado"
                ) else "left"
            )
            partes.append(
                f'<w:p><w:pPr><w:ind w:firstLine="0"/><w:jc w:val="{alinhamento}"/></w:pPr>'
                f'{_runs_xml(trechos, negrito=True, maiusculas=titulo == "endereco")}</w:p>'
            )
            continue
        if negrito or centralizado:
            # `firstLine="0"` ANULA o recuo padrão aqui, e não é detalhe: num
            # parágrafo centralizado o recuo de primeira linha empurra o texto
            # para a direita, e o título deixaria de ficar no centro.
            alinhamento = alinhamento_pedido or (
                "center" if centralizado or (
                    negrito and str((visual or {}).get("alinhamento_titulos")) == "centralizado"
                ) else "left"
            )
            partes.append(
                f'<w:p><w:pPr><w:ind w:firstLine="0"/><w:jc w:val="{alinhamento}"/></w:pPr>'
                f'{_runs_xml(trechos, negrito=negrito)}</w:p>'
            )
        else:
            # `**assim**` vira negrito DE VERDADE, em run próprio.
            #
            # O prompt manda o nome do autor entre asteriscos duplos, e sem esta
            # conversão eles sairiam literais no .docx — o documento entregue ao
            # juízo com `**FULANO**` escrito. `_trechos_formatados` cuida disso e
            # do `**` sem par, que some em vez de sair literal.
            if alinhamento_pedido:
                # Centralizar ou alinhar à direita com o recuo padrão de 1,25 cm
                # empurra o texto para o lado; à esquerda e justificado o recuo
                # continua sendo o do corpo da peça.
                recuo = '<w:ind w:firstLine="0"/>' if alinhamento_pedido in ("center", "right") else ""
                partes.append(
                    f'<w:p><w:pPr>{recuo}<w:jc w:val="{alinhamento_pedido}"/></w:pPr>'
                    f'{_runs_xml(trechos)}</w:p>'
                )
            else:
                partes.append(f"<w:p>{_runs_xml(trechos)}</w:p>")
    return "".join(partes)


# ------------------------------------------------------------------ fotos na peça
#
# A foto vive no TEXTO da seção, como uma linha `[[FOTO:<id do anexo>|legenda]]`.
# Assim ela passa por tudo o que já existe para texto sem caminho paralelo: versão,
# histórico, comparação antes × depois, edição manual (mover ou apagar a linha move ou
# apaga a foto) e peças anexas. Só `montar_docx` sabe que a linha é imagem.

#: Linha inteira de foto. O id é o da ENTREGA — é ele que acha o arquivo no acervo.
_RE_FOTO = re.compile(r"^\s*\[\[FOTO:([\w-]+)(?:\|([^\]]*))?\]\]\s*$")
_EXTENSOES_DE_FOTO = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif")
#: Foto de celular chega com 4000 px e 5 MB; numa peça, 1600 px bastam e o .docx
#: continua anexável no PJe.
_LADO_MAXIMO_PX = 1600
#: Uma foto de pé não pode ocupar a página inteira e empurrar o texto para a próxima.
_ALTURA_MAXIMA_FOTO_CM = 12.0


def eh_foto(arquivo: str) -> bool:
    return Path(str(arquivo or "")).suffix.lower() in _EXTENSOES_DE_FOTO


def marcador_de_foto(anexo_id: str, legenda: str = "") -> str:
    # `]` e `|` fechariam o marcador antes da hora e a legenda sairia cortada.
    legenda = " ".join(str(legenda or "").replace("]", ")").replace("|", "/").split())
    return f"[[FOTO:{anexo_id}|{legenda}]]" if legenda else f"[[FOTO:{anexo_id}]]"


def _marcadores_de_foto(conteudo: Any) -> list[str]:
    return [linha.strip() for linha in str(conteudo or "").split("\n") if _RE_FOTO.match(linha)]


def preparar_foto(anexo_id: str) -> tuple[bytes, int, int] | None:
    """A foto como JPEG pronto para o Word: `(bytes, largura_px, altura_px)`.

    Gira pelo EXIF antes de tudo: foto de celular vem "deitada" no arquivo com a
    rotação só anotada, e o Word não lê essa anotação — o machucado sairia de lado.
    Transparência vira fundo branco e o lado maior cai para 1600 px. `None` quando
    o anexo não existe ou não abre como imagem (PDF, HEIC sem decodificador).
    """
    entrega = armazenamento.obter_entrega(anexo_id)
    if not entrega:
        return None
    caminho = armazenamento.caminho_duravel_da_entrega(anexo_id)
    bruto = caminho.read_bytes() if caminho else armazenamento.conteudo_arquivo_entrega(entrega)
    if not bruto:
        return None
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(bruto)) as original:
            imagem = ImageOps.exif_transpose(original)
            if imagem.mode not in ("RGB", "L"):
                rgba = imagem.convert("RGBA")
                imagem = Image.new("RGB", rgba.size, "white")
                imagem.paste(rgba, mask=rgba.getchannel("A"))
            imagem = imagem.convert("RGB")
            imagem.thumbnail((_LADO_MAXIMO_PX, _LADO_MAXIMO_PX))
            saida = io.BytesIO()
            imagem.save(saida, "JPEG", quality=85)
            return saida.getvalue(), imagem.width, imagem.height
    except Exception as erro:  # noqa: BLE001 — anexo ilegível vira pendência na peça
        log.warning("foto %s não abriu como imagem: %s", anexo_id, erro)
        return None


def _largura_util_cm(visual: dict[str, Any]) -> float:
    esquerda = max(1, min(6, float(visual["margem_esquerda_cm"])))
    direita = max(1, min(6, float(visual["margem_direita_cm"])))
    return 21.0 - esquerda - direita


def _foto_xml(linha: str, *, fotos: list[tuple[str, bytes]], visual: dict[str, Any]) -> str:
    """A foto centralizada, com a legenda em itálico logo abaixo.

    `fotos` acumula `(rId, jpeg)` para `montar_docx` gravar em `word/media`.
    """
    achado = _RE_FOTO.match(linha)
    anexo_id, legenda = achado.group(1), (achado.group(2) or "").strip()
    sem_recuo = '<w:ind w:firstLine="0"/>'
    foto = preparar_foto(anexo_id)
    if foto is None:
        # Nunca some em silêncio: o advogado precisa ver que ali faltou a foto.
        aviso = escape(f"[PENDENTE: foto não encontrada nos anexos{' — ' + legenda if legenda else ''}]")
        return (
            f'<w:p><w:pPr>{sem_recuo}<w:jc w:val="center"/></w:pPr>'
            f'<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{aviso}</w:t></w:r></w:p>'
        )
    jpeg, largura_px, altura_px = foto
    # Não amplia além de ~150 dpi: foto pequena esticada até a margem fica borrada.
    largura_cm = min(_largura_util_cm(visual), largura_px / 150 * 2.54)
    altura_cm = largura_cm * altura_px / largura_px
    if altura_cm > _ALTURA_MAXIMA_FOTO_CM:
        altura_cm = _ALTURA_MAXIMA_FOTO_CM
        largura_cm = altura_cm * largura_px / altura_px
    cx, cy = round(largura_cm * 360000), round(altura_cm * 360000)
    numero = len(fotos) + 1
    rel_id = f"rIdFoto{numero}"
    fotos.append((rel_id, jpeg))
    # id 1 é a logo do cabeçalho; as fotos começam em 100 para nunca colidir.
    doc_id = 100 + numero
    nome = escape(legenda or f"Foto {numero}", {'"': "&quot;"})
    xml = (
        f'<w:p><w:pPr><w:keepNext/>{sem_recuo}<w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{doc_id}" name="{nome}"/>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{doc_id}" name="foto-{numero}.jpeg"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )
    if legenda:
        xml += (
            f'<w:p><w:pPr>{sem_recuo}<w:jc w:val="center"/></w:pPr>'
            f'<w:r><w:rPr><w:i/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>'
            f'<w:t xml:space="preserve">{escape(legenda)}</w:t></w:r></w:p>'
        )
    return xml


def _preservar_fotos(
    antes: list[dict[str, Any]], depois: list[dict[str, Any]], critica: str
) -> list[dict[str, Any]]:
    """Devolve à revisão as fotos que a IA deixou cair.

    O modelo reescreve a seção inteira e trata `[[FOTO:…]]` como ruído; sem isto,
    pedir "melhore os fatos" apagava a foto do machucado. Se a crítica fala de foto
    ou imagem, quem decide é ela (tirar ou mover é pedido legítimo).
    """
    if re.search(r"\b(fotos?|imagens?|figuras?)\b", critica or "", re.IGNORECASE):
        return depois
    resultado = [dict(s) for s in depois]
    if not resultado:
        return resultado
    presentes = {m for s in resultado for m in _marcadores_de_foto(s.get("content"))}
    por_codigo = {s.get("code"): s for s in resultado}
    for secao in antes:
        faltando = [m for m in _marcadores_de_foto(secao.get("content")) if m not in presentes]
        if not faltando:
            continue
        destino = por_codigo.get(secao.get("code")) or resultado[-1]
        destino["content"] = str(destino.get("content") or "").rstrip() + "\n\n" + "\n".join(faltando)
        presentes.update(faltando)
    return resultado


def _preservar_citacoes(
    antes: list[dict[str, Any]], depois: list[dict[str, Any]], critica: str
) -> list[dict[str, Any]]:
    """Devolve à revisão as citações literais de documento que a IA parafraseou ou deixou cair.

    Mesma ideia das fotos: o modelo reescreve a seção inteira e trata `> …` como texto
    seu. Citação alterada deixa de ser citação — e ninguém percebe, porque parece igual.
    Se a crítica fala de citação/trecho, quem decide é ela.
    """
    if re.search(r"\b(cita[çc][ãa]o|cita[çc][õo]es|trechos?|transcri[çc][ãa]o|transcri[çc][õo]es)\b", critica or "", re.IGNORECASE):
        return depois
    resultado = [dict(s) for s in depois]
    if not resultado:
        return resultado

    def citacoes(conteudo: Any) -> list[str]:
        return [linha.strip() for linha in str(conteudo or "").split("\n") if _RE_TRECHO.match(linha)]

    presentes = {c for s in resultado for c in citacoes(s.get("content"))}
    por_codigo = {s.get("code"): s for s in resultado}
    for secao in antes:
        faltando = [c for c in citacoes(secao.get("content")) if c not in presentes]
        if not faltando:
            continue
        destino = por_codigo.get(secao.get("code")) or resultado[-1]
        destino["content"] = str(destino.get("content") or "").rstrip() + "\n\n" + "\n\n".join(faltando)
        presentes.update(faltando)
    return resultado


def _achar_secao(secoes: list[dict[str, Any]], secao: str) -> dict[str, Any]:
    """Pelo código ("FACTS") ou pelo rótulo ("Dos fatos"); vazio = última seção."""
    procurado = _sem_acento(secao).strip().lower()
    if procurado:
        for candidata in secoes:
            codigo = str(candidata.get("code") or "").lower()
            rotulo = _sem_acento(str(candidata.get("label") or "")).lower()
            if procurado in (codigo, rotulo) or (len(procurado) >= 4 and procurado in rotulo):
                return candidata
        raise ErroPeticao(
            f"Não achei a seção «{secao}» na petição. Seções: "
            + "; ".join(str(s.get("label") or s.get("code")) for s in secoes)
        )
    return secoes[-1]


def inserir_foto(
    caso_id: str,
    anexo_id: str,
    *,
    secao: str = "",
    depois_de: str = "",
    legenda: str = "",
    usuario: str = "",
) -> dict[str, Any]:
    """Põe uma foto do caso dentro da petição, sem IA no meio.

    `secao` vazio = fim da petição (última seção). `depois_de` é um trecho do texto:
    a foto entra logo abaixo do parágrafo que o contém; sem ele, no fim da seção.
    Vira edição manual comum — versão nova, histórico, desfazível.
    """
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    entrega = armazenamento.obter_entrega(anexo_id)
    if not entrega or str(entrega.get("caso_id")) != str(caso_id):
        raise ErroPeticao("Esse anexo não é deste caso.")
    arquivo = str(entrega.get("arquivo") or "")
    if not eh_foto(arquivo):
        raise ErroPeticao(f"«{arquivo}» não é uma foto (jpg, png…).")
    if preparar_foto(anexo_id) is None:
        raise ErroPeticao(f"Não consegui abrir «{arquivo}» como imagem.")

    secoes = [s for s in dados.get("sections") or [] if s.get("code") != "JURIMETRY"]
    if not secoes:
        raise ErroPeticao("A petição não tem seções.")
    alvo = _achar_secao(secoes, secao)
    marcador = marcador_de_foto(anexo_id, legenda)
    linhas = str(alvo.get("content") or "").rstrip().split("\n")
    posicao = "no fim da seção"
    trecho = _sem_acento(" ".join(depois_de.split())).lower()
    indice = next(
        (i for i, linha in enumerate(linhas) if trecho and trecho in _sem_acento(" ".join(linha.split())).lower()),
        None,
    )
    if indice is not None:
        linhas[indice + 1:indice + 1] = ["", marcador, ""]
        posicao = "logo abaixo do parágrafo indicado"
    else:
        if depois_de.strip():
            posicao = "no fim da seção (não achei o trecho indicado)"
        linhas += ["", marcador]
    conteudo = "\n".join(linhas)
    peticao = salvar_secoes(caso_id, [{"code": str(alvo.get("code")), "content": conteudo}], usuario)
    return {
        "peticao": peticao,
        "secao": str(alvo.get("label") or alvo.get("code")),
        "posicao": posicao,
        "arquivo": arquivo,
    }


#: Teto de um trecho citado: acima disso é transcrever o documento, não citá-lo.
LIMITE_TRECHO = 1500


def _compacto(texto: str) -> str:
    """Sem acento, sem caixa e com espaço/quebra de linha colapsados: a base da conferência
    de um trecho contra o texto que o OCR leu (que quebra linha no meio da frase)."""
    return " ".join(_sem_acento(str(texto or "")).lower().split())


def trecho_esta_no_documento(texto_do_documento: str, trecho: str) -> bool:
    """`True` só quando o trecho aparece, palavra por palavra, no texto lido do documento.

    A citação vai para uma peça entregue ao juízo: um trecho «de memória», mesmo quase
    igual, é citação falsa. Espaço e acento não contam; palavra trocada conta.
    """
    alvo = _compacto(trecho)
    return len(alvo) >= 8 and alvo in _compacto(texto_do_documento)


def inserir_trecho(
    caso_id: str,
    anexo_id: str,
    trecho: str,
    *,
    secao: str = "",
    depois_de: str = "",
    usuario: str = "",
) -> dict[str, Any]:
    """Põe um trecho LITERAL de um documento do caso dentro da petição, sem IA no meio.

    Entra como citação (`> trecho (Fonte: tipo — arquivo)`), com a fonte ao lado. Recusa
    o que não está no texto lido do documento. Vira edição manual comum: versão nova,
    histórico, desfazível.
    """
    trecho = " ".join(str(trecho or "").split())
    if not trecho:
        raise ErroPeticao("Diga qual trecho do documento deve entrar na petição.")
    if len(trecho) > LIMITE_TRECHO:
        raise ErroPeticao(
            f"O trecho tem {len(trecho)} caracteres; o máximo é {LIMITE_TRECHO}. Cite só a passagem que interessa."
        )
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    anexo = next((a for a in anexos_do_caso(caso_id) if a["id"] == str(anexo_id)), None)
    if not anexo:
        raise ErroPeticao("Esse anexo não é deste caso.")
    if not trecho_esta_no_documento(anexo["texto"], trecho):
        raise ErroPeticao(
            f"Esse trecho não aparece no texto lido de «{anexo['arquivo']}». Só entra na petição"
            " o que o documento diz, palavra por palavra."
        )
    secoes = [s for s in dados.get("sections") or [] if s.get("code") != "JURIMETRY"]
    if not secoes:
        raise ErroPeticao("A petição não tem seções.")
    alvo = _achar_secao(secoes, secao)
    fonte = f"{anexo['tipo']} — {anexo['arquivo']}" if anexo["tipo"] else anexo["arquivo"]
    citacao = f"> {trecho} (Fonte: {fonte})"
    linhas = str(alvo.get("content") or "").rstrip().split("\n")
    posicao = "no fim da seção"
    procurado = _compacto(depois_de)
    indice = next((i for i, linha in enumerate(linhas) if procurado and procurado in _compacto(linha)), None)
    if indice is not None:
        linhas[indice + 1:indice + 1] = ["", citacao, ""]
        posicao = "logo abaixo do parágrafo indicado"
    else:
        if depois_de.strip():
            posicao = "no fim da seção (não achei o trecho indicado)"
        linhas += ["", citacao]
    peticao = salvar_secoes(caso_id, [{"code": str(alvo.get("code")), "content": "\n".join(linhas)}], usuario)
    return {
        "peticao": peticao,
        "secao": str(alvo.get("label") or alvo.get("code")),
        "posicao": posicao,
        "arquivo": anexo["arquivo"],
    }


_RE_SEPARADOR_TABELA = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _celulas_tabela_markdown(linha: str) -> list[str]:
    """Lê uma linha de tabela Markdown sem deixar ``|`` virar texto no Word."""
    limpa = linha.strip()
    if limpa.startswith("|"):
        limpa = limpa[1:]
    if limpa.endswith("|"):
        limpa = limpa[:-1]
    return [celula.strip() for celula in limpa.split("|")]


def _tabela_xml(cabecalho: list[str], linhas: list[list[str]]) -> str:
    """Uma tabela Word nativa, com bordas e expansão automática de linhas.

    O conteúdo chega da IA em Markdown somente como uma representação transitória.
    O DOCX final recebe ``w:tbl`` editável, nunca barras, tabs ou imagem.
    """
    colunas = max(2, len(cabecalho), *(len(linha) for linha in linhas))
    cabecalho = (cabecalho + [""] * colunas)[:colunas]
    linhas = [(linha + [""] * colunas)[:colunas] for linha in linhas]
    # A tabela de dados contratuais do escritório usa rótulo mais estreito e valor
    # mais largo. Para outras estruturas, as colunas ficam proporcionais e legíveis.
    # Uma largura ligeiramente menor que a área útil deixa a tabela respirar dentro
    # da página, em vez de parecer uma grade colada às margens. O valor é em twips.
    largura_total = 7800
    if colunas == 2:
        larguras = [2400, 5400]
    else:
        base, resto = divmod(largura_total, colunas)
        larguras = [base + (1 if indice < resto else 0) for indice in range(colunas)]

    def celula(texto: str, largura: int, *, destaque: bool = False) -> str:
        # A célula é texto simples: formatação de trecho feita na tela sobre uma
        # linha de tabela não pode sair literal (`[[i]]`) dentro da grade.
        texto = "\n".join(_sem_formatacao(parte) for parte in str(texto or "").split("\n"))
        partes = texto.split("\n") or [""]
        runs = "".join(
            f'<w:r><w:rPr>{"<w:b/>" if destaque else ""}</w:rPr><w:t xml:space="preserve">{escape(parte)}</w:t></w:r>'
            + ("<w:r><w:br/></w:r>" if indice < len(partes) - 1 else "")
            for indice, parte in enumerate(partes)
        )
        return (
            f'<w:tc><w:tcPr><w:tcW w:w="{largura}" w:type="dxa"/>'
            '<w:vAlign w:val="center"/></w:tcPr>'
            f'<w:p><w:pPr><w:jc w:val="left"/><w:ind w:firstLine="0"/></w:pPr>{runs}</w:p></w:tc>'
        )

    def linha(valores: list[str], *, destaque: bool = False) -> str:
        return "<w:tr>" + "".join(
            celula(valor, larguras[indice], destaque=destaque)
            for indice, valor in enumerate(valores)
        ) + "</w:tr>"

    return (
        f'<w:tbl><w:tblPr><w:tblW w:w="{largura_total}" w:type="dxa"/><w:jc w:val="center"/>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/></w:tblBorders>'
        '<w:tblCellMar><w:top w:w="50" w:type="dxa"/><w:left w:w="50" w:type="dxa"/>'
        '<w:bottom w:w="50" w:type="dxa"/><w:right w:w="50" w:type="dxa"/></w:tblCellMar>'
        '</w:tblPr><w:tblGrid>'
        + "".join(f'<w:gridCol w:w="{largura}"/>' for largura in larguras)
        + "</w:tblGrid>"
        + linha(cabecalho, destaque=True)
        + "".join(linha(valores) for valores in linhas)
        + "</w:tbl>"
    )


def _conteudo_com_tabelas_xml(
    conteudo: str,
    *,
    centralizado: bool,
    visual: dict[str, Any],
    fotos: list[tuple[str, bytes]] | None = None,
) -> str:
    """Converte blocos Markdown de tabela (e linhas de foto), mantendo a posição."""
    # Linha de tabela ou de foto pode ter ganhado um `[[alin=…]]` na tela; o
    # marcador não pode esconder a `|` nem o `[[FOTO:…]]` do reconhecimento. As
    # linhas comuns seguem com o marcador, que `_paragrafo_xml` sabe ler.
    linhas = [
        linha if not _RE_ALINHAMENTO_LINHA.match(linha) or not (
            "|" in linha or "[[FOTO:" in linha
        ) else _sem_alinhamento(linha)[1].lstrip()
        for linha in conteudo.split("\n")
    ]
    partes: list[str] = []
    comum: list[str] = []

    def descarregar_comum() -> None:
        nonlocal comum
        if comum:
            partes.append(_paragrafo_xml("\n".join(comum), centralizado=centralizado, visual=visual))
            comum = []

    indice = 0
    while indice < len(linhas):
        atual = linhas[indice]
        proxima = linhas[indice + 1] if indice + 1 < len(linhas) else ""
        if fotos is not None and _RE_FOTO.match(atual):
            descarregar_comum()
            partes.append(_foto_xml(atual, fotos=fotos, visual=visual))
            indice += 1
            continue
        if "|" in atual and _RE_SEPARADOR_TABELA.match(proxima):
            cabecalho = _celulas_tabela_markdown(atual)
            tabela: list[list[str]] = []
            indice += 2
            while indice < len(linhas) and "|" in linhas[indice] and linhas[indice].strip():
                tabela.append(_celulas_tabela_markdown(linhas[indice]))
                indice += 1
            if len(cabecalho) >= 2 and tabela:
                descarregar_comum()
                partes.append(_tabela_xml(cabecalho, tabela))
                partes.append("<w:p/>")
                continue
            comum.extend([atual, proxima])
            continue
        comum.append(atual)
        indice += 1
    descarregar_comum()
    return "".join(partes)


def montar_docx(secoes: list[dict[str, Any]]) -> bytes:
    logo, fonte, logo_extensao, _origem_visual = identidade_visual()
    visual = configuracao_visual()
    fonte = str(visual.get("fonte") or fonte).strip() or fonte
    fonte_xml = escape(fonte, {'"': "&quot;"})
    def twips(cm: float) -> int:
        return round(cm / 2.54 * 1440)
    tamanho = max(8, min(24, float(visual["tamanho_fonte_pt"])))
    entrelinha = max(1, min(3, float(visual["espacamento_linha"])))
    recuo = max(0, min(5, float(visual["recuo_primeira_linha_cm"])))
    margem_topo = max(1.5, min(7, float(visual["margem_superior_cm"])))
    margem_direita = max(1, min(6, float(visual["margem_direita_cm"])))
    margem_inferior = max(1, min(6, float(visual["margem_inferior_cm"])))
    margem_esquerda = max(1, min(6, float(visual["margem_esquerda_cm"])))
    altura_logo = max(0.5, min(5, float(visual["altura_logo_cm"])))
    logo_cy = round(altura_logo * 360000)
    logo_cx = round(logo_cy * 1.774)
    alinhamento_corpo = {"justificado": "both", "esquerda": "left", "direita": "right"}.get(str(visual.get("alinhamento_corpo")), "both")
    logo_arquivo = f"logo-escritorio{logo_extensao}"
    logo_content_type = "image/jpeg" if logo_extensao == ".jpg" else "image/png"
    corpo: list[str] = []
    fotos: list[tuple[str, bytes]] = []
    for secao in secoes:
        if secao.get("code") == "JURIMETRY":
            continue
        rotulo = str(secao.get("label") or secao.get("code") or "").strip()
        conteudo = str(secao.get("content") or "").strip()
        # VALUE entra junto de HEADING e CLOSING: o valor da causa NÃO tem título
        # na peça do escritório — é uma frase solta ("Dá-se à causa o valor de
        # ..."). O rótulo continua existindo em `SECOES` porque a tela e o prompt
        # se orientam por ele; só não vira parágrafo no .docx.
        if rotulo and secao.get("code") not in ("HEADING", "CLOSING", "VALUE"):
            # `centralizado=False`: o rótulo da seção fica À ESQUERDA.
            #
            # Estava centralizado, e era metade do problema — "DOS FATOS",
            # "DO DIREITO" e "DAS PROVAS" apareciam no meio da página enquanto
            # os subtítulos de dentro do conteúdo iam à esquerda. O escritório
            # quer todos à esquerda; só o endereçamento e o nome da ação ficam
            # no centro.
            corpo.append(_paragrafo_xml(rotulo.upper(), negrito=True, visual=visual))
        if conteudo:
            # O HEADING NÃO é centralizado por inteiro.
            #
            # Centralizar a seção toda punha a qualificação do autor no meio da
            # página, e na peça de referência ela é justificada com recuo, como
            # qualquer parágrafo — só o endereçamento ("Ao Juízo…") e o nome da
            # ação ficam centralizados. Como efeito colateral, o bloco inteiro
            # caía no ramo de título e a conversão de `**negrito**` nunca rodava:
            # o nome do autor saía com os asteriscos literais no documento.
            #
            # Quem decide agora é `_tipo_de_titulo`, linha a linha.
            corpo.append(
                _conteudo_com_tabelas_xml(
                    conteudo,
                    centralizado=secao.get("code") == "CLOSING",
                    visual=visual,
                    fotos=fotos,
                )
            )
        corpo.append("<w:p/>")

    documento_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    {"".join(corpo)}
    <w:sectPr>
      <w:headerReference w:type="default" r:id="rIdHeader"/>
      <w:pgSz w:w="11906" w:h="16838"/>
      <!-- Medido na petição de referência do escritório, página a página (as
           quatro primeiras dão exatamente o mesmo recorte):

             esquerda  3,00 cm = 1701 twips
             direita   1,89 cm = 1069 twips
             rodapé    1,25 cm =  708 twips
             header    1,25 cm =  708 twips  (onde o timbre começa)
             topo      4,66 cm = 2642 twips  (onde o TEXTO começava)

           `w:top` é onde o corpo começa, não a borda do papel: entre 1,25 cm e
           `w:top` fica a logo, que é cabeçalho e se repete em toda página. Com
           `w:top` menor que isso o texto subiria por cima do timbre.

           Com a logo reduzida a 2,36 cm de altura, o timbre acaba em 3,61 cm.
           Mantendo a mesma folga de 0,13 cm da peça de referência, o texto passa
           a começar em 3,74 cm = 2120 twips. Sem descer `w:top` junto sobraria
           quase 1 cm de ar entre a logo e o primeiro parágrafo. -->
      <w:pgMar w:top="{twips(margem_topo)}" w:right="{twips(margem_direita)}" w:bottom="{twips(margem_inferior)}" w:left="{twips(margem_esquerda)}" w:header="708"/>
    </w:sectPr>
  </w:body>
</w:document>"""

    # f-string: sem o `f`, `{logo_cx}` ia literal para o XML e o Word recusava abrir
    # o arquivo inteiro (o LibreOffice, que gera o PDF, tolerava e escondia o defeito).
    cabecalho_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <!-- A logo já era centralizada, mas na ÁREA ÚTIL — e as margens são
       assimétricas (3,00 cm à esquerda, 1,89 cm à direita, medidas na peça de
       referência). O centro da área útil cai 0,55 cm à direita do centro da
       FOLHA, e é isso que se vê como logo fora do meio.

       `w:right="629"` (1,11 cm, a diferença entre as margens) devolve o
       parágrafo ao centro do papel, que é onde o olho espera o timbre. -->
  <w:p><w:pPr><w:jc w:val="center"/><w:ind w:right="629"/></w:pPr><w:r><w:drawing>
    <wp:inline distT="0" distB="0" distL="0" distR="0">
      <!-- 4,19 × 2,36 cm em EMU (1 cm = 360000). O timbre da peça de referência
           tem 5,82 × 3,28 cm; este é ele a 72%, por pedido do escritório. Os dois
           lados usam o mesmo fator, então a proporção 1,77 se mantém e a imagem
           encolhe sem distorcer. Mexer aqui obriga a mexer no `w:top` do sectPr. -->
      <wp:extent cx="{logo_cx}" cy="{logo_cy}"/><wp:docPr id="1" name="Logo do escritório"/>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="logo-escritorio"/><pic:cNvPicPr/></pic:nvPicPr>
          <pic:blipFill><a:blip r:embed="rIdLogo"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
          <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{logo_cx}" cy="{logo_cy}"/></a:xfrm>
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
      <w:sz w:val="{round(tamanho * 2)}"/><w:szCs w:val="{round(tamanho * 2)}"/><w:lang w:val="pt-BR"/>
    </w:rPr></w:rPrDefault>
    <!-- `firstLine="709"` = 1,25 cm de recuo na primeira linha de cada parágrafo.
         Medido na petição de referência: o corpo começa em 3,0 cm e a primeira
         linha de cada parágrafo em 4,25 cm — 20 linhas do documento confirmam
         essa segunda coluna. Sem isso o texto sai em bloco corrido, que foi a
         diferença apontada ao comparar a peça gerada com a do escritório. -->
    <w:pPrDefault><w:pPr><w:jc w:val="{alinhamento_corpo}"/><w:spacing w:line="{round(entrelinha * 240)}" w:lineRule="auto"/><w:ind w:firstLine="{twips(recuo)}"/></w:pPr></w:pPrDefault>
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
  {'<Default Extension="jpeg" ContentType="image/jpeg"/>' if fotos else ""}
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
        # `.jpeg`, e não `.jpg`: a logo pode ser `.jpg`, e dois <Default> para a
        # mesma extensão tornam o pacote inválido para o Word.
        relacoes_fotos = ""
        for rel_id, jpeg in fotos:
            numero = rel_id.removeprefix("rIdFoto")
            arquivo.writestr(f"word/media/foto-{numero}.jpeg", jpeg)
            relacoes_fotos += (
                f'\n  <Relationship Id="{rel_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/foto-{numero}.jpeg"/>'
            )
        arquivo.writestr(
            "word/_rels/document.xml.rels",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>{relacoes_fotos}
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
