# Matriz de fontes jurisprudenciais

Levantamento inicial em 25/09/2026. A matriz é deliberadamente conservadora:
portal acessível não equivale a API pública nem autoriza scraping. Todos os
providers começam em `MANUAL_ONLY` até homologação técnica por tribunal.

| Tribunal | Fonte oficial | API/endpoint público homologado | Pesquisa web | Dados anunciados | Automação | Limitação | Provider |
|---|---|---|---|---|---|---|---|
| TRT-1 | https://www.trt1.jus.br/ | Não identificado | Portal | A confirmar | Não | Fluxo/endpoints não homologados | Manual |
| TRT-2 | https://ww2.trt2.jus.br/ | Não identificado | Portal | Pesquisa jurisprudencial | Não | Interface web; API não documentada | Manual |
| TRT-3 | https://portal.trt3.jus.br/ | Não identificado | Portal | Acórdãos em inteiro teor | Não | Interface web; API não documentada | Manual |
| TRT-4 | https://www.trt4.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-5 | https://www.trt5.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-6 | https://www.trt6.jus.br/ | Não identificado | Portal | Texto, processo, relator, órgão e data | Não | Consulta de acórdãos apresenta CAPTCHA | Manual |
| TRT-7 | https://www.trt7.jus.br/ | Não identificado | Portal/Falcão | Acórdãos e publicações | Não | API não documentada | Manual |
| TRT-8 | https://www.trt8.jus.br/ | Não identificado | Portal/Falcão | Acórdãos e precedentes qualificados | Não | API não documentada | Manual |
| TRT-9 | https://www.trt9.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-10 | https://www.trt10.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-11 | https://portal.trt11.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-12 | https://portal.trt12.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-13 | https://www.trt13.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-14 | https://portal.trt14.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-15 | https://www.trt15.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-16 | https://www.trt16.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-17 | https://www.trt17.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-18 | https://www.trt18.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-19 | https://site.trt19.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-20 | https://www.trt20.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-21 | https://www.trt21.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-22 | https://www.trt22.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TRT-23 | https://www.trt23.jus.br/ | Não identificado | Portal/Falcão | A confirmar | Não | Portal redireciona; endpoint não homologado | Manual |
| TRT-24 | https://www.trt24.jus.br/ | Não identificado | Portal | A confirmar | Não | Endpoint não homologado | Manual |
| TST | https://jurisprudencia.tst.jus.br/ | Não identificado | Consulta unificada | Processo, relator, órgão, ementa e inteiro teor | Não | API não documentada | Manual |
| STF | https://jurisprudencia.stf.jus.br/ | Não identificado | Portal | A confirmar | Não | Fora da prioridade trabalhista normal | Manual |
| STJ | https://jurisprudencia.stj.jus.br/ | Não identificado | Portal | A confirmar | Não | Fora da prioridade trabalhista normal | Manual |

## Evidências e decisão

- O TRT-6 descreve campos de pesquisa, mas a consulta de acórdãos contém
  verificação de segurança; por política, o sistema não tenta automatizá-la.
- O TRT-3 disponibiliza pesquisa de acórdãos em inteiro teor.
- O TST informa que sua Consulta Unificada pesquisa por texto e por processo,
  relator, órgão julgador, ementa e tipo de processo.
- O Falcão é repositório oficial nacional, porém a documentação pública consultada
  não oferece uma API externa estável para este produto. Ele será candidato a
  provider somente quando houver contrato/endpoint público homologado.

Um provider `AUTOMATED` só pode ser promovido após teste de ponta a ponta que
consulta, abre a decisão original, extrai os campos sem inferência, persiste o
hash e marca `VERIFIED`. Até lá, uma busca manual pode registrar o link para a
etapa de validação, mas não alimentar automaticamente uma petição.
