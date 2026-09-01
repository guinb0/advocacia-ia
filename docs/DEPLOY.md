# Publicação do Acervo

Para quem vai colocar o Acervo no ar. O repositório já traz `Dockerfile`, os
compose e o `.gitlab-ci.yml` no padrão da casa — componente
`components/ci-platform/pipeline-generic`, roteamento por Traefik, sem porta
publicada, como no **vig-agent**.

O que ainda depende de decisão sua está em **"Falta você decidir"**, no fim.

---

## Como está montado

Uma imagem só para o repositório inteiro, porque é isso que o pipeline
constrói. Quem vira serviço diferente é o `command`:

| serviço | comando | porta interna |
|---|---|---|
| `frontend` | `node frontend/server.js` (Next standalone) | 3000 |
| `api` | `uvicorn app.main:app` (padrão do Dockerfile) | 8100 |
| `transcricao` | `uvicorn app.servico_transcricao:app` | 8200 |
| `worker` | `celery worker` — é onde o OCR roda | — |
| `beat` | `celery beat` | — |
| `redis` | broker do Celery, interno à stack | — |

O front é Node e o resto é Python. Em vez de duas imagens (que o pipeline não
constrói), o binário `node` é copiado para dentro da imagem Python — o build
`standalone` do Next só precisa dele.

### Um domínio só, e o Traefik decide pelo caminho

Homologação é **`advocacia.levelhom.com.br`**. Produção **ainda não tem
domínio** — e por isso a stack de produção não sobe até alguém definir um
(explicado abaixo).

Um domínio só atende os três serviços que o navegador chama:

| caminho | vai para | prioridade |
|---|---|---|
| `/ws/transcricao`, `/entrevista` | `transcricao` | 200 |
| `/api`, `/ws/chamada` | `api` | 100 |
| todo o resto | `frontend` | 1 |

**Por que não um subdomínio para cada.** O login é um cookie HttpOnly assinado
pela API, e front e API precisam ser o *mesmo site* para ele acompanhar a
chamada — está registrado no `.env.example`, ao lado de `JWT_COOKIE_SAMESITE`.
Com um domínio só, cookie e CORS deixam de ser problema e as `NEXT_PUBLIC_*`
ficam vazias.

**Isso não reintroduz o proxy do Next**, que foi removido de propósito
(`frontend/next.config.ts`): quem roteia é o Traefik, na borda, sem o teto de
30s nem o buffer em memória que matavam upload de foto de celular.

`/metrics`, `/docs` e `/redoc` **não** têm rota — ficam alcançáveis só de dentro
da stack. Expor o `/metrics` publicaria a telemetria do escritório.

O WebSocket da transcrição não precisa de label especial: o Traefik repassa o
`Upgrade` sozinho. O que precisa é da prioridade acima do front.

---

## Arquivos

| arquivo | o que é |
|---|---|
| `Dockerfile` | multi-stage: Next standalone → runtime Python |
| `.dockerignore` | tira `.venv`, `node_modules`, `.env` e `dados/` do contexto |
| `docker-compose.production.yml` | stack de produção |
| `docker-compose.homologation.yml` | idêntica, em `advocacia.levelhom.com.br` |
| `.gitlab-ci.yml` | as duas rotas + `tsc` e testes nas outras branches |
| `deploy/jitsi/` | o que falta na stack do Jitsi para atender cliente remoto |
| `docker-compose.yml` | **não é deploy.** É a stack local (redis, jobs-db, flower, prometheus, grafana) que o `iniciar.ps1` levanta na máquina de quem desenvolve |

O último importa: `docker-compose.yml` já existia com outro propósito, então as
stacks de deploy têm nome próprio, declarado em `compose_file` no
`.gitlab-ci.yml`.

### Detalhes da imagem que custaram para descobrir

- **Python 3.11 é teto, não preferência.** O `paddlepaddle` não publica wheel
  para 3.13+. Mesmo motivo do `uv venv --python 3.11` no `iniciar.ps1`.
- **`libgssapi-krb5-2` está listada explicitamente** e não pode sair. Ela entra
  como dependência do `curl`, e o `autoremove` a levava embora *depois* de o
  driver ODBC estar instalado. O sintoma engana: o unixODBC diz `file not found`
  apontando para o `.so` do driver, que está lá — quem falta é a biblioteca que
  ele carrega. Medido: sem ela, `pyodbc.connect` falha dentro da imagem.
- **`msodbcsql18` é instalado à mão.** Não há wheel que traga o driver. O Driver
  18 liga criptografia por padrão e o servidor não tem certificado emitido;
  funciona porque `app/banco.py` já fixa `TrustServerCertificate=yes`.
- **`docs/` entra na imagem.** Não é documentação morta: os `.docx` oficiais
  (contrato, procuração, declaração) são lidos dali por `app/contrato.py`. Sem
  eles a geração da papelada quebra.
- **OCR roda em CPU de propósito.** A wheel de GPU é 17x mais rápida e foi
  revertida: o caminho CUDA devolve caixas com geometria diferente e a extração
  de campos quebra. Medido em `requirements.txt` e em `docs/SISTEMA.md`.
- **A imagem tem ~3,3 GB**, quase toda de `paddlepaddle`. É o preço do OCR local.

---

## Variáveis

