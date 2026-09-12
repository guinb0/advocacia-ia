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

### `acervo_perfil_alteracoes`

Trilha do que o gestor muda nos perfis. Uma linha por alteração aceita:

- `perfil_codigo`
- `acao` — `criado`, `atualizado` ou `removido`
- `autor` — o e-mail da conta que alterou (o login do escritório). Alteração
  feita sem sessão — a inicialização, por exemplo — grava `desconhecido`, e com
  a autenticação desligada grava `sessão sem autenticação`
- `resumo` — o que mudou, em uma linha, com os **códigos** dos módulos (o rótulo
  é editável e o registro precisa continuar significando a mesma coisa depois)
- `antes` / `depois` — o estado completo do perfil em JSON
- `criado_em`

Duas decisões que valem registro:

1. **Salvar sem mudar nada não gera linha.** Abrir a tela, clicar e desistir é
   comum; uma trilha cheia desses registros esconde a alteração de verdade.
2. **A gravação acontece na mesma transação da alteração.** Uma trilha escrita à
   parte sobreviveria a uma alteração desfeita por erro, e passaria a afirmar uma
   mudança que não aconteceu.

Quando a alteração RETIRA módulo de um perfil em uso, o resumo termina com
quantas contas usavam aquele perfil naquele momento — a auditoria precisa do
tamanho do impacto sem ter de reconstruir depois quem usava o quê.

## Quem altera, e por onde

A matriz é editada em **Usuários → Perfis de acesso**
(`frontend/src/components/PerfisDeAcesso.tsx`, montada dentro da tela de
usuários). A tela mostra, por perfil: os módulos marcados, quantas contas
dependem dele e um aviso antes de salvar quando a alteração tira acesso de
contas ativas.

As rotas de gestão exigem o módulo `usuarios` (`auth.exigir_modulo`), o que
inclui:

- `GET /api/usuarios/modulos` — catálogo de módulos
- `GET /api/usuarios/perfis/matriz` — perfis, módulos e contagem de contas
- `GET /api/usuarios/perfis/historico` — a trilha
- `PUT /api/usuarios/perfis/{codigo}` — cria ou atualiza
- `DELETE /api/usuarios/perfis/{codigo}` — apaga

`GET /api/usuarios/perfis` continua **sem** exigência de módulo (a sessão, porém,
segue exigida pelo middleware — `LIVRES_SEM_ADVOGADO` dispensa o papel de advogado,
não a autenticação): é o vocabulário
que alimenta o seletor do cadastro e não diz o que cada perfil alcança.

O que é mutável pela tela: `rotulo`, `descricao` e os módulos. O `codigo` não —
ele viaja no claim `perfil` do token e é comparado como texto exato, então mudá-lo
invalidaria as sessões abertas. Perfil de sistema não é apagável, e perfil com
conta vinculada também não (o servidor recusa, e a tela não oferece o botão).

## Edição de contas: só o secretário

`PUT /api/usuarios/{codigo}` altera nome, e-mail (o login), telefone, perfil, situação e
senha de uma conta existente. `DELETE /api/usuarios/{codigo}` (desativar) segue a mesma
regra. As duas exigem o **papel** `secretario` (`auth.exigir_papel`), e não um módulo —
módulo se concede pela matriz, e o advogado, que também administra a matriz, poderia se
dar esse poder com um clique. Cadastrar conta nova continua com o módulo `usuarios`.

- O secretário não muda o próprio perfil nem desativa a própria conta.
- Senha vazia mantém a atual; `redefinirSenha` volta para a senha padrão e obriga a troca.
- Perfil trocado e conta desativada valem na hora (a autorização lê o banco a cada
  requisição). E-mail trocado derruba a sessão aberta da pessoa. **Senha trocada não
  derruba sessão aberta** — o token vale até 24 h; para cortar acesso agora, desative.
- `telefone` é opcional e guardado só com dígitos (10 a 13).

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
