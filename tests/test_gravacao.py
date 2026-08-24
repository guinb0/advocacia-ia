"""Gravação do áudio da entrevista: do PCM ao .mp4 que o escritório baixa.

O que está coberto é o que faz o áudio de uma entrevista SUMIR — e áudio de
entrevista não se refaz, diferente de uma transcrição:

- o processo morrer com a gravação aberta (WAV com cabeçalho zerado);
- a aba recarregar no meio (a segunda conexão sobrescrevendo a primeira);
- dois cliques em "encerrar" convertendo o mesmo arquivo ao mesmo tempo;
- um id de entrevista escrevendo fora da pasta de gravações.

O Whisper NÃO entra aqui. Os testes mandam menos de meio segundo de áudio por
sessão, que é o piso de `SEGUNDOS_ENTRE_PARCIAIS`, e não mandam `stop` — assim
nada dispara a transcrição, que levaria 85s de carga de modelo para provar coisa
nenhuma sobre gravação.

Rodar: .venv\\Scripts\\python.exe -m tests.test_gravacao
"""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path

import numpy as np

from app import gravacao


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


def _fala(segundos: float, hz: float = 220.0) -> np.ndarray:
    """Float32 no formato que o worklet manda: mono, 16 kHz, entre -1 e 1."""
    t = np.arange(int(gravacao.TAXA * segundos)) / gravacao.TAXA
    return (0.4 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def _duracao_do_mp4(caminho: Path) -> float:
    """Quanto áudio o arquivo REALMENTE tem, decodificando-o de volta."""
    import av

    with av.open(str(caminho)) as container:
        amostras = sum(quadro.samples for quadro in container.decode(audio=0))
        return amostras / container.streams.audio[0].codec_context.sample_rate


# --------------------------------------------------------------- gravação


def testar_ciclo_completo() -> int:
    falhas = 0
    with tempfile.TemporaryDirectory() as pasta:
        gravacao.PASTA = Path(pasta)
        grav = gravacao.Gravacao("11111111-1111-4111-8111-111111111111")

        for _ in range(4):
            grav.acrescentar(_fala(0.5))

        falhas += not checar(abs(grav.duracao_s - 2.0) < 0.01, "acumula 2s de fala")
        falhas += not checar(grav.wav.exists(), "o WAV existe DURANTE a entrevista")

        dados = grav.encerrar()

        falhas += not checar(grav.mp4.exists(), "o MP4 é gerado no encerramento")
        falhas += not checar(not grav.wav.exists(), "o WAV some depois de convertido")
        falhas += not checar(dados["pronto"] and dados["bytes"] > 0, "os metadados dizem pronto")
        falhas += not checar(
            abs(_duracao_do_mp4(grav.mp4) - 2.0) < 0.15,
            "o MP4 tem o áudio inteiro (decodificado de volta)",
        )
        falhas += not checar(
            grav.mp4.read_bytes()[4:8] == b"ftyp", "o arquivo é MP4 de verdade (átomo ftyp)"
        )
        falhas += not checar(
            dados["nome"].startswith("Entrevista ") and dados["nome"].endswith(".mp4"),
            f"o nome do download é legível: {dados['nome']!r}",
        )
        falhas += not checar(grav.manifesto.exists(), "o manifesto fica ao lado do áudio")
    return falhas


def testar_pausa_nao_entra() -> int:
    """O que não é enviado não é gravado — e o corte fica registrado."""
    falhas = 0
    with tempfile.TemporaryDirectory() as pasta:
        gravacao.PASTA = Path(pasta)
        grav = gravacao.Gravacao("22222222-2222-4222-8222-222222222222")

        grav.acrescentar(_fala(0.5))
        # A pausa é o navegador PARANDO de mandar bytes: para o servidor, é um
        # intervalo de relógio sem escrita nenhuma.
        grav._ultima_escrita -= gravacao.INTERVALO_TRECHO_S + 1
        grav.acrescentar(_fala(0.5))

        falhas += not checar(len(grav.trechos) == 2, "a retomada vira um segundo trecho")
        falhas += not checar(
            abs(grav.duracao_s - 1.0) < 0.01, "o arquivo tem 1s de fala, não o tempo de relógio"
        )
        falhas += not checar(
            abs(grav.trechos[1]["inicio_s"] - 0.5) < 0.01,
            "o trecho novo começa onde o áudio parou, não onde o relógio estava",
        )
        grav.fechar_arquivo()  # o Windows não apaga a pasta com o arquivo aberto
    return falhas


def testar_retomada_nao_sobrescreve() -> int:
    """F5 no meio da entrevista: a segunda conexão continua o mesmo arquivo."""
    falhas = 0
    with tempfile.TemporaryDirectory() as pasta:
        gravacao.PASTA = Path(pasta)
        identificador = "33333333-3333-4333-8333-333333333333"

        primeira = gravacao.Gravacao(identificador)
        primeira.acrescentar(_fala(1.0))
        primeira.fechar_arquivo()

        segunda = gravacao.Gravacao(identificador)
        falhas += not checar(
            abs(segunda.duracao_s - 1.0) < 0.01, "a gravação reaberta enxerga o que já havia"
        )
        segunda.acrescentar(_fala(1.0))
        segunda.encerrar()

        falhas += not checar(
            abs(_duracao_do_mp4(segunda.mp4) - 2.0) < 0.15,
            "as duas metades estão no mesmo arquivo",
        )
    return falhas


def testar_cabecalho_orfao() -> int:
    """O processo morreu com o arquivo aberto: o áudio está lá e precisa sair."""
    falhas = 0
    with tempfile.TemporaryDirectory() as pasta:
        gravacao.PASTA = Path(pasta)
        identificador = "44444444-4444-4444-8444-444444444444"

        # O que o processo derrubado deixa para trás: os bytes no disco e o
        # cabeçalho por escrever. O handle o sistema operacional recolhe junto
        # com o processo — por isso ele é fechado aqui SEM passar pelo
        # `fechar_arquivo`, que é justamente quem acertaria o cabeçalho.
        orfa = gravacao.Gravacao(identificador)
        orfa.acrescentar(_fala(1.5))
        orfa._arquivo.close()
        orfa._arquivo = None

        with wave.open(str(orfa.wav), "rb") as arquivo:
            falhas += not checar(
                arquivo.getnframes() == 0, "o WAV abandonado mente: diz ter 0 quadros"
            )

        # Ninguém tem esta gravação em memória — é um serviço que reiniciou.
        acervo = gravacao.Gravacoes()
        dados = acervo.encerrar(identificador)

        falhas += not checar(dados["pronto"], "o acervo converte o que ficou da queda")
        falhas += not checar(
            abs(_duracao_do_mp4(gravacao.caminho_mp4(identificador)) - 1.5) < 0.15,
            "o áudio da entrevista interrompida está inteiro no MP4",
        )
    return falhas


def testar_encerrar_duas_vezes() -> int:
    falhas = 0
    with tempfile.TemporaryDirectory() as pasta:
        gravacao.PASTA = Path(pasta)
        identificador = "55555555-5555-4555-8555-555555555555"

        acervo = gravacao.Gravacoes()
        grav = acervo.abrir(identificador)
        grav.acrescentar(_fala(1.0))

        primeiro = acervo.encerrar(identificador)
        assinatura = gravacao.caminho_mp4(identificador).read_bytes()
        segundo = acervo.encerrar(identificador)

        falhas += not checar(
            primeiro["bytes"] == segundo["bytes"], "encerrar de novo devolve o mesmo arquivo"
        )
        falhas += not checar(
            gravacao.caminho_mp4(identificador).read_bytes() == assinatura,
            "o MP4 não é reconvertido nem sobrescrito no segundo clique",
        )

    return falhas


def testar_nao_grava_por_cima() -> int:
    """Voltar a gravar com o id já convertido apagaria a entrevista anterior."""
    falhas = 0
    with tempfile.TemporaryDirectory() as pasta:
        gravacao.PASTA = Path(pasta)
        identificador = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

        acervo = gravacao.Gravacoes()
        acervo.abrir(identificador).acrescentar(_fala(1.0))
        acervo.encerrar(identificador)
        assinatura = gravacao.caminho_mp4(identificador).read_bytes()

        try:
            acervo.abrir(identificador).acrescentar(_fala(1.0))
            recusou = False
        except gravacao.ErroGravacao:
            recusou = True

        falhas += not checar(recusou, "reabrir uma entrevista encerrada é recusado")
        falhas += not checar(
            gravacao.caminho_mp4(identificador).read_bytes() == assinatura,
            "e o áudio da entrevista anterior continua intacto",
        )
    return falhas


def testar_sem_audio() -> int:
    falhas = 0
    with tempfile.TemporaryDirectory() as pasta:
        gravacao.PASTA = Path(pasta)
        acervo = gravacao.Gravacoes()
        try:
            acervo.encerrar("66666666-6666-4666-8666-666666666666")
            recusou = False
        except gravacao.ErroGravacao:
            recusou = True
        falhas += not checar(recusou, "entrevista sem áudio nenhum não inventa arquivo")

        situacao = gravacao.metadados("66666666-6666-4666-8666-666666666666")
        falhas += not checar(
            not situacao["existe"] and not situacao["pronto"],
            "os metadados dizem que não há gravação, sem estourar",
        )
    return falhas


def testar_identificador_hostil() -> int:
    """O id vem do navegador e vira nome de arquivo."""
    falhas = 0
    for hostil in ("../../etc/senha", "..", "a/b", "curto", "", "x" * 65, "com espaço"):
        if gravacao.identificador_valido(hostil):
            falhas += not checar(False, f"deveria recusar o id {hostil!r}")
    falhas += not checar(True, "ids com travessia, curtos ou com barra são recusados")

    try:
        gravacao.caminho_mp4("../../fora")
        escapou = True
    except gravacao.ErroGravacao:
        escapou = False
    falhas += not checar(not escapou, "caminho_mp4 não deixa escrever fora da pasta")

    falhas += not checar(
        gravacao.identificador_valido("77777777-7777-4777-8777-777777777777"),
        "o uuid que o navegador gera passa",
    )
    return falhas


# ----------------------------------------------------------------- rotas


def testar_rotas() -> int:
    """O caminho de ponta a ponta: WebSocket manda PCM, HTTP devolve o MP4."""
    from fastapi.testclient import TestClient

    from app import servico_transcricao

    falhas = 0
    with tempfile.TemporaryDirectory() as pasta:
        gravacao.PASTA = Path(pasta)
        identificador = "88888888-8888-4888-8888-888888888888"
        cliente = TestClient(servico_transcricao.app)

        with cliente.websocket_connect("/ws/transcricao") as ws:
            ws.send_json(
                {
                    "type": "start",
                    "sessionId": "sessao-1",
                    "questionId": "entrevista",
                    "entrevistaId": identificador,
                }
            )
            falhas += not checar(
                ws.receive_json().get("gravando") is True,
                "o servidor confirma que está gravando o áudio",
            )
            # Menos de 0,5s por bloco e nenhum `stop`: nada aciona o Whisper.
            for _ in range(3):
                ws.send_bytes(_fala(0.4).tobytes())

        situacao = cliente.get(f"/entrevista/{identificador}/gravacao").json()
        falhas += not checar(
            situacao["existe"] and not situacao["pronto"],
            "antes de converter: o áudio existe e o MP4 ainda não",
        )

        pendente = cliente.get(f"/entrevista/{identificador}/audio")
        falhas += not checar(
            pendente.status_code == 409, "baixar antes de converter responde 409, não 404"
        )

        dados = cliente.post(f"/entrevista/{identificador}/encerrar").json()
        falhas += not checar(dados["pronto"], "o POST de encerrar converte e devolve pronto")
        falhas += not checar(
            abs(dados["duracao_s"] - 1.2) < 0.1, f"a duração é a da fala enviada ({dados})"
        )

        arquivo = cliente.get(f"/entrevista/{identificador}/audio")
        falhas += not checar(arquivo.status_code == 200, "o áudio baixa")
        falhas += not checar(
            arquivo.headers["content-type"] == "audio/mp4", "vai como audio/mp4"
        )
        falhas += not checar(
            "attachment" in arquivo.headers.get("content-disposition", ""),
            "o navegador é instruído a baixar, com nome de arquivo",
        )
        falhas += not checar(
            arquivo.content[4:8] == b"ftyp" and len(arquivo.content) > 1000,
            "o que chega ao escritório é um MP4 com conteúdo",
        )

        vazia = cliente.get("/entrevista/99999999-9999-4999-8999-999999999999/audio")
        falhas += not checar(vazia.status_code == 404, "entrevista sem gravação responde 404")

        invalida = cliente.get("/entrevista/..%2F..%2Ffora/audio")
        falhas += not checar(
            invalida.status_code in (400, 404), "id hostil não passa pela rota"
        )
    return falhas


def main_teste() -> int:
    original = gravacao.PASTA
    falhas = 0
    for titulo, teste in (
        ("PCM entra, MP4 sai", testar_ciclo_completo),
        ("pausa não entra no arquivo", testar_pausa_nao_entra),
        ("F5 no meio não sobrescreve", testar_retomada_nao_sobrescreve),
        ("processo morto com o arquivo aberto", testar_cabecalho_orfao),
        ("encerrar duas vezes", testar_encerrar_duas_vezes),
        ("não grava por cima do que já saiu", testar_nao_grava_por_cima),
        ("entrevista sem áudio", testar_sem_audio),
        ("id de entrevista hostil", testar_identificador_hostil),
        ("rotas de ponta a ponta", testar_rotas),
    ):
        print(f"\n{titulo}")
        falhas += teste()

    gravacao.PASTA = original
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
