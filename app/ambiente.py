"""O `.env` da raiz, lido por quem precisa dele antes de qualquer configuração.

POR QUE ISTO SAIU DO `banco.py`

A leitura do `.env` nasceu lá porque o banco foi o primeiro a precisar de segredo
fora do `iniciar.ps1`. Agora o serviço de transcrição precisa da mesma coisa — a
chave da OpenRouter — e ele NÃO fala com o banco: o processo da 8200 existe
justamente para não carregar o que não é dele (ver o cabeçalho de
`app/servico_transcricao.py`). Importar `banco` só para ler um arquivo de texto
traria o pyodbc junto e desfaria essa separação.

`iniciar.ps1` continua exportando o `.env` inteiro antes de subir os processos, e
enquanto se sobe por ele nada disto é necessário. O caso que isto cobre é o outro,
e é o que o próprio docstring do serviço ensina a fazer:

    .venv\\Scripts\\python.exe -m uvicorn app.servico_transcricao:app --port 8200

Subido assim, sem o script, o processo ficava sem `OPENROUTER_API_KEY` — e o
sintoma era a transcrição falhando em toda resposta, com a tela dizendo que não
ouviu nada. Erro de configuração parecendo erro de microfone.
"""

from __future__ import annotations

import os
from pathlib import Path

CAMINHO = Path(__file__).resolve().parent.parent / ".env"


def carregar() -> None:
    """Lê o `.env` do projeto sem sobrescrever o que já veio do ambiente.

    Variável já presente no ambiente **vence** o arquivo: é o que permite apontar
    para outro banco, ou trocar de motor de transcrição, numa execução pontual sem
    editar o `.env`. Idempotente — chamar de novo não desfaz nem repõe nada.
    """
    if not CAMINHO.exists():
        return
    for linha in CAMINHO.read_text(encoding="utf-8").splitlines():
        texto = linha.strip()
        if not texto or texto.startswith("#") or "=" not in texto:
            continue
        chave, _, valor = texto.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip())


def numero(nome: str, padrao: float) -> float:
    """Um número do ambiente, tratando VAZIO como ausente.

    `os.getenv(nome, padrao)` não serve depois que o `.env` passa a ser lido: uma
    linha `SEGUNDOS_ENTRE_PARCIAIS=` põe a chave no ambiente com valor `""`, o
    default nunca entra, e o `float("")` derruba a importação do módulo — ou seja,
    o serviço inteiro não sobe por causa de uma linha em branco no arquivo de
    configuração. Deixar a chave vazia é justamente como o `.env.example` diz para
    pedir o padrão, então isto precisa funcionar.
    """
    bruto = os.getenv(nome, "").strip()
    if not bruto:
        return padrao
    try:
        return float(bruto)
    except ValueError:
        return padrao
