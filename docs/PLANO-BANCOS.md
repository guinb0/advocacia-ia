# Plano — sair dos bancos locais para os bancos de verdade

Escrito em 13/08/2026, com os números medidos **ao vivo** nesta data. Cobre os dois
sistemas: o Acervo (este repositório) e o agente jurídico (`ia-juridica`), que passou
a ser consumido daqui pelo módulo `app/agente/`.

Nada abaixo foi executado. É a sequência proposta, com o que cada passo exige de
quem tem a chave.

---

## 1. Onde os dados estão hoje — levantamento medido

| Onde | O quê | Como está |
|---|---|---|
| `10.200.1.1:5432 / advocacia_ia` | corpus de jurisprudência | **real e em uso.** PostgreSQL 18.3, `vector 0.8.2`, `pg_trgm`, `unaccent`. 52.926 trechos, 5.826 fontes, **44.922 vetorizados (84,9%)**, 1.745 processos distintos, `vector(1536)` |
| `10.200.1.1:5432 / advocacia_ia` | tabela `entrevistas` | existe e está **vazia** (0 linhas) |
| `dados/casos.db` (SQLite, este repo) | casos, entregas, assinaturas, vínculo com o agente | **local**, na máquina do advogado |
| `dados/casos/<id>/` | os arquivos enviados pelo cliente | **local**, fora do git |
| Docker `localhost:5433 / legal_agent` | Case State do agente: fatos, evidências, classificações, pendências, pesquisas, precedentes | **local**, contêiner de desenvolvimento |
| Docker `localhost:5434` | banco de teste do agente | local, efêmero (tmpfs) — continua assim |
| Docker `localhost:6379` | Redis: fila do agente e cache do Case State | local |

Dois pontos que o `.env.example` ainda descreve errado e valem correção junto com
este plano:

- **`JURIMETRIA_DATABASE_URL=postgresql://juri:juri@localhost:5433/juri` aponta para
  porta ocupada.** Nesta máquina, a 5433 é o Postgres do agente (`legal_agent`), não
  o banco da jurimetria — a credencial `juri` é recusada ali. Ou o serviço mudou de
  porta, ou a variável ficou para trás;
- **`CONTEXTO.md` diz que o banco vetorial está vazio** numa seção e traz o
  checkpoint com 52.926 chunks em outra. A primeira ficou para trás.

### O achado de segurança que muda a ordem das coisas

A conexão que os dois sistemas usam hoje para o `advocacia_ia` é a do usuário
**`bezerra`, que é `superuser` do servidor**. Esse servidor é compartilhado: nele
convivem `vigdigital_agent`, `visadf`, `portos_prod`, `speedcoffe_*`,
`gitlab_engineering_analytics`, `dflegal` e outros — 21 bancos ao todo.

Ou seja: hoje o backend do OCR e o agente jurídico rodam com credencial capaz de
apagar o banco de outro sistema. Isso não é um detalhe de higiene — é o item que
precisa ser resolvido **antes** de a escrita de casos reais ir para lá, e é o
primeiro passo do plano.

---

## 2. O destino escolhido

**Schema `agente` dentro do banco `advocacia_ia`**, no mesmo servidor.

Por quê:

- não depende de `CREATE DATABASE` num servidor compartilhado, que é decisão do DBA;
- o Case State fica ao lado do corpus que a pesquisa jurídica consulta — mesma
  janela de backup, mesma janela de manutenção;
- separar por schema mantém a fronteira: o corpus continua sendo `public`, e o
  usuário da aplicação recebe permissão de escrita **só** no schema novo.

O que **não** muda: `public.knowledge_chunks` e `public.fontes` seguem sendo fonte
externa read-only para o agente. A separação de credenciais abaixo é o que torna isso
verdade no banco, e não só no código.

---

## 3. Passos

### Passo 1 — credenciais próprias (bloqueia todo o resto)

Executado por quem tem acesso administrativo ao servidor. Três papéis, nenhum deles
superusuário:

