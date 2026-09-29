"""Onde o backend acha o que não é código Python dele.

O repositório se divide em `front/`, `back/` e `ia/`; na raiz fica só o que é do
projeto inteiro — o `.env` inclusive, porque o `docker compose` também o lê de lá.
A imagem de produção NÃO segue essa divisão: o Dockerfile remonta tudo sob
`/app`, com as skills dentro do pacote (`/app/app/skills`) e o `.skill.zip` ao
lado dele. Por isso cada caminho aqui procura primeiro o lugar da imagem e só
depois o do repositório — assim nenhum comando de produção precisou mudar.
"""

from __future__ import annotations

from pathlib import Path

PACOTE = Path(__file__).resolve().parent
#: `back/` no repositório, `/app` na imagem: onde moram `dados/`, `docs/`, `static/`, `tmp/`.
BACK = PACOTE.parent
#: Raiz do repositório (a do `.env`). Na imagem não há `back/`, e ela é a própria `/app`.
RAIZ = BACK.parent if BACK.name == "back" else BACK
IA = RAIZ / "ia"

ENV = RAIZ / ".env"
ENV_LOCAL = RAIZ / ".env.local"


def _primeiro_que_existe(*candidatos: Path) -> Path:
    return next((c for c in candidatos if c.exists()), candidatos[-1])


#: Skills em arquivo (`<nome>/SKILL.md`). Somente leitura em produção.
SKILLS = _primeiro_que_existe(PACOTE / "skills", IA / "skills")
#: A skill jurídica que a API instala no banco ao subir.
SKILL_EMBUTIDA = _primeiro_que_existe(
    BACK / "escritorio-trabalhista.skill.zip", IA / "escritorio-trabalhista.skill.zip"
)
