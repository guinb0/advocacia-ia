# Glossário de tipos de documento, reclassificação e duplicidade

Este documento cobre três coisas que trabalham juntas:

- o **glossário**, que é a lista única de tipos de documento;
- a **reclassificação**, que é a palavra final de uma pessoa sobre o item e o tipo de um documento;
- a **verificação de duplicidade**, feita antes de o documento contar no checklist.

Código: `app/tipos_documento.py`, `app/duplicidade.py`, `app/historico_alteracoes.py`.
Tela: **Escritório → Glossário de documentos** e o painel **Corrigir classificação** do checklist.

## Por que o glossário existe

Antes, "tipo de documento" ficava espalhado em três lugares que não se falavam:

- os 9 tipos do classificador de OCR (`extractors.ROTULOS_TIPO`);
- os nomes dos itens de cada checklist;
- o que a correção manual gravava.

A correção gravava `item.tipo_ocr or item.codigo`. Por isso uma CAT virava "DOC.10" no acidente de
trabalho geral e "DOC.09" na doença ocupacional. E o mesmo "DOC.13" queria dizer atestado numa
categoria e extrato do FGTS em outra. A memória de correções que orienta o modelo aprendia com esse
ruído.

Agora:

- cada tipo tem um **código estável** (`cat`, `laudo_medico`, `contracheque`…);
- todo item de checklist aponta para um tipo (`ItemChecklist.tipo_documento`);
- a reclassificação grava o código do glossário.

O teste `tests/test_tipos_documento.py` falha se algum item ficar sem tipo.

A semente tem **43 tipos**:

- os 9 do classificador, com o **mesmo código** que ele grava em `tipo_detectado`;
- 34 tipos tirados dos checklists do escritório.

A semente só *insere* o que falta. Nome e sinônimos editados pelo escritório nunca são sobrescritos
quando o servidor sobe.

## Quem mantém

| Ação | Quem |
|---|---|
| Consultar o glossário (`GET /api/tipos-documento`) | Toda a equipe interna — a reclassificação precisa da lista |
| Criar, editar, desativar e reativar | Perfis com o módulo **`glossario_documentos`** |

O sistema não tem perfil "gestor" nem "admin" fixo no código: o acesso é decidido por módulo, na
matriz de perfis. De fábrica, o módulo vai para os perfis que já administram o escritório:

- **Advogado**, que é o perfil da conta administradora inicial;
- **Secretário**, que gerencia os usuários.

Para ter um perfil "Gestor", crie-o em **Usuários → Perfis** e marque "Glossário de documentos".

Em instalações que já existem, o módulo chega sozinho a esses dois perfis na próxima subida
(`perfis._entregar_modulos_ineditos`). Os demais perfis nascem com o módulo negado.

## Impacto de alterar um tipo já usado

