# Acervo no SQL Server

O Acervo saiu do SQLite (`dados/casos.db`) e passou a gravar no **SQL Server**, no mesmo
banco `advocacia` e no mesmo schema `dbo` onde o agente já vive. As tabelas levam o
prefixo `acervo_`, que é o que distingue os dois sistemas — sem ele, `casos` ficaria ao
lado de `cases` guardando coisa diferente.

Os **arquivos enviados pelo cliente continuam em disco** (`dados/casos/`). O que foi para
o servidor é o registro, não o binário: guardar o arquivo duas vezes seria dois lugares
para vazar o mesmo dado e duas políticas de retenção para conciliar.

## Como ficou

| | |
|---|---|
| Banco | `advocacia` em `177.131.142.42`, schema `dbo` |
| Tabelas | `acervo_casos`, `acervo_entregas`, `acervo_entrevistas`, `acervo_assinaturas`, `acervo_vinculos_agente` |
| Driver | `pyodbc` + ODBC Driver 17 for SQL Server |
| Configuração | `SQLSERVER_*` no `.env` |

## O que mudou no código

Quase nada, de propósito. A conexão foi isolada em [app/banco.py](app/banco.py), que
oferece a **mesma interface** que o `sqlite3` oferecia — `conectar()` como gerenciador de
contexto, `?` como marcador de parâmetro, linha acessível por nome de coluna. As 44
funções de `armazenamento.py` continuam escrevendo SQL como antes.

Três pontos precisaram de tradução:

1. **`INSERT OR REPLACE` não existe** no SQL Server → virou `MERGE`, em `vincular_agente`;
2. **função Python registrada na conexão** (`normalizar_nome_cliente`) não tem equivalente
   — o SQL Server não roda Python dentro da consulta. Como o nome já é gravado
   normalizado, a comparação passou a ser direta;
3. **`COLLATE NOCASE`** saiu: o banco usa `Latin1_General_CI_AS`, que já ignora
   maiúsculas.

Os `PRAGMA` e as migrações de coluna que existiam em `inicializar()` eram para bancos
SQLite antigos, criados antes de campos como `status_proc` e `portal_token`. O schema do
SQL Server nasce completo, então não há o que remendar.

## Migrar os dados

```bash
python scripts/migrar_sqlite_para_sqlserver.py --conferir   # compara as contagens
python scripts/migrar_sqlite_para_sqlserver.py --migrar
```

Idempotente: registro já presente no destino é pulado pelo `id`. **O SQLite não é
apagado** — fica como estava, e é o que permite conferir ou voltar atrás enquanto a
confiança no destino não estiver formada.

Migração feita em 18/08/2026: 6 casos, 20 entregas, 3 entrevistas e 4 vínculos.

## O que ainda aponta para o lugar antigo

Os quatro `vinculos_agente` migrados referenciam casos que o agente tinha no **PostgreSQL
local**, não no SQL Server. Abrir o dossiê de um deles mostra o caso do Acervo
normalmente, mas a parte do agente vem vazia — os ids não existem mais do outro lado.

Não é defeito da migração: é consequência de os dois sistemas terem virado de banco em
momentos diferentes. Casos novos nascem ligados corretamente. Para os quatro antigos, o
caminho é ressincronizar pelo botão de enviar ao agente, que cria o caso do outro lado e
regrava o vínculo.

## Voltar para o SQLite

Se for preciso, o caminho é trocar o import em `armazenamento.py`:

```python
from .banco import conectar      # SQL Server
```

O arquivo `dados/casos.db` continua íntegro, com os dados até a data da virada.


## A faxina de 18/08/2026

Por um tempo o Acervo teve schema próprio (`ocr`), e o banco chegou a ter cinco schemas —
três deles (`agente`, `core`, `adm`) eram sobra de um redesenho de domínio que foi
discutido e não seguido, com 20 tabelas sem uma linha de dado.

Tudo foi consolidado em `dbo`:

- as 5 tabelas do Acervo mudaram de schema com `ALTER SCHEMA TRANSFER`, levando os dados
  junto, e ganharam o prefixo `acervo_`;
- os schemas `ocr`, `agente`, `core` e `adm` foram removidos, com 20 tabelas vazias, 1
  procedure e 1 view;
- o conteúdo de `adm.schema_versao` — a única coisa com dado em tudo que saiu — está
  guardado em `../../ia-juridica/migrations/sqlserver/HISTORICO-schema_versao.json`.

O banco passou de 5 schemas e 50 tabelas para **1 schema e 32 tabelas**. As constraints
criadas antes mantêm o nome `pk_ocr_*` / `fk_ocr_*`: renomeá-las exigiria `sp_rename` em
cada uma, sem mudar comportamento nenhum.
