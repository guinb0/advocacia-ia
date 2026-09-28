"""Cadastro do caso, carteira, painel, panorama e portal do cliente."""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
)
from pydantic import BaseModel

from .. import (
    armazenamento,
    auth,
    carteira,
    casos,
    categorias,
    panorama,
)
from .. import (
    painel as painel_do_caso,
)
from ..cache_leitura import por_alguns_segundos
from .comum import URL_PORTAL, _criar_portal

roteador = APIRouter()


@roteador.post("/api/casos", status_code=201)
def criar_caso(
    cliente: str = Form(...),
    categoria: str = Form(...),
    observacao: str = Form(""),
    #: O WhatsApp que a entrevista colheu. Opcional porque o caso também nasce
    #: pela carteira, digitado à mão, onde ninguém perguntou telefone ainda.
    telefone: str = Form(""),
    tipo_acao: str = Form(""),
):
    """Cria o caso já com o portal do cliente pronto.

    O link nasce junto com o caso porque é isso que o escritório manda ao cliente
    logo depois de abrir o processo. A senha vai NESTA resposta e em nenhuma
    outra — o banco guarda apenas o hash.
    """
    if not cliente.strip():
        raise HTTPException(400, "Informe o nome do cliente.")
    # A ação exibida é livre; a categoria continua técnica para preservar o
    # checklist. O fallback evita que uma tese nova impeça a abertura do caso.
    if categorias.obter(categoria) is None:
        categoria = "em_triagem"

    caso = armazenamento.criar_caso(cliente, categoria, observacao, telefone, tipo_acao)
    listar_casos.limpar_cache()  # type: ignore[attr-defined]
    return {**caso, "portal": _criar_portal(caso["id"])}


class QualificacaoCliente(BaseModel):
    """A qualificação do cliente colhida na entrevista — consulta por CPF ou à mão.

    Toda opcional: o campo em branco vira NULL na tabela `qualificacao`, porque
    "não informado" não é o mesmo que "" para quem for ler o cadastro depois.
    """

    cpf: str = ""
    nascimento: str = ""
    sexo: str = ""
    nome_mae: str = ""
    cep: str = ""
    endereco: str = ""
    email: str = ""
    renda_estimada: str = ""
    # Digitados na tela desde sempre, usados pelo contrato e perdidos ao salvar
    # até aqui — a tabela não tinha onde guardá-los (ver `CAMPOS_QUALIFICACAO`).
    idade: str = ""
    nacionalidade: str = ""
    profissao: str = ""
    estado_civil: str = ""
    rg: str = ""
    rg_orgao: str = ""
    rg_uf: str = ""
    nome_pai: str = ""
    pis: str = ""
    uf: str = ""
    municipio: str = ""
    # O que a consulta por CPF devolve além do primeiro item de cada lista.
    telefones_extras: str = ""
    emails_extras: str = ""
    enderecos_extras: str = ""


@roteador.put("/api/casos/{caso_id}/qualificacao")
def gravar_qualificacao(caso_id: str, dados: QualificacaoCliente):
    """Grava (upsert) a qualificação do cliente numa tabela à parte, 1:1 com o caso.

    Fica separada de `casos` de propósito: o caso segue enxuto e o cadastro
    completo — o que a consulta por CPF traz e o que a atendente digita — tem
    onde morar. Campo vazio não vira "", vira ausência (NULL).
    """
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    armazenamento.salvar_qualificacao(caso_id, dados.model_dump())
    return {"ok": True}


@roteador.get("/api/casos")
@por_alguns_segundos(5)
def listar_casos():
    return {"casos": armazenamento.listar_casos()}


@roteador.get("/api/carteira")
def fila_da_carteira(
    pagina: int = 1,
    tamanho: int = carteira.TAMANHO_PADRAO,
    busca: str = "",
    categoria: str = "",
    situacao: str = "",
    ordenar: str = "recente",
):
    """A fila de casos da carteira, uma página por vez.

    Substitui o `GET /api/casos` seguido de um `GET /api/casos/{id}` por caso que a tela
    fazia: eram N+1 requisições e a carteira inteira no navegador. Aqui são duas consultas
    e só a página pedida no payload — mas a ordem por risco e os contadores do topo são
    medidos sobre a carteira toda (ver `app/carteira.py`).

    `busca`, `categoria` e `situacao` recortam a lista no servidor, para o filtro valer
    na carteira inteira e não só na página aberta; `ordenar` troca a ordem da fila.
    """
    return carteira.montar(
        pagina=pagina,
        tamanho=tamanho,
        busca=busca,
        categoria=categoria,
        situacao=situacao,
        ordenar=ordenar,
    )


@roteador.get("/api/follow-up")
def relatorio_follow_up(_usuario: auth.Usuario = Depends(auth.exigir_modulo("casos"))):
    """Relatório operacional: clientes com documento obrigatório pendente.

    Nome, telefone, documentos faltantes e alerta de quando o follow-up por
    WhatsApp não resolve e é preciso LIGAR (ver `carteira.relatorio_follow_up`).
    """
    return carteira.relatorio_follow_up()


@roteador.get("/api/casos/{caso_id}/ligacoes")
def list_case_calls(
    caso_id: str,
    _usuario: auth.Usuario = Depends(auth.exigir_modulo("casos")),
):
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    return {"calls": armazenamento.list_calls(caso_id)}


