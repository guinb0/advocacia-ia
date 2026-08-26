"""Memória curta para retratos caros e somente de leitura."""

from __future__ import annotations

import time
from functools import wraps
from threading import RLock
from typing import Any, Callable, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])


def por_alguns_segundos(ttl: float, *, maximo: int = 128) -> Callable[[F], F]:
    """Reutiliza respostas boas; exceções nunca entram no cache."""

    def decorar(funcao: F) -> F:
        memoria: dict[tuple[Any, ...], tuple[float, Any]] = {}
        trava = RLock()

        @wraps(funcao)
        def envolta(*args: Any, **kwargs: Any) -> Any:
            chave = (*args, *sorted(kwargs.items()))
            agora = time.monotonic()
            with trava:
                salvo = memoria.get(chave)
                if salvo is not None and agora - salvo[0] < ttl:
                    return salvo[1]

            valor = funcao(*args, **kwargs)
            with trava:
                if len(memoria) >= maximo:
                    memoria.pop(min(memoria, key=lambda item: memoria[item][0]), None)
                memoria[chave] = (time.monotonic(), valor)
            return valor

        def limpar() -> None:
            with trava:
                memoria.clear()

        envolta.limpar_cache = limpar  # type: ignore[attr-defined]

        return cast(F, envolta)

    return decorar
