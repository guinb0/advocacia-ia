# Legislação no RAG

A coleção `lei` é separada da jurisprudência e usa texto consolidado da fonte
oficial, com URL, hash SHA-256, escopo, área e instante de coleta em cada chunk.
O modelo DeepSeek deve responder a partir desses trechos recuperados e citar a
fonte; o conhecimento interno dele nunca substitui verificação de vigência.

## Primeira carga federal

Com `DATABASE_URL` e as variáveis de embeddings configuradas no `.env`:

```powershell
.venv\Scripts\python.exe -m scripts.ingerir_legislacao_federal --coletar
.venv\Scripts\python.exe -m scripts.vetorizar_legislacao_pendente
```

Para piloto, acrescente `--limite 1`. Se a importação deve gerar vetores na
mesma execução, use `--com-embeddings` no primeiro comando.

O manifesto começa pelos diplomas federais estruturantes e é reexecutável: uma
fonte cujo SHA-256 não mudou não é regravada. A atualização deve ser agendada;
o coletor baixa novamente apenas com `--coletar`.

## Cobertura e limites

"Legislação brasileira" inclui normas federais, estaduais, distritais e
municipais, além de regulamentos e atos de agências. O primeiro lote é federal
e não afirma cobertura total. Cada novo coletor deve usar fonte oficial do ente,
preencher `escopo`, `origem`, `sha256`, `coletado_em` e situação/vigência, e não
misturar projeto de lei com norma promulgada.

As fontes federais escolhidas são páginas consolidadas do Planalto. Para escala
nacional, o catálogo LexML/Senado deve servir para descoberta e o texto deve ser
confirmado na fonte oficial indicada, pois metadados de pesquisa não garantem a
redação vigente.
