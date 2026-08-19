"""Contabilidade do texto provisório — o que aparece na tela enquanto se fala.

Sem Whisper: o transcritor é substituído por um falso que devolve o tamanho do
trecho recebido. O que se testa aqui não é a qualidade do reconhecimento, é a
mecânica em volta dele, que é onde o texto na tela quebra:

- a cadência (não adianta pedir parcial a cada 100ms se o modelo leva 1s);
- o congelamento na pausa, que é o que impede o atraso de crescer com a fala;
- a janela deslizante, que já fez o texto ENCOLHER no meio da fala;
- a exclusão mútua, que evita empilhar transcrições que ninguém vai ver.

Rodar: .venv\\Scripts\\python.exe -m tests.test_transcricao
"""

from __future__ import annotations

import numpy as np

from app import transcricao as T


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


def falar(sessao: T.AnswerSession, segundos: float) -> None:
    """Acrescenta N segundos de áudio, como o worklet faz de 256 em 256 ms."""
    sessao.acrescentar(np.zeros(int(segundos * T.TAXA), dtype=np.float32))


def falante_sem_pausa(audio: np.ndarray) -> list[T.Trecho]:
    """Um segmento só, que vai até o fim do áudio: ninguém parou para respirar.

    É o pior caso para o parcial — não há pausa onde congelar, então a cauda só
    encurta quando bate no limite.
    """
    dur = len(audio) / T.TAXA
    return [T.Trecho(0.0, dur, f"trecho de {dur:.0f}s")]


def falante_com_pausa(audio: np.ndarray) -> list[T.Trecho]:
    """Uma frase fechada logo no começo e outra ainda em curso no fim.

    O caso comum de uma entrevista: a pessoa termina uma frase, respira, e
    continua. A primeira já pode ser congelada.
    """
    dur = len(audio) / T.TAXA
    if dur < 3.0:
        return [T.Trecho(0.0, dur, "comecei a falar")]
    return [
        T.Trecho(0.0, 2.0, "primeira frase"),
        T.Trecho(2.5, dur, f"continuando ate {dur:.0f}s"),
    ]