@roteador.post("/api/casos/{caso_id}/ligacoes", status_code=201)
def register_case_call(
    caso_id: str,
    usuario: auth.Usuario = Depends(auth.exigir_modulo("casos")),
):
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    return armazenamento.register_call(caso_id, usuario.id, usuario.nome)


@roteador.get("/api/casos/{caso_id}")
def obter_caso(caso_id: str):
    situacao = casos.montar_situacao(caso_id)
    if situacao is None:
        raise HTTPException(404, "Caso não encontrado.")
    # "Nada passa despercebido": item de carteira que falta, mas cujo dado (CTPS,
    # PIS) aparece em outro anexo, ganha a observação de onde foi encontrado.
    # A leitura agora é feita em lote sobre as extrações persistidas, sem abrir
    # cada entrega nem consultar o agente jurídico uma vez por arquivo.
    casos.anexar_observacoes_cruzadas(caso_id, situacao)
    return situacao


@roteador.get("/api/casos/{caso_id}/painel")
def painel_do_caso_analitico(caso_id: str):
    """Painel analítico do caso: histórico medido, comparação e riscos.

    Leitura pesada de propósito — passa pelo dossiê (que consulta o agente) e pelos casos
    anteriores da mesma categoria para montar a referência. É uma tela que se abre para
    estudar o caso, não um polling: quem quer só o estado atual usa `/api/casos/{id}`.
    """
    montado = painel_do_caso.montar(caso_id)
    if montado is None:
        raise HTTPException(404, "Caso não encontrado.")
    return montado


@roteador.get("/api/panorama")
def panorama_do_escritorio():
    """Painel analítico de todos os casos: o mesmo tipo de leitura, uma escala acima.

    Existe para que o gestor responda "como o escritório está andando" sem abrir caso
    por caso. Mede com as mesmas funções do painel do caso (`app/panorama.py` importa
    `painel.marcos_do_caso` e `painel.medir_etapas`), então os números das duas telas
    fecham entre si.

    Cinco consultas independentemente do tamanho da carteira, e nenhuma chamada ao
    agente jurídico — o que dependeria dele está declarado em `ausencias`.

    Não leva `exigir_papel`: o middleware `exigir_autenticacao` já fecha toda rota que
    não esteja em `LIVRES_SEM_ADVOGADO` para quem não é advogado ou secretário, e esta
    atravessa o acervo inteiro.
    """
    return panorama.montar()


@roteador.patch("/api/casos/{caso_id}")
def atualizar_caso(
    caso_id: str,
    cliente: str | None = Form(None),
    observacao: str | None = Form(None),
    telefone: str | None = Form(None),
    categoria: str | None = Form(None),
):
    if categoria is not None and categorias.obter(categoria) is None:
        raise HTTPException(400, f"Categoria '{categoria}' não existe.")
    if not armazenamento.atualizar_caso(caso_id, cliente, observacao, telefone, categoria):
        raise HTTPException(404, "Caso não encontrado ou nada para atualizar.")
    listar_casos.limpar_cache()  # type: ignore[attr-defined]
    return armazenamento.obter_caso(caso_id)


@roteador.delete("/api/casos/{caso_id}")
def excluir_caso(caso_id: str):
    if not armazenamento.excluir_caso(caso_id):
        raise HTTPException(404, "Caso não encontrado.")
    listar_casos.limpar_cache()  # type: ignore[attr-defined]
    return {"removido": True}


@roteador.post("/api/casos/{caso_id}/portal", status_code=201)
def gerar_portal(caso_id: str):
    """Troca a senha do portal. O link e a senha anteriores param de valer.

    Serve para casos criados antes do portal existir e para quando o cliente
    perde a senha — que não tem como ser recuperada, só substituída.
    """
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    return _criar_portal(caso_id)


@roteador.get("/api/casos/{caso_id}/portal")
def consultar_portal(caso_id: str):
    """Estado do portal. Devolve o link, nunca a senha."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    token = caso.get("portal_token")
    return {
        "ativo": bool(token),
        "url": f"{URL_PORTAL}/portal/{token}" if token else None,
        # O token já vai no `url`; sai em campo próprio porque é ele que nomeia
        # a sala da chamada, e recortar a URL na tela seria pior.
        "token": token,
        "criado_em": caso.get("portal_criado_em"),
    }


@roteador.get("/api/casos/{caso_id}/pedido")
def pedido_do_caso(caso_id: str, incluir_opcionais: bool = False):
    """Texto pronto para o advogado mandar ao cliente com o que ainda falta."""
    pedido = casos.montar_pedido(caso_id, incluir_opcionais)
    if pedido is None:
        raise HTTPException(404, "Caso não encontrado.")
    return pedido


@roteador.get("/api/casos/{caso_id}/documentos/pendentes")
def documentos_pendentes_do_caso(caso_id: str, incluir_opcionais: bool = False):
    """Documentos que ainda exigem ação do cliente, sem montar texto de WhatsApp."""
    pendentes = casos.documentos_pendentes_do_caso(caso_id, incluir_opcionais)
    if pendentes is None:
        raise HTTPException(404, "Caso não encontrado.")
    return pendentes


@roteador.get("/api/casos/{caso_id}/documentos/busca")
def buscar_nos_documentos_do_caso(caso_id: str, q: str = ""):
    """Documentos cujo conteúdo lido (campos e texto do OCR) contém a busca."""
    resultados = casos.buscar_no_conteudo(caso_id, q[:200])
    if resultados is None:
        raise HTTPException(404, "Caso não encontrado.")
    return resultados
