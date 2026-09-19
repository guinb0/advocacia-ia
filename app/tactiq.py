"""Conexão OAuth (PKCE) por advogado com o MCP remoto do Tactiq."""
from __future__ import annotations
import base64, hashlib, json, os, secrets, threading
from datetime import datetime, timezone
from urllib.parse import urlencode
import httpx
from . import cripto
from .banco import PREFIXO, SCHEMA, conectar

MCP = "https://mcp.tactiq.io"
TABELA = f"{SCHEMA}.{PREFIXO}tactiq_conexoes"
ESQUEMA = f"""
IF OBJECT_ID('{TABELA}') IS NULL CREATE TABLE {TABELA} (
 usuario_id varchar(160) NOT NULL PRIMARY KEY, client_id nvarchar(300) NULL,
 access_token_cifrado nvarchar(max) NULL, refresh_token_cifrado nvarchar(max) NULL,
 state_cifrado nvarchar(max) NULL, verifier_cifrado nvarchar(max) NULL,
 conectado_em varchar(40) NULL, atualizado_em varchar(40) NOT NULL
)"""
ESQUEMA_PENDENTE = f"IF COL_LENGTH('{TABELA}','pendente_client_id') IS NULL ALTER TABLE {TABELA} ADD pendente_client_id nvarchar(300) NULL"
MSG_EXPIRADA = "A conexão Tactiq expirou ou foi revogada. Conecte novamente para importar as transcrições."
MSG_CHAVE = "Não foi possível abrir a conexão Tactiq salva com a chave atual do servidor. Conecte novamente."
ERROS_REVOGACAO = {"invalid_grant", "invalid_client", "unauthorized_client"}
_travas: dict[str, threading.Lock] = {}
_travas_guarda = threading.Lock()


class _NaoAutorizado(Exception):
    pass


def agora(): return datetime.now(timezone.utc).isoformat()
def inicializar():
    with conectar() as c:
        c.execute(ESQUEMA)
        c.execute(ESQUEMA_PENDENTE)
        c.commit()
def _linha(usuario_id):
    with conectar() as c: return c.execute(f"SELECT * FROM {TABELA} WHERE usuario_id=?", (usuario_id,)).fetchone()
def _trava(usuario_id):
    with _travas_guarda:
        return _travas.setdefault(usuario_id, threading.Lock())
def _decifrar(valor):
    try:
        return cripto.decifrar(valor)
    except cripto.ErroCripto as exc:
        raise ValueError(MSG_CHAVE) from exc
def _limpar_tokens(usuario_id):
    with conectar() as c:
        c.execute(f"UPDATE {TABELA} SET access_token_cifrado=NULL, refresh_token_cifrado=NULL, atualizado_em=? WHERE usuario_id=?", (agora(), usuario_id)); c.commit()


def status(usuario_id, verificar=False):
    inicializar()
    r=_linha(usuario_id)
    dados={"conectado": bool(r and r['access_token_cifrado']), "conectado_em": str(r['conectado_em'] or '') if r else '', "servidor": MCP, "disponivel": True, "motivo": ""}
    if not dados["conectado"]:
        return dados
    try:
        _decifrar(r['access_token_cifrado'])
        if verificar:
            _mcp(usuario_id, lambda cliente, cabecalho: True)
    except ValueError as exc:
        dados.update(conectado=False, motivo=str(exc))
    except httpx.HTTPError:
        dados["motivo"] = "O Tactiq não respondeu agora; a conexão foi mantida."
    return dados
