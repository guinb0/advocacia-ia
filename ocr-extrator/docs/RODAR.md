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
observabilidade, Jitsi (:8081), agente jurídico (:8011 + worker Dramatiq),
transcrição/Whisper (:8200), API (:8100), workers Celery e frontend (:3000). Se
o agente já estiver em :8011, reutiliza o processo; `-SemAgente` não o sobe.
`-SemJitsi` pula somente as chamadas remotas.

Na primeira execução, o script também instala as dependências Python e Node. Se
`docker-jitsi-meet` ainda não existir ao lado dos repositórios, ele clona o
projeto oficial, cria a `.env` local com senhas aleatórias, prepara os volumes e
sobe web, Prosody, Jicofo e JVB. As imagens usam a tag oficial `stable`, nunca o
fallback `unstable` do Compose.

Antes de alterar qualquer coisa, o bootstrap verifica `docker`, `uv` e `npm` e
confirma que o Docker Desktop responde. Assim a inicialização para na causa, em
vez de deixar metade dos serviços no ar e falhar muitos minutos depois.

O agente lê **somente** `ia-juridica/.env`. Em especial, não herda a
`DATABASE_URL` do Acervo, que aponta para o corpus pgvector e seria o banco
errado para o Case State.

## Endereços por ambiente

Nenhuma URL pública precisa ficar presa a `localhost`. Configure na `.env`:

```env
APP_BIND_HOST=0.0.0.0
APP_PUBLIC_URL=https://app.hom.exemplo.com
OCR_API_PUBLIC_URL=https://api.hom.exemplo.com
TRANSCRICAO_PUBLIC_URL=https://transcricao.hom.exemplo.com
KEYCLOAK_PUBLIC_URL=https://login.hom.exemplo.com
JITSI_PUBLIC_URL=https://meet.hom.exemplo.com
JITSI_ADVERTISE_IPS=203.0.113.10
```

Para teste em outro aparelho na mesma rede, troque os domínios pelo IPv4 da
máquina que executa o projeto. API, Whisper, agente e Next escutam em `0.0.0.0`.
O navegador, porém, só libera microfone, câmera e compartilhamento de tela em
HTTPS ou `localhost`; homologação e produção precisam de HTTPS válido.

O bootstrap inclui `APP_PUBLIC_URL` no CORS e no cliente `acervo-frontend` do
Keycloak. O Jitsi recebe `JITSI_PUBLIC_URL` e `JITSI_ADVERTISE_IPS` na própria
`.env`, portanto o endereço que o navegador usa é também o que o JVB anuncia.

## Dependências externas

| O quê | Onde | Sem ele |
|---|---|---|
| Keycloak | contêiner `acervo-keycloak`, :8180 | ninguém entra |
| SQL Server | 177.131.142.42:1433 | nada persiste |
| pgvector | 10.200.1.1:5432, **atrás da VPN** | some recomendação, análise por precedentes e a aba Dados |
| Redis | contêiner, :6380 | fila e lock de GPU param |
| Postgres de jobs | contêiner, :5434 | histórico de jobs |
| Jitsi | criado/subido automaticamente, :8081 | entrevista só presencial |
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
curl http://localhost:8081/libs/lib-jitsi-meet.min.js
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
