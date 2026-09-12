# A porta de entrada: captcha e segundo fator

O login do Acervo passou a ter três obstáculos em vez de um. Este documento diz
o que cada um faz, como ligar, e o que acontece quando não está ligado.

---

## O que mudou

Antes: e-mail + senha, e a sessão nascia na hora.

Agora:

1. **Captcha (Cloudflare Turnstile)** — o navegador prova que é navegador antes
   de a senha ser sequer conferida;
2. **Senha** — como sempre, MD5 vindo do navegador contra a coluna `senha_md5`;
3. **Código de 6 dígitos por e-mail** — exigido de **todos os perfis internos**
   (`advogado`, `secretario`, `documentacao` e qualquer perfil novo). `cliente`
   fica de fora: ele entra pelo portal, com link próprio, e não tem senha do
   escritório.

**A sessão só nasce no passo 3.** Quem acerta a senha e para ali não recebe
cookie nenhum — o que ele tem é um identificador de desafio, que não abre nada.

### Por que essas duas medidas, e não outras

A senha aqui é **MD5 sem sal** (ver o cabeçalho de `app/usuarios.py`). Isso
significa duas fraquezas concretas:

- tentativa automatizada é barata → **o captcha** fecha isso;
- um vazamento da tabela `acervo_usuarios` devolve as senhas em claro → **o
  segundo fator** faz esse vazamento deixar de ser acesso imediato.

O segundo fator por e-mail tem um limite que vale dizer em voz alta: **quem
controlar a caixa de e-mail da pessoa passa por ele.** Ele protege contra senha
vazada, não contra e-mail comprometido. O TOTP (app autenticador) não teria essa
dependência — trocar depois é substituir `app/dois_fatores.py`, sem tocar nas
rotas nem na tela.

---

## As rotas

| Rota | O que faz |
|---|---|
| `POST /api/user/authenticate` | Captcha + senha. Devolve `etapa: "sessao"` (acabou) ou `etapa: "dois_fatores"` (falta o código) |
| `POST /api/user/authenticate/verify` | Confere o código e **grava o cookie** |
| `POST /api/user/authenticate/resend` | Manda um código novo para o mesmo desafio |
| `GET /api/config` | Diz à tela se há captcha e com que `site_key` |

O corpo do `resend` traz **só o identificador do desafio**, nunca um e-mail:
aceitar um endereço ali transformaria a rota num disparador de e-mail em nome do
escritório, sem ninguém precisar de senha.

---

## Ligando o captcha

1. Em `dash.cloudflare.com` → **Turnstile** → *Add site*. É gratuito e sem teto.
2. Cadastre **o domínio publicado e `localhost`** (senão o desenvolvimento fica
   sem widget).
3. No `.env`:

```ini
TURNSTILE_SITE_KEY=0x4AAA...      # pública, vai para o navegador
TURNSTILE_SECRET_KEY=0x4AAA...    # fica só no servidor
```

**`TURNSTILE_SECRET_KEY` vazio desliga o captcha** e o log grita. A tela não
desenha widget nenhum nesse caso — não fica uma caixa vazia sem explicação.

`TURNSTILE_FALHA_ABERTA=1` (padrão) deixa a tentativa passar quando a Cloudflare
está inalcançável: indisponibilidade de terceiro não pode trancar o escritório
para fora do próprio sistema, e a senha e o segundo fator continuam valendo.
`=0` recusa.

> A `site_key` chega ao navegador pelo `/api/config`, e **não** por uma
> `NEXT_PUBLIC_*`. O motivo está no `.env.example`: variável embutida no bundle
> já quebrou o sistema quando ele foi aberto de outro computador.

---

## Ligando o segundo fator

Ele depende de um SMTP. Sem servidor de e-mail não há como entregar o código.

```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORTA=587
SMTP_SEGURANCA=starttls          # starttls (587) | ssl (465) | nenhuma (25)
SMTP_USUARIO=sistema@escritorio.com.br
SMTP_SENHA=xxxx xxxx xxxx xxxx   # SENHA DE APLICATIVO, não a da conta
SMTP_REMETENTE=sistema@escritorio.com.br
SMTP_REMETENTE_NOME=Acervo — Escritório jurídico

DOIS_FATORES_OBRIGATORIO=1       # PRODUÇÃO
```