def iniciar(usuario_id, redirect_uri):
    inicializar()
    verifier=secrets.token_urlsafe(64); state=secrets.token_urlsafe(32)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    reg=httpx.post(f"{MCP}/oauth/register",json={"client_name":"Advocacia IA","redirect_uris":[redirect_uri],"token_endpoint_auth_method":"none"},timeout=20)
    reg.raise_for_status(); client_id=reg.json()['client_id']
    with conectar() as c:
        if c.execute(f"SELECT 1 FROM {TABELA} WHERE usuario_id=?",(usuario_id,)).fetchone():
            c.execute(f"UPDATE {TABELA} SET pendente_client_id=?,state_cifrado=?,verifier_cifrado=?,atualizado_em=? WHERE usuario_id=?",(client_id,cripto.cifrar(state),cripto.cifrar(verifier),agora(),usuario_id))
        else:
            c.execute(f"INSERT INTO {TABELA}(usuario_id,client_id,pendente_client_id,state_cifrado,verifier_cifrado,atualizado_em) VALUES(?,?,?,?,?,?)",(usuario_id,client_id,client_id,cripto.cifrar(state),cripto.cifrar(verifier),agora()))
        c.commit()
    return f"{MCP}/oauth/authorize?"+urlencode({"response_type":"code","client_id":client_id,"redirect_uri":redirect_uri,"scope":"mcp:meetings:own mcp:meetings:shared mcp:meetings:spaces mcp:meetings:details","state":state,"code_challenge":challenge,"code_challenge_method":"S256"})
def _confere_state(linha, state):
    try:
        return secrets.compare_digest(cripto.decifrar(linha['state_cifrado']),state)
    except cripto.ErroCripto:
        return False
def concluir(state, code, redirect_uri):
    inicializar()
    with conectar() as c:
        linhas=c.execute(f"SELECT * FROM {TABELA} WHERE state_cifrado IS NOT NULL").fetchall()
    linha=next((r for r in linhas if _confere_state(r,state)),None)
    if not linha: raise ValueError("Conexão Tactiq expirada ou inválida. Comece novamente.")
    client_id=linha['pendente_client_id'] or linha['client_id']
    resp=httpx.post(f"{MCP}/oauth/token",data={"grant_type":"authorization_code","code":code,"redirect_uri":redirect_uri,"client_id":client_id,"code_verifier":cripto.decifrar(linha['verifier_cifrado'])},timeout=25); resp.raise_for_status(); tok=resp.json()
    with _trava(linha['usuario_id']), conectar() as c:
        c.execute(f"UPDATE {TABELA} SET client_id=?,pendente_client_id=NULL,access_token_cifrado=?,refresh_token_cifrado=?,state_cifrado=NULL,verifier_cifrado=NULL,conectado_em=?,atualizado_em=? WHERE usuario_id=?",(client_id,cripto.cifrar(tok['access_token']),cripto.cifrar(tok.get('refresh_token','')),agora(),agora(),linha['usuario_id'])); c.commit()
    return linha['usuario_id']


def _token(usuario_id):
    linha = _linha(usuario_id)
    if not linha or not linha['access_token_cifrado']:
        raise ValueError("Conecte o Tactiq antes de importar uma transcrição.")
    return _decifrar(linha['access_token_cifrado'])


def _erro_oauth(resposta):
    try:
        erro = str((resposta.json() or {}).get("error") or "")
    except ValueError:
        erro = ""
    return erro or ("invalid_client" if resposta.status_code == 401 else "")


def _renovar_token(usuario_id, token_falho):
    """Renova o access token uma única vez por vez: chamadas paralelas reaproveitam o token novo."""
    with _trava(usuario_id):
        linha = _linha(usuario_id)
        if not linha or not linha['refresh_token_cifrado']:
            raise ValueError(MSG_EXPIRADA)
        atual = _decifrar(linha['access_token_cifrado']) if linha['access_token_cifrado'] else ""
        if atual and atual != token_falho:
            return atual
        refresh = _decifrar(linha['refresh_token_cifrado'])
        resposta = httpx.post(
            f"{MCP}/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh, "client_id": linha['client_id']},
            timeout=25,
        )
        if resposta.status_code >= 400:
            if _erro_oauth(resposta) in ERROS_REVOGACAO:
                outra = _linha(usuario_id)
                if outra and outra['access_token_cifrado'] and outra['refresh_token_cifrado'] and _decifrar(outra['refresh_token_cifrado']) != refresh:
                    return _decifrar(outra['access_token_cifrado'])
                _limpar_tokens(usuario_id)
                raise ValueError(MSG_EXPIRADA)
            resposta.raise_for_status()
        dados = resposta.json()
        access = str(dados.get("access_token") or "").strip()
        if not access:
            raise ValueError("O Tactiq não devolveu um novo token de acesso. Conecte novamente.")
        refresh_novo = str(dados.get("refresh_token") or refresh)
        with conectar() as banco:
            banco.execute(
                f"UPDATE {TABELA} SET access_token_cifrado=?, refresh_token_cifrado=?, atualizado_em=? WHERE usuario_id=?",
                (cripto.cifrar(access), cripto.cifrar(refresh_novo), agora(), usuario_id),
            )
            banco.commit()
        return access