```sql
-- Aplicação do agente: escreve no schema próprio, lê o corpus.
CREATE ROLE legal_agent_app LOGIN PASSWORD '<segredo forte>';
CREATE SCHEMA IF NOT EXISTS agente AUTHORIZATION legal_agent_app;
GRANT USAGE ON SCHEMA public TO legal_agent_app;
GRANT SELECT ON public.knowledge_chunks, public.fontes TO legal_agent_app;

-- Leitor do corpus, usado pela pesquisa jurídica e pelo RAG do Acervo.
CREATE ROLE corpus_reader LOGIN PASSWORD '<segredo forte>';
GRANT USAGE ON SCHEMA public TO corpus_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO corpus_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO corpus_reader;

-- Migrations: só ele cria e altera tabela no schema do agente.
CREATE ROLE legal_agent_ddl LOGIN PASSWORD '<segredo forte>';
GRANT ALL ON SCHEMA agente TO legal_agent_ddl;
```

Conferência (é o teste que prova o passo, não a confiança de que o SQL rodou):

```sql
SET ROLE corpus_reader;
INSERT INTO public.fontes (tipo) VALUES ('x');   -- precisa FALHAR
SET ROLE legal_agent_app;
DROP TABLE public.knowledge_chunks;              -- precisa FALHAR
```

Depois disto, **rotacionar a senha do `bezerra`** e tirá-la dos `.env` dos dois
projetos. Ela já circulou por chat (ver "Segurança" no `CONTEXTO.md`).

### Passo 2 — apontar o agente para o schema novo

No `.env` do `ia-juridica`:

```ini
DATABASE_URL=postgresql://legal_agent_app:<segredo>@10.200.1.1:5432/advocacia_ia?options=-csearch_path%3Dagente
JURISPRUDENCE_DATABASE_URL=postgresql://corpus_reader:<segredo>@10.200.1.1:5432/advocacia_ia
```

E no `alembic.ini` / `ALEMBIC_DATABASE_URL`, a conexão do `legal_agent_ddl` com o
mesmo `search_path`.

Duas coisas a acertar no código antes de rodar migration lá:

1. **`version_table_schema`** no `migrations/env.py` — sem isso o Alembic grava
   `alembic_version` no `public`, e o controle de versão do agente passaria a morar
   no schema do corpus;
2. **`search_path` na conexão do SQLAlchemy** (via `connect_args` ou o parâmetro
   `options` acima). Cravar `schema="agente"` nos modelos também funciona, mas
   quebraria o banco de teste local, que não tem o schema.

### Passo 3 — migrations no destino

```bash
ALEMBIC_DATABASE_URL='...legal_agent_ddl...' uv run alembic upgrade head
```

São 7 revisões (`0001` … `0007`). Nenhuma delas cria extensão nem toca em `public`.
A `0007` é a da pesquisa jurídica.

Confira depois: `\dt agente.*` precisa listar 20+ tabelas e `agente.alembic_version`
precisa marcar `0007`.

### Passo 4 — o que fazer com o dado local que já existe

O banco Docker `legal_agent` tem apenas casos de desenvolvimento e os dois casos que
a validação da ponte criou em 13/08. **Recomendação: não migrar nada.** Começar
limpo no destino, e recriar os casos reais pelo Acervo — que é a origem deles.

Se um dia precisar migrar de verdade, a ordem é a das chaves estrangeiras
(`organizations → clients → cases → …`), com `pg_dump --data-only --schema=public`
restaurado em `--schema=agente`. Fazer isso **depois** de o schema existir e com o
sistema parado; um dump de caso pela metade é pior que nenhum caso.

### Passo 5 — Redis

Hoje `redis://localhost:6379/0`, no contêiner. Quando o agente sair da máquina do
escritório, ele precisa de um Redis alcançável pelos dois processos (API e worker).
Enquanto os dois rodarem no mesmo Docker Compose, o de agora serve — **a fila não é
o gargalo, e trocar de Redis não é pré-requisito para trocar de banco**.