**Gmail / Google Workspace**: `smtp.gmail.com:587`, `starttls`, e uma **senha de
aplicativo** — a senha da conta não funciona com verificação em duas etapas
ligada. **Office 365**: `smtp.office365.com:587`, `starttls`. **Relay interno sem
autenticação**: deixe `SMTP_USUARIO` vazio e use `SMTP_SEGURANCA=nenhuma`.

### O interruptor que importa

`DOIS_FATORES_OBRIGATORIO` decide o que acontece **quando o SMTP não está
configurado**:

- **`0`** (padrão): o login passa só com a senha, e o log grita
  `SEGUNDO FATOR PULADO`. É o que permite rodar em desenvolvimento sem SMTP;
- **`1`**: o login é **recusado** com 503. É a diferença entre "o segundo fator
  está ligado" e "está ligado quando dá".

**Em produção, `1`.** Os composes de produção e homologação já vêm com esse
padrão.

### Os outros ajustes

| Variável | Padrão | O que faz |
|---|---|---|
| `DOIS_FATORES_VALIDADE_MIN` | 10 | Quanto tempo o código vale |
| `DOIS_FATORES_TENTATIVAS` | 5 | Erros antes de o desafio morrer |
| `DOIS_FATORES_ENVIOS` | 3 | Reenvios por desafio |
| `DOIS_FATORES_ESPERA_REENVIO_S` | 60 | Espera mínima entre reenvios |
| `DOIS_FATORES_PERFIS_ISENTOS` | `cliente` | Quem NÃO passa pelo segundo fator |

Seis dígitos são um milhão de combinações; sem limite, um robô as percorre em
minutos. Por isso o desafio morre por três caminhos, e **o contador de
tentativas não zera no reenvio** — se zerasse, pedir código novo seria o jeito
de tentar para sempre.

---

## O que o banco guarda

Uma tabela nova, `dbo.acervo_login_desafios`, criada sozinha no start junto de
`usuarios.inicializar()`. Ela guarda o **SHA-256 do código**, salgado com o
`JWT_SECRET` e com o id do desafio — um SELECT durante os dez minutos de validade
não entrega o acesso de ninguém.

As linhas mortas são varridas a cada desafio novo e no start. Não há agendamento
para isso: é um DELETE contra uma tabela que nunca passa de algumas dezenas de
registros.

---

## Testando

```powershell
.venv\Scripts\python.exe -m tests.test_login_dois_fatores
```

Cobre o ciclo feliz, código errado, expiração, limite de tentativas, reenvio com
espera, as duas etapas das rotas e o captcha — com o banco substituído por um
dicionário, então roda em qualquer máquina, sem VPN.

Para conferir o SMTP de verdade sem passar pelo login:

```powershell
.venv\Scripts\python.exe -c "from app import correio; correio.enviar(para='voce@exemplo.com', assunto='teste', texto='funciona')"
```

---

## Quando algo dá errado

**"Confirme que você não é um robô"** com o widget aparecendo — o token ainda não
resolveu. Ele leva alguns segundos; o botão de entrar avisa em vez de mandar uma
tentativa que seria recusada.

**"A verificação de segurança expirou"** — o token do Turnstile vale uma vez só e
por poucos minutos. A tela já reinicia o widget depois de cada tentativa falha;
se persistir, recarregar a página resolve.

**O widget não aparece** — ou `TURNSTILE_SECRET_KEY` está vazio (então é
esperado), ou o script da Cloudflare foi bloqueado por extensão de privacidade ou
firewall corporativo. Nesse segundo caso o login continua funcionando enquanto
`TURNSTILE_FALHA_ABERTA=1`.

**O código não chega** — olhe o log da API por `falha ao enviar e-mail`. Ele traz
o motivo do SMTP (credencial, porta, TLS) mas **não** o destinatário: e-mail de
usuário é dado pessoal e o log é lido por mais gente que o banco.

**"O segundo fator está indisponível"** (503) — `DOIS_FATORES_OBRIGATORIO=1` com
SMTP faltando. É o comportamento pedido: recusar em vez de deixar passar só com a
senha.
