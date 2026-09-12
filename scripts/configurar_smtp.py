"""Pede a conta de envio, TESTA no servidor e só então grava no `.env`.

    .venv\\Scripts\\python.exe -m scripts.configurar_smtp

Por que um script em vez de "edite o .env":

- **A ordem é testar antes de gravar.** Credencial que não funciona no `.env` é
  pior que credencial ausente: o segundo fator passa a existir, a tela promete um
  código, e o e-mail não sai. Aqui nada é gravado enquanto o servidor não aceitar
  a conta;
- **O erro do Gmail engana.** Senha comum no lugar da senha de aplicativo devolve
  `535 Username and Password not accepted`, que se lê como "senha errada" — e a
  pessoa vai reconferir a senha certa várias vezes. O script traduz os erros
  conhecidos para o que realmente é preciso fazer;
- **A senha não fica no histórico do terminal.** Ela é digitada em `getpass`, sem
  eco, e nunca é impressa de volta — nem no sucesso, nem no erro.

O script mostra no fim as mesmas linhas para colar no Portainer, porque o `.env`
daqui não alcança homologação (ver docs/PORTAINER-HOMOLOGACAO.md).
"""

from __future__ import annotations

import getpass
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENV = RAIZ / ".env"

HOST = "smtp.gmail.com"
PORTA = 587


def _perguntar(rotulo: str, padrao: str = "") -> str:
    sufixo = f" [{padrao}]" if padrao else ""
    resposta = input(f"{rotulo}{sufixo}: ").strip()
    return resposta or padrao


def _testar(usuario: str, senha: str, destino: str, remetente_nome: str) -> str:
    """Manda a mensagem de teste. Devolve "" quando deu certo, ou o motivo.

    O motivo volta como texto pronto para o usuário — não como a exceção crua,
    que no caso do Gmail é uma linha de protocolo com um link de ajuda no meio.
    """
    mensagem = EmailMessage()
    mensagem["From"] = formataddr((remetente_nome, usuario))
    mensagem["To"] = destino
    mensagem["Subject"] = "Acervo — teste de envio"
    mensagem.set_content(
        "Se você está lendo isto, o SMTP do Acervo está funcionando.\n\n"
        "É por este caminho que o código de acesso de 6 dígitos vai sair a cada "
        "login dos perfis internos.\n\n"
        "Esta mensagem é automática — não responda."
    )

    try:
        with smtplib.SMTP(HOST, PORTA, timeout=15) as servidor:
            servidor.starttls(context=ssl.create_default_context())
            servidor.login(usuario, senha)
            servidor.send_message(mensagem)
    except smtplib.SMTPAuthenticationError as erro:
        # 535 é o que o Gmail devolve tanto para senha errada quanto para senha
        # COMUM usada no lugar da de aplicativo — e o segundo caso é o comum.
        if erro.smtp_code == 535:
            return (
                "O Google recusou a conta (535).\n\n"
                "  Quase sempre é a senha da CONTA usada no lugar da senha de\n"
                "  APLICATIVO. Elas são coisas diferentes: a de aplicativo tem 16\n"
                "  letras e é gerada em myaccount.google.com/apppasswords (a opção\n"
                "  só aparece com a verificação em duas etapas ligada).\n\n"
                "  Se a conta é do Workspace e a opção não existe, quem administra\n"
                "  o domínio precisa liberar as senhas de aplicativo no admin."
            )
        return f"O servidor recusou a autenticação: {erro}"
    except smtplib.SMTPRecipientsRefused:
        return f"O servidor aceitou a conta mas recusou o destinatário {destino}."
    except (TimeoutError, OSError) as erro:
        return (
            f"Não foi possível alcançar {HOST}:{PORTA} — {erro}\n\n"
            "  Costuma ser firewall ou rede corporativa bloqueando a porta 587."
        )
    except Exception as erro:  # noqa: BLE001
        return f"Falhou: {erro!r}"
    return ""


def _gravar(usuario: str, senha: str, remetente_nome: str) -> None:
    """Atualiza as linhas SMTP_* do `.env`, preservando o resto do arquivo."""
    linhas = ENV.read_text(encoding="utf-8").splitlines()
    novos = {
        "SMTP_HOST": HOST,
        "SMTP_PORTA": str(PORTA),
        "SMTP_SEGURANCA": "starttls",
        "SMTP_USUARIO": usuario,
        "SMTP_SENHA": senha,
        # Igual ao usuário de propósito: remetente de outro domínio faz o
        # destinatário conferir SPF/DKIM, não achar autorização, e mandar para o
        # spam. Código de acesso no spam é o mesmo que código nenhum.
        "SMTP_REMETENTE": usuario,
        "SMTP_REMETENTE_NOME": remetente_nome,
    }

    vistos = set()
    for i, linha in enumerate(linhas):
        chave = linha.split("=", 1)[0].strip()
        if chave in novos:
            linhas[i] = f"{chave}={novos[chave]}"
            vistos.add(chave)

    for chave, valor in novos.items():
        if chave not in vistos:
            linhas.append(f"{chave}={valor}")

    ENV.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main() -> int:
    if not ENV.exists():
        print(f"Não achei {ENV}. Copie o .env.example para .env antes.")
        return 1

    print("Conta do Gmail que vai ENVIAR os códigos de acesso do Acervo.")
    print("A senha pedida é a SENHA DE APLICATIVO (16 letras), não a da conta.")
    print("Gere em: https://myaccount.google.com/apppasswords\n")

    usuario = _perguntar("E-mail da conta de envio")
    if not usuario or "@" not in usuario:
        print("Precisa ser um endereço de e-mail.")
        return 1

    # `getpass` e não `input`: sem eco na tela e fora do histórico do terminal.
    senha = getpass.getpass("Senha de aplicativo (não aparece na tela): ")
    # O Google mostra a senha em quatro blocos separados por espaço, e quem copia
    # da tela traz os espaços junto. Ele aceita das duas formas; tirar aqui evita
    # que um espaço colado a mais vire "senha recusada".
    senha = senha.replace(" ", "").strip()
    if len(senha) != 16:
        print(f"\nAviso: senha de aplicativo tem 16 letras, esta tem {len(senha)}.")
        if _perguntar("Continuar mesmo assim? (s/N)", "N").lower() != "s":
            return 1

    remetente_nome = _perguntar("Nome que aparece como remetente", "Acervo — LARA & MELO Advogados")
    destino = _perguntar("Mandar o teste para", usuario)

    print(f"\nTestando envio por {HOST}:{PORTA}…")
    erro = _testar(usuario, senha, destino, remetente_nome)
    if erro:
        print(f"\nNADA FOI GRAVADO.\n\n{erro}")
        return 1

    _gravar(usuario, senha, remetente_nome)
    print(f"\nEnviado. Confira a caixa de {destino} (olhe o spam na primeira vez).")
    print(f"Gravado em {ENV}.\n")
    print("Para HOMOLOGAÇÃO, as mesmas variáveis na stack do Portainer:\n")
    print(f"  SMTP_HOST={HOST}")
    print(f"  SMTP_PORTA={PORTA}")
    print("  SMTP_SEGURANCA=starttls")
    print(f"  SMTP_USUARIO={usuario}")
    print("  SMTP_SENHA=<a mesma senha de aplicativo>")
    print(f"  SMTP_REMETENTE={usuario}")
    print("  DOIS_FATORES_OBRIGATORIO=1")
    print("\nAqui no .env local o OBRIGATORIO segue 0; suba a API para o segundo")
    print("fator passar a valer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