def _json_mcp(resposta):
    """MCP remoto pode devolver JSON puro ou evento SSE; aceita ambos."""
    resposta.raise_for_status()
    try:
        return resposta.json()
    except ValueError:
        for linha in resposta.text.splitlines():
            if linha.startswith("data:"):
                return json.loads(linha[5:].strip())
    raise ValueError("O servidor MCP devolveu uma resposta sem JSON.")


def _post(cliente, cabecalho, corpo):
    resposta = cliente.post(MCP, json=corpo, headers=cabecalho)
    if resposta.status_code == 401:
        raise _NaoAutorizado()
    return resposta


def _sessao(token, acao):
    cabecalho = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with httpx.Client(timeout=45) as cliente:
        resposta_inicio = _post(cliente, cabecalho, {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"advocacia-ia","version":"1.0"}}})
        inicio = _json_mcp(resposta_inicio)
        sessao = resposta_inicio.headers.get("mcp-session-id") or inicio.get("result", {}).get("sessionId") or ""
        if sessao:
            cabecalho["Mcp-Session-Id"] = sessao
        _post(cliente, cabecalho, {"jsonrpc":"2.0","method":"notifications/initialized","params":{}}).raise_for_status()
        return acao(cliente, cabecalho)


def _mcp(usuario_id, acao):
    """Abre uma sessão MCP remota; um 401 em qualquer etapa renova o token e refaz a sessão uma vez."""
    token = _token(usuario_id)
    try:
        return _sessao(token, acao)
    except _NaoAutorizado:
        token = _renovar_token(usuario_id, token)
    try:
        return _sessao(token, acao)
    except _NaoAutorizado as exc:
        raise ValueError("O Tactiq recusou o token renovado. Conecte novamente.") from exc


def _ferramentas_na_sessao(cliente, cabecalho):
    resposta = _json_mcp(_post(cliente, cabecalho, {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}))
    return resposta.get("result", {}).get("tools", [])


def ferramentas(usuario_id):
    return _mcp(usuario_id, _ferramentas_na_sessao)


