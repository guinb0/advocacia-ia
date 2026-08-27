# Migração de permissões por módulo

## Objetivo

O Acervo passou a ter um fluxo novo de permissões compatível com o padrão de
módulos e perfis usado nos demais projetos da Level. A mudança é incremental:
nenhuma tabela antiga foi removida, porque versões anteriores ainda podem
depender delas.

## Tabelas novas

### `acervo_tb_perfis`

Perfis disponíveis no cadastro de usuários.

Campos principais:

- `id`
- `nome`
- `rotulo`
- `descricao`
- `sistema`
- `ativo`
- `criado_em`

Observação: a tabela nova não tem coluna `codigo`. O campo `nome` guarda o nome
estável do perfil, como `advogado`, `secretario`, `documentacao` e `cliente`.

### `acervo_tb_modulos_web`

Catálogo dos módulos web.

Campos principais:

- `id`
- `nome_modulo`
- `rotulo`
- `descricao`
- `rota`
- `grupo`
- `ordem`
- `ativo`

Observação: a tabela nova não tem coluna `codigo`. O campo `nome_modulo` guarda
o nome estável do módulo.

A navegação usa `ordem` para montar a barra lateral. O backend entrega os
módulos autorizados do perfil já nessa sequência, e o frontend exibe as telas
ligadas a esses módulos. A coluna `rota` fica no catálogo como metadado da rota
principal do módulo.

### `acervo_tb_permissoes`

Matriz relacional perfil x módulo.

Formato:

```text
id | modulo | perfil | hasPermissao
1  |   1    |   1    | s
```

Onde:

- `modulo` referencia `acervo_tb_modulos_web.id`
- `perfil` referencia `acervo_tb_perfis.id`
- `hasPermissao` usa `s` ou `n`

## Compatibilidade

As tabelas antigas continuam existindo:

- `acervo_perfis`
- `acervo_perfil_modulos`

O código atual mantém o fluxo antigo quando um perfil é salvo pela tela, mas a
leitura de acesso das versões novas usa `acervo_tb_permissoes.hasPermissao`.
Durante a inicialização, a migração a partir do legado só preenche permissões que
ainda não existem; ela não sobrescreve alterações feitas no fluxo novo.
O catálogo em código funciona apenas como semente: módulo ou perfil já existente
na tabela nova não é reativado automaticamente, e a coluna `ativo` do banco é
respeitada nas leituras.

O login, os cookies de sessão e o frontend continuam recebendo os nomes textuais
dos perfis e módulos para não quebrar contratos já usados.

O frontend não persiste permissões de módulo em cookie. O cookie guarda apenas
dados de identidade para evitar piscada visual; a navbar só usa os módulos
retornados pelo `my-account`, que consulta `acervo_tb_modulos_web.ativo = 1`,
`acervo_tb_perfis.ativo = 1` e `acervo_tb_permissoes.hasPermissao = 's'`.

## Usuários

A tabela `acervo_usuarios` mantém a coluna antiga `perfil` em texto para versões
anteriores do projeto, mas as versões novas também preenchem `perfil_id`,
referenciando `acervo_tb_perfis.id`.

Na leitura, o backend prefere `perfil_id` e usa `perfil` apenas como fallback de
compatibilidade. O cadastro atual envia `perfilId`, valida a referência contra
um perfil ativo e deriva o texto legado do registro encontrado. Os dois campos
ficam sincronizados: `perfil_id` para o fluxo relacional atual e `perfil` para
versões antigas.

Um gatilho de compatibilidade também resolve `perfil_id` quando uma versão
antiga inserir ou alterar somente a coluna textual `perfil`. A coluna continua
anulável no esquema para que o `INSERT` legado chegue ao gatilho; contas do fluxo
atual nunca são aceitas sem uma referência válida.

O JWT continua identificando a conta, mas nao e fonte de permissao. Cada
autorizacao consulta o perfil atual do usuario e a matriz relacional; alteracoes
de perfil, `ativo` ou `hasPermissao` passam a valer sem esperar o token expirar.
O banco restringe `hasPermissao` aos valores `s` e `n`.

## Migração automática

Na inicialização, o backend:

1. cria as tabelas novas quando ainda não existem;
2. garante os perfis de sistema;
3. cadastra os módulos conhecidos em `acervo_tb_modulos_web`;
4. copia os perfis antigos para `acervo_tb_perfis`;
5. copia para `hasPermissao = 's'` os vínculos legados que ainda não têm linha
   nova;
6. completa a matriz restante em `acervo_tb_permissoes` com `hasPermissao = 'n'`.

## Limpeza futura

Quando não houver mais versões antigas consumindo o fluxo legado, podemos fazer
uma segunda migração para remover a dependência de:

- `acervo_perfis.codigo`
- `acervo_perfil_modulos`
- compatibilidade do campo `codigo` na API

Essa limpeza deve ser feita separadamente, depois de validação em produção.