Um detalhe medido em 13/08 durante a validação da ponte: o worker estava de pé desde
o dia anterior e **não consumia a fila** — cinco documentos ficaram esperando em
`dramatiq:document_processing` sem qualquer erro visível. Reiniciar o worker drenou
tudo. Antes de mover infraestrutura, vale um alarme simples de fila parada; caso
contrário o sintoma será "o dossiê não mostra os fatos" e ninguém vai olhar a fila.

### Passo 6 — os casos do Acervo (SQLite)

**Fica para depois, e a decisão é do escritório.** O SQLite é local por um motivo
declarado no código: os arquivos são de clientes e não devem sair da máquina. Trocar
para Postgres remoto muda essa premissa e exige antes:

- HTTPS de ponta a ponta (hoje o portal do cliente trafega senha em HTTP);
- decisão de retenção e base legal na LGPD para relato de entrevista, que contém CPF
  e dado de saúde — o servidor de destino é compartilhado com outros sistemas;
- destino dos **arquivos** (hoje `dados/casos/<id>/`), que um banco não resolve.

Quando acontecer, o caminho é o mesmo do agente: schema próprio (`acervo`), usuário
próprio, e o SQLite vira o modo de desenvolvimento — não um segundo lugar onde o dado
mora ao mesmo tempo.

### Passo 7 — autenticação entre os dois sistemas

Hoje o agente roda com `AUTH_ENABLED=false` e a ponte não manda token. Para ligar a
autenticação de verdade, faltam duas coisas no token que o Acervo assina
(`app/auth.py`) — e o agente precisa passar a aceitar a mesma chave:

1. **mapper de `organization_id`** — o agente exige essa claim para escopar o tenant.
   Hoje o realm emite só `audience: acervo-api` e a role `advogado`;
2. **mapa de papéis** — o agente espera `ADMIN`/`LAWYER`/`ASSISTANT`; o realm tem
   `advogado`. Ou o realm passa a emitir os nomes que o agente conhece, ou o agente
   aprende a traduzir. A segunda opção é uma linha em `config/security.py`.

Enquanto isso não existir, `AGENTE_TOKEN` fica vazio e o agente só deve responder
dentro da rede do escritório.

---

## 4. Ordem sugerida e o que cada passo exige

| # | Passo | Depende de | Reversível? |
|---|---|---|---|
| 1 | Credenciais próprias + rotação da senha do `bezerra` | acesso administrativo ao servidor | sim |
| 2 | `search_path` e `version_table_schema` no agente | passo 1 | sim (é código) |
| 3 | `alembic upgrade head` no schema `agente` | passos 1 e 2 | sim (`downgrade`) |
| 4 | Apontar `.env` do agente para o servidor real | passo 3 | sim (troca de variável) |
| 5 | Alarme de fila parada | — | sim |
| 6 | Casos do Acervo para Postgres | HTTPS + decisão LGPD | não trivial |
| 7 | Autenticação ponta a ponta | claim `organization_id` no token | sim |

Os passos 1 a 4 são de uma tarde. O 6 é um projeto à parte, e não deve ser embutido
neste.

---

## 5. Como saber se deu certo

Não por "subiu sem erro", e sim por estas quatro conferências:

1. `SELECT count(*) FROM agente.cases;` responde no servidor real, e o mesmo número
   aparece na lista de casos do agente;
2. `corpus_reader` **não** consegue escrever em `public` (o `INSERT` do passo 1 falha);
3. um documento enviado pelo Acervo vira fato no agente e aparece no dossiê — foi
   exatamente esse caminho que a validação de 13/08 percorreu contra o banco local;
4. a pesquisa jurídica continua devolvendo precedente do TRT8 com a cobertura
   declarada (84,9% em 13/08) — se ela passar a falhar, é sinal de que a credencial
   nova não enxerga `public.knowledge_chunks`.