| Campo | Pode mudar? | O que acontece |
|---|---|---|
| `codigo` | **Não** | É o que fica gravado em cada documento classificado e em cada correção. Não existe rota que o altere. |
| `nome`, `descricao` | Sim | O documento guarda o código, então o nome novo aparece em todo lugar que consulta o glossário. O registro de cada leitura (`extracao_json`) continua com o nome da época, como histórico. |
| `sinonimos` | Sim | Entram na leitura automática dos **próximos** documentos: `roteamento._semantico` manda ao modelo o nome do item com o tipo e os sinônimos. Não reclassificam o que já foi lido. |
| `categorias` (tipos de caso) | Sim | Decide em que checklists, além do fixo do escritório, o tipo é pedido. Ver [Em que tipos de caso o documento é pedido](#em-que-tipos-de-caso-o-documento-é-pedido). Desmarcar um tipo de caso com documento já entregue nesse item é **bloqueado** (409). |
| `ativo` | Com restrições | Desativar tira o tipo das opções de classificação, e os documentos que já o usam continuam como estão. **Bloqueado** (409) para tipo pedido por item de checklist (inclusive o acrescentado por tipo de caso marcado) e para tipo de sistema. |
| apagar | **Não existe** | Apagar levaria junto o significado dos documentos que usam o tipo. |

Antes de salvar, a tela mostra o impacto, que vem de `GET /api/tipos-documento/{codigo}/impacto`:

- quantos documentos e casos usam o tipo;
- quantas correções o citam;
- quais itens de checklist o pedem;
- o efeito de cada alteração.

Renomear um tipo em uso e desativar pedem confirmação.

A edição é **otimista por versão**. O formulário devolve a `versao` que leu; se outra pessoa salvou
antes, a resposta é 409 e nada é sobrescrito.

## Em que tipos de caso o documento é pedido

Os checklists de `app/categorias.py` são os do escritório, conferidos contra os `.docx`. Um tipo criado
no glossário não estava em nenhum deles e, por isso, não aparecia em caso nenhum. O formulário do
glossário tem uma tabela com os tipos de caso do sistema, e quem cria ou edita o tipo marca aqueles em
que ele deve ser pedido.

- A marcação fica em `dbo.acervo_tipos_documento_categorias`, com uma linha por par (tipo, categoria).
  A tabela é criada na subida, em `tipos_documento.inicializar`.
- `categorias.obter()` e `categorias.listar()` acrescentam ao fim do checklist um item para cada tipo
  **ativo** marcado. `categorias.CATEGORIAS` continua só com o checklist fixo.
- O item acrescentado:
  - tem código `GLOS.<codigo do tipo>`, derivado do código imutável para que a entrega não troque de
    item;
  - é **opcional**, porque marcar um tipo de caso não pode deixar incompletos casos que estavam completos;
  - vale para todos os casos da categoria, **inclusive os já abertos**.
- Tipo que o checklist fixo da categoria já pede não ganha um segundo item. A tela mostra essa linha
  marcada e travada.
- Desmarcar um tipo de caso em que já há documento entregue no item é recusado (409): o documento
  ficaria preso a um item que a tela não mostra mais. Reclassifique-o antes.
- A marcação entra no histórico do tipo (`categorias` em `antes` e `depois`).
- Os processos guardam as marcações em cache por até 30 s. O processo que salvou limpa o dele na hora;
  o worker de OCR vê a mudança em até 30 s.

## A regra de duplicidade

Dois documentos só são comparados se forem do **mesmo caso**. Há três níveis, do certo ao provável:

| Regra | Quando casa | Onde é verificada | Efeito |
|---|---|---|---|
| **Idêntico** | Mesmo SHA-256 do arquivo (`entregas.conteudo_sha256`) | No envio, **antes** de gravar | Envio recusado com 409 e nada gravado. A equipe pode insistir com `confirmar_duplicidade`, e a confirmação vai ao histórico. O portal do cliente não tem essa opção. |
| **Mesmo número** | Mesmo tipo cadastral reconhecido pelo classificador **e** mesmo número válido de CPF, RG, registro da CNH, título ou Cartão SUS | Depois do OCR, antes de contar no checklist | O documento fica **na triagem** com o motivo (`roteamento_origem = "duplicidade"`) |
| **Mesmo conteúdo** | Mesmo tipo no glossário **e** ≥ 90% dos trigramas de palavras em comum, com pelo menos 30 palavras em cada | Depois do OCR, antes de contar no checklist | Igual ao anterior |

Na **reclassificação** as três regras rodam antes de gravar. Havendo suspeita, a resposta é 409 com a
lista, e só a confirmação conclui a operação.

### O que não conta como duplicidade, de propósito

- **Documento de outro caso.** O mesmo PCMSO serve a dois clientes da mesma empresa. Além disso,
  procurar fora do caso contaria a quem envia pelo portal que outro cliente mandou aquele papel.
- **Mesmo tipo e nada mais.** Dois atestados são dois atestados.
  - Contracheques de meses diferentes dividem quase todo o cabeçalho.
  - A comparação por **trigramas** existe por isso: cada valor que muda derruba os três trigramas em
    volta dele.
  - O teste mede dois meses distintos bem abaixo do limiar.
- **RG e CNH da mesma pessoa.** Os dois trazem o mesmo número de RG, mas são documentos diferentes. A
  regra do número exige o mesmo tipo reconhecido.

### O que a regra não pega

Duas fotos de um laudo manuscrito ou mal digitalizado, que o OCR lê de jeitos diferentes, podem passar.
Baixar o limiar para alcançá-las faria o sistema acusar atestados do mesmo médico, que são documentos
distintos.

A regra também não impede dois envios idênticos feitos **no mesmo instante**: a checagem e a gravação
não são atômicas. O envio em lote é sequencial, então o arquivo repetido *dentro* de um lote é
recusado.

## Rastreabilidade

Toda alteração relevante vai para `dbo.acervo_historico_alteracoes`, **na mesma transação** da
alteração: ou ficam as duas, ou nenhuma. Cada linha guarda quem fez, quando, o estado anterior, o novo
estado e o motivo, quando informado.

A tabela não tem chave estrangeira. Por isso o rastro de um documento removido sobrevive à remoção.

| Entidade | Ações |
|---|---|
| `tipo_documento` | `criado`, `editado`, `desativado`, `reativado` |
| `entrega` | `reclassificada` (com `duplicidades_confirmadas` quando houve), `devolvida_triagem`, `duplicidade_confirmada` (repetido aceito no envio), `removida` |

Os eventos são consultados em `GET /api/tipos-documento/{codigo}/historico` e
`GET /api/entregas/{id}/historico`. Na tela, aparecem no botão **Histórico** do glossário e no painel
de correção do documento.

A tabela `classificacoes_documentos_corrigidas` continua existindo como **memória de aprendizado** do
classificador. Ela é agregada e alimenta o prompt, e passa a receber o código do glossário em
`tipo_correto`.

## API

| Método e rota | Corpo | Observação |
|---|---|---|
| `GET /api/tipos-documento?incluir_inativos=` | — | Livre para a equipe |
| `GET /api/tipos-documento/{codigo}` | — | |
| `GET /api/tipos-documento/{codigo}/impacto` | — | |
| `GET /api/tipos-documento/{codigo}/historico` | — | |
| `POST /api/tipos-documento` | `nome`, `codigo?`, `descricao`, `sinonimos[]`, `categorias[]` | Módulo `glossario_documentos`. Sem código, ele é gerado do nome. |
| `PUT /api/tipos-documento/{codigo}` | `nome`, `descricao`, `sinonimos[]`, `ativo`, `versao`, `motivo`, `categorias[]?` | Módulo `glossario_documentos`. Versão diferente da atual = 409. Sem `categorias`, mantém as marcadas. |
| `POST /api/casos/{id}/documentos` | + `confirmar_duplicidade` (form) | Idêntico sem confirmação = 409 |
| `PATCH /api/entregas/{id}/itens` | `itens[]`, `tipo?`, `confirmar_duplicidade`, `motivo` | Lista vazia devolve à triagem |
| `GET /api/entregas/{id}/historico` | — | |
| `DELETE /api/entregas/{id}` | — | Registra `removida` |

O 409 de duplicidade tem esta forma:

```json
{
  "detail": "Este arquivo já está no caso: “rg.pdf”, enviado em 10/09/2026. Nada foi gravado.",
  "codigo": "DOCUMENTO_DUPLICADO",
  "duplicidades": [
    {"entrega_id": "…", "arquivo": "rg.pdf", "regra": "identico",
     "explicacao": "arquivo idêntico", "itens": ["DOC.03"], "criado_em": "…"}
  ]
}
```

`detail` continua sendo texto. O portal e o envio em lote só mostram a frase; a tela da equipe lê
`codigo` e `duplicidades` para oferecer a confirmação.

## Testes

```powershell
.venv\Scripts\python.exe -m pytest tests/test_tipos_documento.py tests/test_duplicidade.py -q
.venv\Scripts\python.exe -m tests.cenario_glossario_duplicidade
```

O primeiro comando testa as regras sem banco.

O segundo roda o cenário de aceite **contra o SQL Server do `.env`**. Os passos são:

1. cria um tipo;
2. classifica um documento;
3. reclassifica esse documento;
4. tenta adicionar duplicados;
5. apaga tudo o que criou.

O OCR e o modelo de linguagem são simulados no cenário.
