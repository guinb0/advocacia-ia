"""Conexão OAuth (PKCE) por advogado com o MCP remoto do Tactiq."""
from __future__ import annotations
import base64, hashlib, json, os, secrets
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
def agora(): return datetime.now(timezone.utc).isoformat()
def inicializar():
    with conectar() as c: c.execute(ESQUEMA); c.commit()
def _linha(usuario_id):
    with conectar() as c: return c.execute(f"SELECT * FROM {TABELA} WHERE usuario_id=?", (usuario_id,)).fetchone()
def status(usuario_id):
    # A primeira versão dependia da criação na inicialização da API. Se uma
    # instância subisse durante uma oscilação do SQL Server, a tabela não nascia
    # e esta simples leitura devolvia 500 para a tela. Garantir aqui torna a rota
    # autocorretiva e não expõe token algum.
    inicializar()
    r=_linha(usuario_id)
    return {"conectado": bool(r and r['access_token_cifrado']), "conectado_em": str(r['conectado_em'] or '') if r else '', "servidor": MCP, "disponivel": True}
def iniciar(usuario_id, redirect_uri):
    inicializar()
    verifier=secrets.token_urlsafe(64); state=secrets.token_urlsafe(32)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    # Registro dinâmico oficial do servidor: não há client secret no frontend.
    reg=httpx.post(f"{MCP}/oauth/register",json={"client_name":"Advocacia IA","redirect_uris":[redirect_uri],"token_endpoint_auth_method":"none"},timeout=20)
    reg.raise_for_status(); client_id=reg.json()['client_id']
    with conectar() as c:
        c.execute(f"DELETE FROM {TABELA} WHERE usuario_id=?",(usuario_id,))
        c.execute(f"INSERT INTO {TABELA}(usuario_id,client_id,state_cifrado,verifier_cifrado,atualizado_em) VALUES(?,?,?,?,?)",(usuario_id,client_id,cripto.cifrar(state),cripto.cifrar(verifier),agora())); c.commit()
    return f"{MCP}/oauth/authorize?"+urlencode({"response_type":"code","client_id":client_id,"redirect_uri":redirect_uri,"scope":"mcp:meetings:own mcp:meetings:shared mcp:meetings:spaces mcp:meetings:details","state":state,"code_challenge":challenge,"code_challenge_method":"S256"})
def concluir(state, code, redirect_uri):
    with conectar() as c:
        linhas=c.execute(f"SELECT * FROM {TABELA} WHERE state_cifrado IS NOT NULL").fetchall()
    linha=next((r for r in linhas if secrets.compare_digest(cripto.decifrar(r['state_cifrado']),state)),None)
    if not linha: raise ValueError("Conexão Tactiq expirada ou inválida. Comece novamente.")
    resp=httpx.post(f"{MCP}/oauth/token",data={"grant_type":"authorization_code","code":code,"redirect_uri":redirect_uri,"client_id":linha['client_id'],"code_verifier":cripto.decifrar(linha['verifier_cifrado'])},timeout=25); resp.raise_for_status(); tok=resp.json()
    with conectar() as c:
        c.execute(f"UPDATE {TABELA} SET access_token_cifrado=?,refresh_token_cifrado=?,state_cifrado=NULL,verifier_cifrado=NULL,conectado_em=?,atualizado_em=? WHERE usuario_id=?",(cripto.cifrar(tok['access_token']),cripto.cifrar(tok.get('refresh_token','')),agora(),agora(),linha['usuario_id'])); c.commit()
    return linha['usuario_id']


def _token(usuario_id):
    linha = _linha(usuario_id)
    if not linha or not linha['access_token_cifrado']:
        raise ValueError("Conecte o Tactiq antes de importar uma transcrição.")
    return cripto.decifrar(linha['access_token_cifrado'])


def _json_mcp(resposta):
    """MCP remoto pode devolver JSON puro ou evento SSE; aceita ambos."""
    resposta.raise_for_status()
    try:
        return resposta.json()
    except ValueError:
        for linha in resposta.text.splitlines():
            if linha.startswith("data:"):
                import json
                return json.loads(linha[5:].strip())
    raise ValueError("O servidor MCP devolveu uma resposta sem JSON.")


def _mcp(usuario_id, acao):
    """Abre uma sessão MCP remota e executa uma operação autenticada."""
    cabecalho = {"Authorization": f"Bearer {_token(usuario_id)}", "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with httpx.Client(timeout=45) as cliente:
        resposta_inicio = cliente.post(MCP, json={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"advocacia-ia","version":"1.0"}}}, headers=cabecalho)
        inicio = _json_mcp(resposta_inicio)
        sessao = resposta_inicio.headers.get("mcp-session-id") or inicio.get("result", {}).get("sessionId") or ""
        if sessao:
            cabecalho["Mcp-Session-Id"] = sessao
        cliente.post(MCP, json={"jsonrpc":"2.0","method":"notifications/initialized","params":{}}, headers=cabecalho).raise_for_status()
        return acao(cliente, cabecalho)


def _ferramentas_na_sessao(cliente, cabecalho):
    resposta = _json_mcp(cliente.post(MCP, json={"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}, headers=cabecalho))
    return resposta.get("result", {}).get("tools", [])


def ferramentas(usuario_id):
    return _mcp(usuario_id, _ferramentas_na_sessao)


def _chamar(cliente, cabecalho, nome, argumentos):
    resposta = _json_mcp(cliente.post(MCP, json={"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":nome,"arguments":argumentos}}, headers=cabecalho))
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
            ferramenta = _ferramenta(disponiveis, "meeting", "detail")
        except ValueError:
            ferramenta = _ferramenta(disponiveis, "transcript")
        propriedades = (ferramenta.get("inputSchema") or {}).get("properties") or {}
        campo_id = next((nome for nome in ("meeting_id", "meetingId", "id") if nome in propriedades), None)
        if not campo_id:
            raise ValueError("O Tactiq não informou como identificar a reunião selecionada.")
        dados = _texto_resultado(_chamar(cliente, cabecalho, ferramenta["name"], {campo_id: reuniao_id}))
        if isinstance(dados, str):
            texto, titulo = dados, "Transcrição Tactiq"
        else:
            texto, titulo, pilha = "", "Transcrição Tactiq", [dados]
            while pilha:
                atual = pilha.pop()
                if isinstance(atual, dict):
                    titulo = str(atual.get("title") or atual.get("name") or titulo)
                    for chave, valor in atual.items():
                        if chave.lower() in {"transcript", "transcription", "full_transcript", "text"} and isinstance(valor, str) and len(valor) > len(texto): texto = valor
                        elif isinstance(valor, (dict, list)): pilha.append(valor)
                elif isinstance(atual, list): pilha.extend(atual)
            if not texto: texto = json.dumps(dados, ensure_ascii=False, indent=2)
        if len(texto.strip()) < 20:
            raise ValueError("Esta reunião ainda não possui transcrição disponível no Tactiq.")
        return {"id": reuniao_id, "titulo": titulo, "texto": texto.strip()}
    return _mcp(usuario_id, executar)