def _chamar(cliente, cabecalho, nome, argumentos):
    resposta = _json_mcp(_post(cliente, cabecalho, {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":nome,"arguments":argumentos}}))
    if resposta.get("error"):
        raise ValueError(str(resposta["error"].get("message") or "O Tactiq recusou a consulta."))
    return resposta.get("result", {})


def _texto_resultado(resultado):
    textos = [str(item.get("text") or "") for item in resultado.get("content") or [] if isinstance(item, dict) and item.get("type") == "text"]
    bruto = "\n".join(textos).strip()
    if not bruto:
        return resultado
    try:
        return json.loads(bruto)
    except ValueError:
        # Alguns gateways MCP acrescentam uma mensagem curta antes/depois do
        # JSON. A transcrição continua válida: procura cada bloco JSON sem
        # confundir uma resposta textual legítima com erro de formato.
        for texto in textos:
            try:
                return json.loads(texto.strip())
            except ValueError:
                inicio = texto.find("{")
                fim = texto.rfind("}")
                if inicio >= 0 and fim > inicio:
                    try:
                        return json.loads(texto[inicio : fim + 1])
                    except ValueError:
                        pass
        return bruto


def _ferramenta(ferramentas, *termos):
    termos = tuple(termo.lower() for termo in termos)
    candidatas = []
    for item in ferramentas:
        descricao = " ".join((str(item.get("name") or ""), str(item.get("description") or ""), str(item.get("inputSchema") or ""))).lower()
        if all(termo in descricao for termo in termos):
            candidatas.append(item)
    if not candidatas:
        raise ValueError("O Tactiq não disponibilizou esta consulta. Reconecte e aprove a permissão para detalhes das reuniões.")
    return min(candidatas, key=lambda item: len(str(item.get("name") or "")))


def _ferramenta_por_nome(ferramentas, nome):
    encontrada = next((item for item in ferramentas if item.get("name") == nome), None)
    if not encontrada:
        raise ValueError("O Tactiq não disponibilizou esta consulta. Reconecte e aprove a permissão para detalhes das reuniões.")
    return encontrada


def _coletar_reunioes(valor, saida):
    if isinstance(valor, list):
        for item in valor:
            _coletar_reunioes(item, saida)
    elif isinstance(valor, dict):
        identificador = valor.get("meeting_id") or valor.get("meetingId") or valor.get("id")
        titulo = valor.get("title") or valor.get("name") or valor.get("meeting_title")
        if identificador and titulo:
            saida.append({"id":str(identificador), "titulo":str(titulo), "data":str(valor.get("date") or valor.get("created_at") or valor.get("createdAt") or valor.get("started_at") or "")})
        for item in valor.values():
            _coletar_reunioes(item, saida)


def listar_reunioes(usuario_id):
    def executar(cliente, cabecalho):
        disponiveis = _ferramentas_na_sessao(cliente, cabecalho)
        # `list_spaces` também menciona "meeting" na descrição, mas não lista
        # reuniões. O MCP atual fornece explicitamente esta ferramenta.
        try:
            ferramenta = _ferramenta_por_nome(disponiveis, "list_recent_meetings")
        except ValueError:
            try:
                ferramenta = _ferramenta(disponiveis, "meeting", "list")
            except ValueError:
                ferramenta = _ferramenta(disponiveis, "meeting", "search")
        propriedades = (ferramenta.get("inputSchema") or {}).get("properties") or {}
        argumentos = next(({nome: 50} for nome in ("limit", "page_size", "pageSize") if nome in propriedades), {})
        dados = _texto_resultado(_chamar(cliente, cabecalho, ferramenta["name"], argumentos))
        reunioes = []
        _coletar_reunioes(dados, reunioes)
        return sorted({item["id"]: item for item in reunioes}.values(), key=lambda item: item["data"], reverse=True)[:50]
    return _mcp(usuario_id, executar)


def transcricao(usuario_id, reuniao_id):
    def executar(cliente, cabecalho):
        disponiveis = _ferramentas_na_sessao(cliente, cabecalho)
        try:
            ferramenta = _ferramenta_por_nome(disponiveis, "get_transcript")
        except ValueError:
            ferramenta = _ferramenta(disponiveis, "transcript")
        propriedades = (ferramenta.get("inputSchema") or {}).get("properties") or {}
        campo_id = next((nome for nome in ("meetingId", "meeting_id", "id") if nome in propriedades), None)
        if not campo_id:
            raise ValueError("O Tactiq não informou como identificar a reunião selecionada.")
        pagina, entradas, titulo = 1, [], "Transcrição Tactiq"
        while pagina <= 100:
            argumentos = {campo_id: reuniao_id}
            if "page" in propriedades:
                argumentos["page"] = pagina
            dados = _texto_resultado(_chamar(cliente, cabecalho, ferramenta["name"], argumentos))
            if not isinstance(dados, dict):
                raise ValueError("O Tactiq devolveu uma transcrição em formato inesperado.")
            titulo = str(dados.get("title") or titulo)
            for entrada in dados.get("entries") or []:
                if not isinstance(entrada, dict) or not str(entrada.get("text") or "").strip():
                    continue
                falante = str(entrada.get("speaker") or "").strip()
                texto_entrada = str(entrada.get("text") or "").strip()
                entradas.append(f"{falante}: {texto_entrada}" if falante else texto_entrada)
            total = int(dados.get("totalPages") or pagina)
            if pagina >= total or not dados.get("hasMore"):
                break
            pagina += 1
        texto = "\n\n".join(entradas)
        if len(texto.strip()) < 20:
            raise ValueError("Esta reunião ainda não possui transcrição disponível no Tactiq.")
        return {"id": reuniao_id, "titulo": titulo, "texto": texto.strip()}
    return _mcp(usuario_id, executar)
