"""Migra petições já geradas para o acervo semântico de conteúdo."""
from __future__ import annotations
import hashlib, json, os
import psycopg
from app import ambiente, armazenamento, rag
from app.indexacao_documento import _fragmentar

def texto(dados: dict) -> str:
    return "\n\n".join(
        f"{s.get('label') or s.get('code') or 'Seção'}\n{s.get('content') or ''}"
        for s in dados.get('sections') or [] if str(s.get('content') or '').strip()
    ).strip()

def main() -> None:
    ambiente.carregar()
    with armazenamento.conectar() as origem:
        linhas = origem.execute("SELECT caso_id,dados_json FROM peticoes_locais").fetchall()
    total = 0
    with psycopg.connect(os.environ['DATABASE_URL']) as destino:
        for linha in linhas:
            try: dados = json.loads(linha['dados_json'])
            except Exception: continue
            corpo = texto(dados)
            if not corpo: continue
            origem_id = f"peticao-local:{linha['caso_id']}"
            digest = hashlib.sha256(corpo.encode()).hexdigest()
            partes = _fragmentar(corpo)
            vetores = rag.gerar_embeddings(partes, timeout=180)
            registro = destino.execute("""INSERT INTO pecas_conteudo(origem_id,nome_arquivo,tipo_peca,categoria,texto_integral,hash_conteudo)
              VALUES(%s,%s,'PETICAO_INICIAL','',%s,%s)
              ON CONFLICT(origem_id) DO UPDATE SET texto_integral=EXCLUDED.texto_integral,hash_conteudo=EXCLUDED.hash_conteudo,atualizado_em=now() RETURNING id""",(origem_id,dados.get('title') or origem_id,corpo,digest)).fetchone()[0]
            destino.execute("DELETE FROM pecas_conteudo_chunks WHERE peca_id=%s",(registro,))
            with destino.cursor() as cursor:
                cursor.executemany("INSERT INTO pecas_conteudo_chunks(peca_id,ordem,texto,embedding) VALUES(%s,%s,%s,%s::vector)",[(registro,n,p,rag.vetor_literal(v)) for n,(p,v) in enumerate(zip(partes,vetores))])
            total += len(partes)
        destino.commit()
    print(f'Chunks de petições vetorizados: {total}')
if __name__ == '__main__': main()