Seguindo o vig-agent, **só segredo** vira variável do GitLab. O resto (domínios,
modelos, portas de banco) está fixo no compose, onde se lê junto com o contexto.

Precisam existir em **Settings → CI/CD → Variables**, com o *environment scope*
`prod` ou `homolog`:

```
DOMINIO             (só em produção — ver abaixo)
SQLSERVER_HOST      SQLSERVER_PASSWORD
PGVECTOR_HOST       PGVECTOR_USER        PGVECTOR_PASSWORD
JWT_SECRET          PORTAL_SEGREDO
DEEPSEEK_API_KEY    OPENROUTER_API_KEY
ZAPSIGN_API_TOKEN   DATAJUD_API_KEY
EVOLUTION_API_KEY   EVOLUTION_INSTANCE
```

Todas usam a forma `${VAR?VAR is required}` no compose: **faltando qualquer
uma, a stack recusa subir em vez de subir quebrada.**

**`DOMINIO` existe só na rota de produção.** Homologação tem o domínio fixo no
compose porque ele já existe; produção não tem domínio ainda, e em vez de
inventar um placeholder que faria deploy silencioso no lugar errado, a stack
usa `${DOMINIO?defina o dominio de producao}`. O efeito é que **produção não
sobe** enquanto ninguém cadastrar a variável — que é o comportamento certo para
algo que ainda não foi decidido.

Duas merecem atenção:

- **`JWT_SECRET` vazio desliga a autenticação** e abre a API inteira. É o que o
  `iniciar.ps1 -SemAuth` faz em desenvolvimento.
- **`PORTAL_SEGREDO` vazio** faz o servidor sortear uma chave por processo, e as
  sessões do portal do cliente caem a cada restart.

`PGVECTOR_HOST` aponta hoje para `10.200.1.1`, endereço de VPN. Se o cluster não
alcançar, o sistema sobe e funciona, mas a busca de precedentes volta vazia.

---

## A chamada por vídeo

Três coisas separam o que funciona no escritório do que funciona com cliente em
casa. Estão em `deploy/jitsi/`.

**1. `JVB_ADVERTISE_IPS` com IP público.** Hoje vale `192.168.5.241` — endereço
que só existe dentro do escritório. O videobridge anuncia isso para o navegador
do cliente, que não alcança. Não é "rede difícil": é impossível para todo mundo
de fora. É o bloqueio maior dos três.

**2. HTTPS.** Navegador nenhum libera microfone fora de `localhost` sem
certificado. Com o Traefik na frente e `DISABLE_HTTPS=1` no Jitsi, resolve junto
com o resto.

**3. TURN** (`deploy/jitsi/docker-compose.coturn.yml`). O áudio vai por UDP na
10000; funciona na maioria das redes e falha justamente em 4G de operadora e
rede de empresa. Aí a chamada **abre e ninguém ouve ninguém** — o pior sintoma,
porque parece que deu certo. O coturn escuta em 443/TCP e repassa.

De brinde, o TURN cala um erro antigo: a `lib-jitsi-meet` pergunta ao Prosody
por servidores de STUN/TURN assim que conecta (XEP-0215) e não há como desligar
essa pergunta no cliente. Sem TURN, o Prosody responde `service-unavailable` e a
lib registra dois `ERROR` no console a cada entrada na sala. A imagem só carrega
o módulo `external_services` quando `TURN_HOST` existe.

**A 443 do TURN e a 443 do Traefik são a mesma porta** e não cabem no mesmo IP.
As saídas estão comentadas no compose do coturn; a escolha depende de quantos
IPs o cluster tem.

---

## Falta você decidir

1. **O domínio de produção.** Homologação já está em
   `advocacia.levelhom.com.br`. Produção espera a variável `DOMINIO` — sem ela
   a stack recusa subir, de propósito. `meet.` e `turn.` continuam chute meu,
   no padrão `<nome>.level33lab.cloud` do vig-agent.
2. **O IP público do TURN e do JVB**, e como resolver o conflito da 443.
3. **O volume `dados/` em Swarm.** `api` e `worker` gravam no mesmo volume
   nomeado — é onde ficam arquivos de caso e contratos assinados. Volume nomeado
   em Swarm é **por nó**: se caírem em nós diferentes, cada um vê uma pasta
   vazia e o advogado recebe "documento não encontrado" sem erro no log. Ou os
   dois ganham `placement constraint` no mesmo nó, ou isso vira armazenamento
   compartilhado. Não resolvi porque depende de quantos nós existem — com um só,
   não há problema.
4. **O agente jurídico.** `AGENTE_API_URL` aponta para `http://ia-juridica:8011`,
   assumindo que ele tem stack própria alcançável na rede interna. Se o nome do
   serviço for outro, é uma linha no compose.

---

## Primeiro deploy

```
git checkout -b release && git push -u origin release
```

O componente gera a versão a partir da última tag `release/v*`, constrói,
publica em `registry.level33lab.cloud/ia/advocacia-ia` e cria a stack no
Portainer se ela não existir. Produção é o mesmo com a branch `production`, que
**reusa** a versão em vez de incrementar.

O componente está fixado em `@1.1.6`. Não baixe para `1.0.8` (a do novosidaf):
`gitlab_variables` e `gitlab_variables_environment` não existem lá, e é por eles
que os segredos chegam à stack.