def main_teste() -> int:
    falhas = 0
    original = T._segmentos_sem_trava
    T._segmentos_sem_trava = falante_sem_pausa
    try:
        sessao = T.AnswerSession(sessao_id="s1", pergunta_id="p1")
        sessao.estado = T.Estado.LISTENING

        falhas += not checar(
            not sessao.iniciar_parcial(),
            "sem áudio não há parcial — a tela não pisca antes da primeira palavra",
        )

        falar(sessao, 0.3)
        falhas += not checar(
            not sessao.iniciar_parcial(),
            f"menos de {T.SEGUNDOS_ENTRE_PARCIAIS}s de fala nova não dispara parcial",
        )

        falar(sessao, 1.5)
        falhas += not checar(sessao.iniciar_parcial(), "passada a cadência, o parcial dispara")
        falhas += not checar(
            not sessao.iniciar_parcial(),
            "só um parcial por vez: o segundo é descartado, não enfileirado",
        )

        texto = sessao.transcrever_parcial()
        sessao.parcial_em_curso = False
        falhas += not checar(texto == "trecho de 2s", f"o parcial vê o áudio todo ({texto!r})")

        # --- fala sem pausa: a cauda só encurta no limite -----------------
        falar(sessao, T.LIMITE_CAUDA_S)
        sessao.iniciar_parcial()
        antes = sessao.transcrever_parcial()
        sessao.parcial_em_curso = False

        falhas += not checar(
            sessao.prefixo_parcial != "" and sessao.texto_parcial == "",
            "sem pausa onde cortar, o limite da cauda força o congelamento",
        )
        falhas += not checar(
            sessao._inicio_cauda == sessao.amostras - int(T.SOBREPOSICAO_PARCIAL_S * T.TAXA),
            "no corte forçado a emenda volta um segundo, para não partir palavra",
        )

        falar(sessao, 2.0)
        sessao.iniciar_parcial()
        depois = sessao.transcrever_parcial()
        sessao.parcial_em_curso = False

        falhas += not checar(
            depois.startswith(antes.split(" trecho")[0]) and len(depois) >= len(antes),
            f"o texto na tela cresce, nunca encolhe ({antes!r} -> {depois!r})",
        )
        falhas += not checar(
            depois == sessao.texto_em_construcao(),
            "o que volta para a tela é prefixo + cauda, sempre",
        )

        # --- fala com pausa: congela na fronteira e a cauda encurta -------
        # É este caminho que mantém o parcial barato: sem ele, cada rodada
        # retranscreve uma cauda cada vez maior e o texto atrasa em relação
        # à fala — que é o sintoma de "não está em tempo real".
        T._segmentos_sem_trava = falante_com_pausa
        pausada = T.AnswerSession(sessao_id="s3", pergunta_id="p3")
        pausada.estado = T.Estado.LISTENING

        falar(pausada, 6.0)
        pausada.iniciar_parcial()
        saida = pausada.transcrever_parcial()
        pausada.parcial_em_curso = False

        falhas += not checar(
            pausada.prefixo_parcial == "primeira frase",
            f"a frase fechada antes da pausa é congelada ({pausada.prefixo_parcial!r})",
        )
        falhas += not checar(
            pausada._inicio_cauda == int(2.0 * T.TAXA),
            "a cauda recomeça exatamente onde o segmento terminou, sem sobreposição",
        )
        falhas += not checar(
            saida.startswith("primeira frase ") and "continuando" in saida,
            f"a tela recebe congelado + em curso ({saida!r})",
        )

        antes_da_cauda = pausada._inicio_cauda
        falar(pausada, 1.0)
        pausada.iniciar_parcial()
        pausada.transcrever_parcial()
        pausada.parcial_em_curso = False
        falhas += not checar(
            pausada._inicio_cauda >= antes_da_cauda
            and (pausada.amostras - pausada._inicio_cauda) <= T.LIMITE_CAUDA_S * T.TAXA,
            "a cauda nunca passa do limite — é o que segura o custo por rodada",
        )

        T._segmentos_sem_trava = falante_sem_pausa

        # --- o final não é a soma dos parciais ---------------------------
        # Ele transcreve o áudio inteiro de novo: é o texto que vira registro,
        # e não pode herdar a emenda das janelas.
        final = sessao.transcrever_final()
        falhas += not checar(
            final == f"trecho de {sessao.duracao_s:.0f}s",
            f"o final transcreve a resposta inteira ({final!r})",
        )
        falhas += not checar(
            sessao.estado is T.Estado.COMPLETED, "a sessão termina marcada como concluída"
        )

        # --- entrevista longa: aceita sempre, e solta o que já virou texto ---
        #
        # Aqui havia o teste oposto: "passado o limite de 30 min, o áudio para de
        # crescer". Isso ERA o defeito. A escuta contínua abre uma sessão só para
        # a entrevista inteira, então o teto silenciava a transcrição no meio do
        # atendimento — o roteiro parava de preencher e a tela dizia que não
        # estava ouvindo. O que a memória precisa é soltar o congelado, não
        # recusar o que chega.
        T._segmentos_sem_trava = falante_com_pausa
        longa = T.AnswerSession(sessao_id="s4", pergunta_id="p4")
        longa.estado = T.Estado.LISTENING

        # Passa bem do teto de memória, senão o descarte nem chega a rodar.
        rodadas = int((T.MEMORIA_MAXIMA_S * 2) / 6)
        for _ in range(rodadas):
            falar(longa, 6.0)
            longa.iniciar_parcial()
            longa.transcrever_parcial()
            longa.parcial_em_curso = False

        antes = longa.amostras
        falar(longa, 5)
        falhas += not checar(
            longa.amostras > antes,
            "entrevista longa continua aceitando fala nova — sem teto que emudece",
        )

        # O que importa é a memória parar de acompanhar o TOTAL. O número exato
        # depende de quanto o congelamento avança, e isto aqui roda com um
        # transcritor falso — cravar segundos mediria o falso, não o código.
        segurado = sum(len(b) for b in longa.audio)
        falhas += not checar(
            longa._base > 0 and segurado < longa.amostras,
            f"a memória solta o que já virou texto ({segurado / T.TAXA:.0f}s de "
            f"{longa.amostras / T.TAXA:.0f}s)",
        )
        falhas += not checar(
            longa.prefixo_parcial != "",
            "o que saiu da memória já tinha virado texto no prefixo",
        )
    finally:
        T._segmentos_sem_trava = original

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
