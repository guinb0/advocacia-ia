"""Por que o documento ficou "Lendo" para sempre — respondido em 10 segundos.

Rode DENTRO do container da API ou do worker, no ambiente que está com problema:

    python -m scripts.diagnostico_fila_ocr

Só lê. Não enfileira nada, não escreve no banco, não imprime senha.

A pergunta que ele responde é uma só: entre o upload e a leitura, onde a corrente
arrebentou? São três elos, e cada um falha de um jeito diferente:

  1. a API publicou a mensagem no Redis?      -> fila com tamanho > 0
  2. existe worker consumindo `gpu_background`? -> a resposta de quase todo caso
  3. o worker está no MESMO Redis que a API?  -> fila cheia e worker ocioso

Documento parado em `na_fila` é sempre um destes três. Parado em `erro` é outra
história — aí a leitura aconteceu e falhou, e a mensagem do erro está no banco.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


def _titulo(texto: str) -> None:
    print(f"\n{texto}\n{'-' * len(texto)}")


def _idade(criado_em: str) -> str:
    try:
        criado = datetime.fromisoformat(str(criado_em))
    except ValueError:
        return "?"
    if criado.tzinfo is None:
        criado = criado.replace(tzinfo=timezone.utc)
    minutos = (datetime.now(timezone.utc) - criado).total_seconds() / 60
    if minutos < 90:
        return f"{minutos:.0f} min"
    return f"{minutos / 60:.1f} h"


def main() -> int:
    from app import ambiente

    ambiente.carregar()

    from app.celery_app import celery_app

    broker = celery_app.conf.broker_url

    _titulo("Para onde este processo aponta")
    print(f"  broker Celery : {broker}")
    print(f"  SQL Server    : {os.getenv('SQLSERVER_HOST')}:{os.getenv('SQLSERVER_PORT', '1433')}"
          f" / {os.getenv('SQLSERVER_DATABASE', 'advocacia')}")
    print(f"  MISTRAL_API_KEY: {'definida' if os.getenv('MISTRAL_API_KEY') else 'AUSENTE — nenhuma leitura funciona'}")
    print("  (compare estas linhas entre o container da API e o do worker de OCR:")
    print("   brokers diferentes = a API publica num Redis e o worker escuta outro)")

    # ------------------------------------------------------------ elo 1: fila
    _titulo("1. A fila no Redis")
    try:
        import redis

        r = redis.from_url(broker)
        r.ping()
        for fila in ("gpu_background", "default", "ai", "documents", "low"):
            print(f"  {fila:16} {r.llen(fila):>5} mensagem(ns) esperando")
        # Com `task_acks_late`, a mensagem em execução sai da lista e vai para cá.
        unacked = r.hlen("unacked") if r.exists("unacked") else 0
        print(f"  {'em execução':16} {unacked:>5} (entregue a um worker, ainda sem confirmação)")
    except Exception as exc:  # noqa: BLE001
        print(f"  NÃO FOI POSSÍVEL FALAR COM O REDIS: {type(exc).__name__}: {exc}")
        print("  -> sem broker, nenhum upload vira leitura. É aqui que acaba a investigação.")
        return 1

    # -------------------------------------------------------- elo 2: o worker
    _titulo("2. Quem está consumindo")
    consumindo_ocr = False
    try:
        inspecao = celery_app.control.inspect(timeout=5)
        filas = inspecao.active_queues() or {}
        ativas = inspecao.active() or {}
        if not filas:
            print("  NENHUM worker respondeu.")
        for worker, lista in filas.items():
            nomes = [q["name"] for q in lista]
            if "gpu_background" in nomes:
                consumindo_ocr = True
            trabalhando = len(ativas.get(worker, []))
            print(f"  {worker}")
            print(f"      filas: {', '.join(nomes)}")
            print(f"      tarefas em execução agora: {trabalhando}")
    except Exception as exc:  # noqa: BLE001
        print(f"  falha ao inspecionar: {type(exc).__name__}: {exc}")

    if consumindo_ocr:
        print("\n  OK: há worker consumindo 'gpu_background'.")
    else:
        print("\n  *** NINGUÉM CONSOME 'gpu_background'. ***")
        print("  É esta a causa do documento parado em 'aguardando a vez na fila':")
        print("  o upload entra na fila e não há quem o retire. Suba o worker de OCR:")
        print("    celery -A app.celery_app:celery_app worker --pool=solo "
              "--concurrency=1 -Q gpu_background -n ocr@%h")

    # ------------------------------------------------------- elo 3: o registro
    _titulo("3. Os documentos parados, no banco")
    try:
        from app.banco import conectar

        with conectar() as con:
            linhas = con.execute(
                """
                SELECT e.id, e.arquivo, e.item_codigo, e.status_proc, e.criado_em, c.cliente
                  FROM entregas e
                  JOIN casos c ON c.id = e.caso_id
                 WHERE e.status_proc IN ('na_fila', 'processando')
                 ORDER BY e.criado_em
                """
            ).fetchall()
            recentes = con.execute(
                """
                SELECT TOP 5 arquivo, status_proc, erro_proc, criado_em
                  FROM entregas ORDER BY criado_em DESC
                """
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        print(f"  falha ao consultar o banco: {type(exc).__name__}: {exc}")
        return 1

    if not linhas:
        print("  Nenhuma entrega parada em 'na_fila' ou 'processando'.")
        print("  Se a TELA ainda mostra 'Lendo', o banco não concorda com ela:")
        print("  o navegador está com dados velhos, ou está falando com outra instalação.")
    for l in linhas:
        print(f"  {l['status_proc']:12} há {_idade(l['criado_em']):>8}  "
              f"{l['item_codigo']:8} {l['arquivo'][:40]:40} ({l['cliente'][:25]})")
        print(f"       id={l['id']}")

    print("\n  Últimas 5 entregas registradas:")
    for l in recentes:
        erro = f" — {str(l['erro_proc'])[:60]}" if l["erro_proc"] else ""
        print(f"    {l['criado_em']}  {l['status_proc']:10} {l['arquivo'][:40]}{erro}")

    # ---------------------------------------------------------------- veredito
    _titulo("Veredito")
    if linhas and not consumindo_ocr:
        print("  Documento(s) esperando E nenhum leitor no ar. Suba o worker de OCR —")
        print("  a ronda 'recuperar-entregas-travadas' devolve tudo à fila em até 5 min.")
    elif linhas and consumindo_ocr:
        print("  Há leitor no ar e documento esperando. Ou a mensagem se perdeu (a ronda")
        print("  reenfileira em até 5 min), ou o worker está preso — veja o log dele.")
    elif not linhas:
        print("  Nada parado no banco. O problema, se existe, é da tela para cá.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
