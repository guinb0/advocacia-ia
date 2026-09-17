"""Conexão OAuth (PKCE) por advogado com o MCP remoto do Tactiq."""
from __future__ import annotations
import base64, hashlib, os, secrets
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
