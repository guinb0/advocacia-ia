# Estrutura do projeto

O repositório tem três pastas de trabalho e uma raiz só de infraestrutura.

| Diretório | Responsabilidade |
|---|---|
| `front/` | Interface Next.js |
| `front/src/components/entrevista/` | Entrevista, roteiro, revisão e gravação |
| `front/src/components/documentacao/` | Fila e atendimento da documentação |
| `back/app/` | API FastAPI, workers Celery e regras de negócio |
| `back/app/agente/` | Integração com o agente jurídico e dossiê |
| `back/tests/` | Testes automatizados do backend |
| `back/docs/` | Documentação funcional e operacional |
| `back/scripts/` | Importações, migrações e rotinas administrativas |
| `back/sql/` | Consultas e migrações SQL |
| `back/static/` | Recursos estáticos do backend |
| `back/dados/` | Dados locais e documentos; não versionados |
| `back/tmp/` | Arquivos temporários; não versionados |
| `ia/skills/` | Skills em arquivo (petição trabalhista, análise documental) |
| `ia/*.skill.zip` | Skill jurídica embutida, instalada pela API ao subir |
| `ia/sincronizar-rag.ps1` | Ingestão e vetorização do RAG |
| raiz | `iniciar.ps1`/`.sh`, `.env`, Dockerfile, docker-compose, CI, `observability/`, `deploy/` |

## Convenções

- Backend novo fica em `back/app/`, separado por domínio. Todo Python mora em
  `back/` — inclusive o que chama a IA, porque a API a chama no mesmo processo.
- O que ensina a IA (skill, instrução, modelo de peça) fica em `ia/`. O código
  acha as skills por `app/caminhos.py`, nunca por caminho montado à mão.
- Interface fica em `front/src/`; não recriar as pastas legadas
  `front/components`, `front/lib` ou `front/app`.
- Comandos Python rodam de dentro de `back/` (`python -m tests.x`,
  `python -m scripts.x`); o `iniciar.ps1` roda da raiz com `PYTHONPATH=back`.
- Arquivos gerados, logs e estados de workers nunca ficam na raiz nem entram no Git.
- Segredos ficam somente no `.env` da raiz; `NEXT_PUBLIC_` nunca recebe chaves privadas.
- Documentos de arquitetura e operação ficam em `back/docs/`.

A imagem Docker não segue esta divisão: o Dockerfile remonta o layout antigo sob
`/app` (`app/`, `app/skills/`, `frontend/`...), e por isso os composes e os nomes
das tasks do Celery não mudaram.
