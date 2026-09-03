# Ativar o Cloudflare Turnstile

O código do Turnstile já está implementado no login desde o commit `afa08e9`.
Ele permanece desativado enquanto o par de chaves não estiver configurado, para
não bloquear o acesso ao sistema.

## Quando for ativar

1. No painel da Cloudflare, abra **Turnstile** e crie um widget.
2. Use o modo **Managed**.
3. Autorize o hostname `app.forenseflow.com.br`.
4. No GitLab do projeto, abra **Settings > CI/CD > Variables**.
5. Cadastre estas variáveis:

   - `APPENV_NEXT_PUBLIC_TURNSTILE_SITE_KEY`: site key pública do widget.
   - `APPENV_TURNSTILE_SECRET_KEY`: secret key; marcar como **Masked** e **Protected**.
   - `APPENV_TURNSTILE_HOSTNAMES`: `app.forenseflow.com.br`.

6. Execute novamente o pipeline da branch `production`.
7. Abra o login em uma janela anônima e confira:

   - o widget conclui a verificação sem desafio de imagens na situação normal;
   - o botão **Entrar** só é liberado depois da verificação;
   - credenciais válidas continuam entrando;
   - o endpoint `/api/saude` continua respondendo `200`.

## Segurança

Nunca colocar `TURNSTILE_SECRET_KEY` em arquivo versionado, no frontend ou em
mensagem. Ela deve existir somente como variável protegida do GitLab e no ambiente
do backend.
