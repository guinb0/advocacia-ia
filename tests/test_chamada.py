"""Sinalização da chamada de voz: o servidor apresenta os dois lados.

O áudio é ponto a ponto e não passa por aqui — o que dá para verificar sem
microfone é justamente o resto, e é onde moram os erros que travam a chamada:
quem é avisado de que o outro chegou, se o SDP chega inteiro do outro lado, e o
que acontece quando uma aba recarrega no meio da conversa.

Rodar: .venv\\Scripts\\python.exe -m tests.test_chamada
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app import armazenamento, main


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


def main_teste() -> int:
    temporario = Path(tempfile.mkdtemp(prefix="ocr-chamada-"))
    armazenamento.DIR_DADOS = temporario
    armazenamento.DIR_ARQUIVOS = temporario / "casos"
    armazenamento.CAMINHO_BANCO = temporario / "casos.db"
    armazenamento.inicializar()

    falhas = 0
    sala = "sala-de-teste"

    with TestClient(main.app) as cliente:
        config = cliente.get("/api/chamada/config")
        falhas += not checar(
            config.status_code == 200 and config.json()["iceServers"],
            "a config ICE responde sem token — o cliente do portal não tem conta",
        )

        # --- sala avulsa, para a entrevista antes de existir caso ---------
        primeira = cliente.post("/api/chamada/sala").json()
        segunda = cliente.post("/api/chamada/sala").json()
        falhas += not checar(
            primeira["url"].endswith(primeira["sala"]) and "/chamada/" in primeira["url"],
            f"a sala vem com o link pronto para mandar ({primeira['url'][:48]}…)",
        )
        falhas += not checar(
            primeira["sala"] != segunda["sala"] and len(primeira["sala"]) == 32,
            "cada chamada tem sala própria, e o nome dela é o segredo (128 bits)",
        )
        # Minúsculas obrigatórias: a sala vira o nome de uma MUC no Prosody, e o
        # Jitsi normaliza para minúsculas. Um nome com maiúsculas viraria outro
        # no servidor, e as duas pontas poderiam entrar em salas diferentes.
        falhas += not checar(
            re.fullmatch(r"[0-9a-f]{32}", primeira["sala"]) is not None,
            f"o nome da sala é válido em XMPP sem normalização ({primeira['sala'][:12]}…)",
        )
        # --- token JWT para o Jitsi -----------------------------------------
        terceira = cliente.post("/api/chamada/sala").json()
        falhas += not checar(
            "token" in terceira and isinstance(terceira["token"], str) and len(terceira["token"]) > 0,
            "a sala vem com token JWT para o Jitsi",
        )
        # O token deve ser um JWT válido (3 partes separadas por ponto)
        partes_token = terceira["token"].split(".")
        falhas += not checar(
            len(partes_token) == 3,
            "o token é um JWT válido (3 partes: header.payload.signature)",
        )
        # O endpoint aceita sala existente e devolve token novo
        quarta = cliente.post(
            "/api/chamada/sala",
            json={"sala": terceira["sala"]},
        ).json()
        falhas += not checar(
            quarta["sala"] == terceira["sala"] and "token" in quarta,
            "o endpoint aceita sala existente e devolve token novo",
        )
        # A sala é sorteada, não derivada de caso: a entrevista acontece antes
        # de o caso existir, e é ela que decide a categoria.
        with cliente.websocket_connect(
            f"/ws/chamada/{primeira['sala']}?papel=advogado"
        ) as avulsa:
            falhas += not checar(
                avulsa.receive_json()["papel"] == "advogado",
                "dá para entrar na sala recém-sorteada sem caso nenhum",
            )

        # --- o advogado chega primeiro e espera sozinho -------------------
        with cliente.websocket_connect(f"/ws/chamada/{sala}?papel=advogado") as adv:
            entrada = adv.receive_json()
            falhas += not checar(
                entrada == {"type": "entrou", "papel": "advogado", "outroPresente": False},
                "quem chega primeiro sabe que está sozinho",
            )

            # --- o cliente entra: o advogado é avisado e oferta ------------
            with cliente.websocket_connect(f"/ws/chamada/{sala}?papel=cliente") as cli:
                entrada_cli = cli.receive_json()
                falhas += not checar(
                    entrada_cli["outroPresente"] is True,
                    "quem chega depois já sabe que o outro está na sala",
                )
                falhas += not checar(
                    adv.receive_json() == {"type": "pronto", "papel": "cliente"},
                    "o advogado é avisado da chegada do cliente",
                )

                # O SDP é opaco para o servidor: o teste só confere que chega
                # inteiro. Um repasse que mexesse no corpo quebraria a chamada
                # sem erro nenhum aparecer no log.
                oferta = {"type": "offer", "sdp": {"type": "offer", "sdp": "v=0\r\nm=audio 9"}}
                adv.send_json(oferta)
                falhas += not checar(cli.receive_json() == oferta, "a oferta chega ao cliente igual")

                resposta = {"type": "answer", "sdp": {"type": "answer", "sdp": "v=0\r\nm=audio 9"}}
                cli.send_json(resposta)
                falhas += not checar(adv.receive_json() == resposta, "a resposta volta ao advogado")

                ice = {"type": "ice", "candidate": {"candidate": "candidate:1 1 udp", "sdpMid": "0"}}
                cli.send_json(ice)
                falhas += not checar(adv.receive_json() == ice, "o candidato ICE atravessa")

                adv.send_json({"type": "ping"})
                falhas += not checar(
                    adv.receive_json() == {"type": "pong"},
                    "o ping responde — é ele que segura o WebSocket ocioso",
                )

            # --- o cliente saiu ------------------------------------------
            falhas += not checar(
                adv.receive_json() == {"type": "saiu", "papel": "cliente"},
                "a saída do cliente é avisada ao advogado",
            )

            adv.send_json({"type": "offer", "sdp": {}})
            falhas += not checar(
                adv.receive_json() == {"type": "ausente"},
                "falar com a sala vazia devolve 'ausente' em vez de sumir com a mensagem",
            )

        # --- aba recarregada: o mesmo papel entra de novo ------------------
        # Sem substituir o participante anterior, a conexão morta ocuparia a
        # vaga e o cliente que voltasse nunca mais seria apresentado.
        antigo = cliente.websocket_connect(f"/ws/chamada/{sala}?papel=cliente").__enter__()
        antigo.receive_json()
        with cliente.websocket_connect(f"/ws/chamada/{sala}?papel=cliente") as novo:
            falhas += not checar(
                novo.receive_json()["papel"] == "cliente",
                "a aba recarregada assume a vaga do mesmo papel",
            )

            # A conexão velha se desfazendo NÃO pode levar a vaga da nova junto.
            # É o desligamento atrasado da aba que recarregou.
            antigo.__exit__(None, None, None)

            with cliente.websocket_connect(f"/ws/chamada/{sala}?papel=advogado") as adv2:
                adv2.receive_json()
                falhas += not checar(
                    novo.receive_json() == {"type": "pronto", "papel": "advogado"},
                    "é a conexão nova que recebe o aviso de chegada",
                )
                adv2.send_json({"type": "offer", "sdp": {"marca": "para o novo"}})
                falhas += not checar(
                    novo.receive_json()["sdp"] == {"marca": "para o novo"},
                    "a oferta vai para a conexão nova, não para o fantasma",
                )
                novo.send_json({"type": "answer", "sdp": {"marca": "de volta"}})
                falhas += not checar(
                    adv2.receive_json()["sdp"] == {"marca": "de volta"},
                    "a sala continua de pé depois que a conexão velha se desfaz",
                )

        # --- papel inventado ----------------------------------------------
        try:
            with cliente.websocket_connect(f"/ws/chamada/{sala}?papel=xereta") as intruso:
                intruso.receive_json()
            recusado = False
        except Exception:
            recusado = True
        falhas += not checar(recusado, "papel fora de advogado/cliente é recusado")

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
