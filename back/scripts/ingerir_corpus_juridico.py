"""Ingestão integral, rastreável e segura do corpus jurídico oficial.

Nunca use ``errors='replace'``: texto de lei com erro de codificação é uma falha,
não um dado aceitável. Primeiro execute ``--reset-legado`` uma única vez para
remover exclusivamente a antiga carga Planalto; depois ``--coletar`` e, apenas
quando o relatório estiver COMPLETE, ``--com-embeddings``.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, sys, time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
import httpx, psycopg
if __package__ in {None, ""}:  # permite `python scripts/ingerir_corpus_juridico.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.rag import BASE, carregar_env, gerar_embeddings, vetor_literal

RAIZ = BASE / "dados" / "corpus_juridico"; MANIFESTO = RAIZ / "manifesto.json"
RAW, PROCESSADOS, RELATORIOS, ERROS = RAIZ / "raw", RAIZ / "processed", RAIZ / "reports", RAIZ / "errors"
VERSAO = "corpus-juridico/1.0"
ARTIGO = re.compile(r"(?im)^Art\.\s*(\d+[ºo]?(?:-[A-Z])?)(?=\s|\.|:|$)")
REFERENCIA = re.compile(r"(?i)\b(?:Lei|Decreto|Emenda Constitucional)\s*(?:n[ºo.]?\s*)?\d+[\d./-]*")

class Extrator(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.linhas=[]; self.ignorar=0
    def handle_starttag(self, tag, attrs):
        if tag in {"script","style","noscript"}: self.ignorar += 1
        elif tag in {"p","div","br","li","tr","h1","h2","h3","h4"}: self.linhas.append("\n")
    def handle_endtag(self, tag):
        if tag in {"script","style","noscript"}: self.ignorar=max(0,self.ignorar-1)
        elif tag in {"p","div","li","tr","h1","h2","h3","h4"}: self.linhas.append("\n")
    def handle_data(self, data):
        if not self.ignorar: self.linhas.append(data)

def decodificar(bruto: bytes) -> tuple[str,str]:
    """Decodifica sem mascarar corrupção; Planalto histórico pode ser cp1252."""
    tentativas = [("utf-8-sig", "utf-8")]
    if bruto.startswith((b"\xff\xfe", b"\xfe\xff")):
        tentativas.append(("utf-16", "utf-16"))
    tentativas.append(("cp1252", "windows-1252"))
    for codec, nome in tentativas:
        try:
            texto = bruto.decode(codec)
            # "Ã" existe legitimamente em palavras como "CONSTITUIÇÃO". O que
            # denuncia mojibake é a sequência UTF-8 mal interpretada (Ã§, Ã£,
            # Â  etc.), não a letra isolada.
            if "\ufffd" not in texto and not re.search(r"(?:Ã|Â)[\u0080-\u00bf]", texto): return texto, nome
        except UnicodeDecodeError: pass
    raise ValueError("ENCODING_CORRUPTO: nenhum decoder seguro produziu texto jurídico válido")

def extrair(html: str) -> str:
    p=Extrator(); p.feed(html.replace("\x00", "")); p.close()
    linhas=[]
    for linha in "".join(p.linhas).splitlines():
        linha=re.sub(r"[ \t\r\f\v]+", " ", linha).strip()
        if linha and (not linhas or linhas[-1] != linha): linhas.append(linha)
    texto="\n".join(linhas)
    if "\ufffd" in texto or re.search(r"(?:Ã|Â)[\u0080-\u00bf]", texto): raise ValueError("ENCODING_CORRUPTO após parser")
    return texto

def dispositivos(item, texto):
    inicios=[m.start() for m in ARTIGO.finditer(texto)]
    if not inicios: raise ValueError("PARSER_SEM_ARTIGOS")
    inicios.append(len(texto)); resultado=[]; hierarquia=[]
    for i, inicio in enumerate(inicios[:-1]):
        parte=texto[inicio:inicios[i+1]].strip(); ident=ARTIGO.match(parte).group(1)
        # A linha imediatamente anterior costuma conter Título/Capítulo/Seção.
        antes=texto[max(0, inicio-400):inicio].splitlines()[-4:]
        contexto=[x for x in antes if re.match(r"(?i)^(livro|título|capítulo|seção|subseção)", x)]
        prefixo="\n".join([item["nome"], *contexto, f"Art. {ident}"])
        # Constituição e ADCT podem repetir a mesma numeração. A posição torna
        # a unidade tecnicamente única sem perder o artigo no texto/contexto.
        resultado.append((f"art-{ident}-{i + 1}", contexto, parte, f"{prefixo}\n{parte}"))
    return resultado

def baixar(url):
    ultimo=None
    for tentativa in range(4):
        try:
            r=httpx.get(url, headers={"User-Agent":"AdvocaciaIA-Corpus/1.0 contato@advocacia-ia.local"}, timeout=60, follow_redirects=True)
            r.raise_for_status(); return r.content, r.status_code
        except httpx.HTTPError as e: ultimo=e; time.sleep(2**tentativa)
    raise RuntimeError(f"DOWNLOAD_FAILED: {ultimo}")

def gerar_em_lotes(textos, *, tamanho=16):
    """Evita exceder o limite do provedor em diplomas extensos."""
    vetores=[]
    for inicio in range(0, len(textos), tamanho):
        vetores.extend(gerar_embeddings(textos[inicio:inicio+tamanho], timeout=180))
    return vetores

def aplicar_schema(con):
    sql=(BASE / "sql" / "006_corpus_juridico.sql").read_text(encoding="utf-8")
    with con.cursor() as c: c.execute(sql)

def limpar_legado(con):
    with con.cursor() as c:
        # O coletor anterior usou metadados inconsistentes. O identificador e a
        # URL são a fonte de verdade para eliminar *todo* o legado corrompido.
        alvo = "(identificador LIKE 'legislacao-federal:%' OR (url ILIKE '%planalto.gov.br%' AND COALESCE(identificador,'') NOT LIKE 'corpus-juridico:%'))"
        c.execute(f"DELETE FROM knowledge_chunks WHERE fonte_id IN (SELECT id FROM fontes WHERE {alvo})")
        c.execute(f"DELETE FROM fontes WHERE {alvo}")
    con.commit()

def persistir(con, item, texto, url, com_embeddings):
    docs=dispositivos(item,texto); agora=datetime.now(UTC); digest=hashlib.sha256(texto.encode()).hexdigest()
    with con.cursor() as c:
        c.execute("""INSERT INTO corpus_manifest(document_id,document_name,document_number,document_year,official_source,source_url,retrieved_at,parser_version,total_devices,total_chunks,current_devices,status,last_checked_at,report)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PARTIAL',%s,%s::jsonb)
        ON CONFLICT(document_id) DO UPDATE SET retrieved_at=EXCLUDED.retrieved_at,last_checked_at=EXCLUDED.last_checked_at,status='PARTIAL',report=EXCLUDED.report""",
        (item['id'],item['nome'],item['numero'],item['ano'],item['fonte'],url,agora,VERSAO,len(docs),len(docs),len(docs),agora,json.dumps({'sha256':digest,'artigos':len(docs),'encoding':'validado'})))
        c.execute("SELECT DISTINCT ON(identifier) identifier,content_hash,version FROM normative_device_versions WHERE document_id=%s ORDER BY identifier,version DESC", (item['id'],))
        anteriores={linha[0]: linha[1:] for linha in c.fetchall()}; novos=[]; encerra=[]; refs=[]
        for ident,hierarquia,corpo,contexto in docs:
            h=hashlib.sha256(corpo.encode()).hexdigest(); anterior=anteriores.get(ident)
            if not anterior or anterior[0] != h:
                if anterior: encerra.append((item['id'],ident,anterior[1]))
                novos.append((item['id'],ident,(anterior[1]+1 if anterior else 1),json.dumps({'ancestrais':hierarquia},ensure_ascii=False),corpo,h,url,agora))
            refs.extend((item['id'],ident,alvo) for alvo in REFERENCIA.findall(corpo))
        if encerra: c.executemany("UPDATE normative_device_versions SET valid_until=CURRENT_DATE WHERE document_id=%s AND identifier=%s AND version=%s", encerra)
        if novos: c.executemany("INSERT INTO normative_device_versions(document_id,identifier,version,hierarchy,text,content_hash,status,source_url,retrieved_at) VALUES(%s,%s,%s,%s::jsonb,%s,%s,'vigente',%s,%s) ON CONFLICT(document_id,identifier,version) DO NOTHING", novos)
        if refs: c.executemany("INSERT INTO corpus_references(document_id,source_identifier,target_text,reason) VALUES(%s,%s,%s,'referência textual oficial') ON CONFLICT DO NOTHING", refs)
        c.execute("INSERT INTO fontes(tipo,titulo,identificador,url) VALUES('lei',%s,%s,%s) ON CONFLICT(tipo,identificador) WHERE identificador IS NOT NULL DO UPDATE SET titulo=EXCLUDED.titulo,url=EXCLUDED.url RETURNING id",(item['nome'],f"corpus-juridico:{item['id']}",url)); fonte=c.fetchone()[0]
        c.execute("DELETE FROM knowledge_chunks WHERE fonte_id=%s",(fonte,))
        vetores=gerar_em_lotes([d[3] for d in docs]) if com_embeddings else [None]*len(docs)
        registros=[(fonte,n,d[3],json.dumps({'origem':'corpus_juridico_oficial','document_id':item['id'],'dispositivo':d[0],'source_url':url,'sha256':hashlib.sha256(d[2].encode()).hexdigest()},ensure_ascii=False),vetor_literal(v) if v else None) for n,(d,v) in enumerate(zip(docs,vetores))]
        for inicio in range(0, len(registros), 16):
            c.executemany("INSERT INTO knowledge_chunks(fonte_id,ordem,texto,metadados,embedding) VALUES(%s,%s,%s,%s::jsonb,%s::vector)", registros[inicio:inicio + 16])
        c.execute("UPDATE corpus_manifest SET status=%s,total_embeddings=%s WHERE document_id=%s",('COMPLETE' if com_embeddings else 'VALIDATED_PENDING_EMBEDDINGS',sum(v is not None for v in vetores),item['id']))
    con.commit(); return len(docs)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--coletar',action='store_true'); ap.add_argument('--com-embeddings',action='store_true'); ap.add_argument('--reset-legado',action='store_true'); ap.add_argument('--limite',type=int); a=ap.parse_args(); carregar_env()
    for p in (RAW,PROCESSADOS,RELATORIOS,ERROS): p.mkdir(parents=True,exist_ok=True)
    with psycopg.connect(os.environ['DATABASE_URL']) as con:
        aplicar_schema(con)
        if a.reset_legado: limpar_legado(con); print('Legado Planalto removido.')
        for item in json.loads(MANIFESTO.read_text(encoding='utf-8'))[:a.limite]:
            arq=RAW / f"{item['id']}.html"
            try:
                if a.coletar or not arq.exists(): bruto,status=baixar(item['url']); arq.write_bytes(bruto)
                html,codec=decodificar(arq.read_bytes()); texto=extrair(html)
                (PROCESSADOS/f"{item['id']}.txt").write_text(texto,encoding='utf-8',newline='\n')
                qtd=persistir(con,item,texto,item['url'],a.com_embeddings)
                rel={'documento':item['nome'],'status':'COMPLETE' if a.com_embeddings else 'VALIDATED_PENDING_EMBEDDINGS','artigos':qtd,'encoding':codec,'fonte':item['url'],'consultado_em':datetime.now(UTC).isoformat()}
                (RELATORIOS/f"{item['id']}.json").write_text(json.dumps(rel,ensure_ascii=False,indent=2),encoding='utf-8')
                print(f"{item['id']}: {qtd} artigos validados")
            except Exception as erro:
                rel={'documento':item['nome'],'status':'SOURCE_REQUIRES_MANUAL_ACQUISITION','fonte':item['url'],'erro':str(erro),'consultado_em':datetime.now(UTC).isoformat()}
                (ERROS/f"{item['id']}.json").write_text(json.dumps(rel,ensure_ascii=False,indent=2),encoding='utf-8')
                print(f"{item['id']}: {rel['status']} — {erro}")
if __name__=='__main__': main()
