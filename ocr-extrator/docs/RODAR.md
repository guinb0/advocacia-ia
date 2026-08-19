# Como isto roda — guia para quem cuida da infra

Dois sistemas, ligados por uma ponte de mão única. Nenhum escreve no banco do
outro: é o que permite subir, testar e reverter um sem parar o outro.

```
  Acervo (ocr-extrator)                        Agente (ia-juridica)
  ─────────────────────                        ────────────────────
  Next  :3000  tela                            FastAPI  :8011
  API   :8100  casos, documentos, contrato   →  Case State: fatos com
  Whisper :8200 transcrição ao vivo             proveniência, classificação,
                                                pesquisa de jurisprudência
        │                                              ▲
        └──────── AGENTE_API_URL (push) ───────────────┘
```

O Acervo **empurra** o que apurou e **lê** o que o agente concluiu
(`app/agente/espelho.py`). Nunca o contrário.

## Subir tudo

Antes da primeira subida, coloque os dois arquivos recebidos pelo canal seguro
(nunca Git, chat ou ticket público):

```text
ocr-extrator/.env
ia-juridica/.env
```

Se as duas aplicações usam as mesmas credenciais de SQL/IA desta instalação, o
segundo arquivo pode ser derivado sem copiar segredo à mão:

```powershell
.\scripts\gerar_env_agente.ps1 -Force
```

O gerador não imprime valores e grava num caminho coberto pelo `.gitignore`.

Depois:

```powershell
cd ocr-extrator
.\iniciar.ps1 -Prod
```

Ele carrega `ocr-extrator/.env` sozinho e levanta: Keycloak, Redis,
observabilidade, agente jurídico (:8011 + worker Dramatiq), transcrição (:8200),
API (:8100), workers Celery e frontend (:3000). Se o agente já estiver em :8011,
reutiliza o processo; `-SemAgente` não o sobe. Sem agente, o restante continua.

O agente lê **somente** `ia-juridica/.env`. Em especial, não herda a
`DATABASE_URL` do Acervo, que aponta para o corpus pgvector e seria o banco
errado para o Case State.

## Dependências externas

| O quê | Onde | Sem ele |
|---|---|---|
| Keycloak | contêiner `acervo-keycloak`, :8180 | ninguém entra |
| SQL Server | 177.131.142.42:1433 | nada persiste |
| pgvector | 10.200.1.1:5432, **atrás da VPN** | some recomendação, análise por precedentes e a aba Dados |
| Redis | contêiner, :6380 | fila e lock de GPU param |
| Postgres de jobs | contêiner, :5434 | histórico de jobs |
| Jitsi | projeto `docker-jitsi-meet`, :8081 | entrevista só presencial |
| DeepSeek | API externa | some a escuta, a análise e a auditoria |

**A VPN é a dependência que mais derruba coisa.** O pgvector só é alcançável por
ela (WireGuard). Quando cai, o sintoma na tela é "o banco de precedentes não
respondeu" — não é bug de aplicação.

## Keycloak: os dados ficam no SQL Server

O contêiner é efêmero, o **estado não**. Desde a migração, usuários e realm
gravam no SQL Server do escritório (schema `dbo` do banco `advocacia`), então
`docker compose down -v` não apaga login. Um contêiner novo reencontra tudo.

Perfis: `advogado`, `secretario`, `cliente`. A API nega por padrão quem não é
advogado nem secretário — rota nova nasce fechada.

## Armadilhas conhecidas

**Build velho servindo tela antiga.** `-Prod` serve o build de `.next`. O script
já recompila quando o fonte é mais novo e grava a assinatura de todas as
`NEXT_PUBLIC_*`. Mudou URL, porta ou modo `-SemAuth`, recompila. Isso cobre o
caso de `npm run build` manual sem variáveis e o laço de "sessão expirou".

**Segredo em script.** Não coloque senha em `iniciar.ps1`, `iniciar-local.ps1`,
README ou compose. Os scripts agora recusam iniciar sem `.env`; `.gitignore`
cobre os dois arquivos reais e só os `.env.example` entram no repositório.

**Variável global com nome genérico.** Já houve `DEBUG=release` herdado do
Windows; o agente espera booleano e não subia. O orquestrador agora limpa do
filho as chaves declaradas em `ia-juridica/.env`, e o script local faz o arquivo
do projeto vencer o ambiente herdado.

**Derrubar o frontend derruba o resto.** O `iniciar.ps1` roda o Next em primeiro
plano e mata os filhos ao sair. Matar o processo da :3000 encerra API, transcrição
e workers junto.

**Porta 8200 ocupada.** Se a transcrição foi subida fora do script, ela sobrevive
ao `Ctrl+C` e a próxima subida falha. Confira com
`netstat -ano | findstr :8200`.

**Docker Desktop depois de reboot.** Costuma responder 500 com o WSL rodando;
fechar e reabrir resolve — esperar, não.

## Conferir que está de pé

```powershell
curl http://localhost:3000                # tela
curl http://127.0.0.1:8100/api/saude      # API
curl http://127.0.0.1:8200/saude          # transcrição (modelo_carregado: true)
curl http://localhost:8180/realms/advocacia/.well-known/openid-configuration
curl $env:AGENTE_API_URL/ready            # a ponte com o agente
```

O `/saude` da transcrição devolve `modelo_carregado` e `modelo_aquecido`. Só com
os dois em `true` a primeira fala sai rápida — antes disso o Whisper ainda está
carregando (~30s) e a tela avisa.

## Onde olhar quando algo falha

- **API e workers**: saída do `iniciar.ps1`.
- **Transcrição**: mesma saída, linhas `parcial: cauda=.. nivel=.. chegada=..`.
  `nivel` abaixo de 0,03 é microfone fraco; `chegada` abaixo de 1,0 é áudio se
  perdendo antes do reconhecimento. A tela avisa dos dois.
- **Keycloak**: `docker logs acervo-keycloak`.
- **Filas**: Flower em :5555. **Métricas**: Grafana em :3001.
