"""Acervo Jurídico: legislação e jurisprudência oficiais, versionadas por dispositivo.

- `encoding`: bytes da fonte oficial → texto, sem nunca mascarar corrupção.
- `parser`: texto → árvore de dispositivos (artigo, parágrafo, inciso, alínea) com ids estáveis.
- `sincronizacao`: busca → normaliza → hash → diff → versão → embedding só do que mudou → status.
- `armazenamento`: o mesmo contrato sobre o PostgreSQL do RAG e sobre memória (testes e uso local).
- `consulta`: leitura para o painel administrativo.

Nada aqui altera skill, peça ou caso: o acervo só é lido pela geração (`juridico.repositorio`).
"""
