# Benchmark e configuração do OCR

Este benchmark impede que uma otimização rápida seja adotada quando ela perde
campos. Cada perfil sobe o PaddleOCR em um processo isolado e mede quatro
documentos sintéticos com gabarito (CNH, CTPS, CPF e título).

Execute na raiz do repositório:

```powershell
.venv\Scripts\python.exe scripts\benchmark_ocr.py
```

O relatório detalhado fica em `tmp/benchmark-ocr.json` (diretório ignorado pelo
Git). O teste realizado em 20/08/2026, nesta máquina, produziu:

| Perfil | Tempo total | Campos exatos | Confiança média | Decisão |
|---|---:|---:|---:|---|
| base | 112,5 s | 24/24 | 0,9958 | referência |
| detector limitado a 1280 | 62,3 s | 24/24 | 0,9958 | configuração adotada |
| 16 threads | 75,9 s | 24/24 | 0,9958 | ganho, mas inferior a 1280 |
| sem MKL-DNN | 174,3 s | 24/24 | 0,9958 | descartado |
| sem orientação | 210,5 s | 24/24 | 0,9958 | descartado |
| detector + reconhecedor mobile | 66,9 s | 24/24 | 0,9980 | inferior ao perfil adotado |
| recorte de perspectiva | 210,6 s | 24/24 | 0,9958 | disponível, desligado por padrão |

## Decisões

- O modelo continua persistente e aquecido no processo; não é recriado por arquivo.
- MKL-DNN, orientação da página e orientação das linhas continuam ligados.
- O detector `server` continua sendo usado. A combinação mobile correta manteve
  24/24 campos, mas foi mais lenta que o server limitado a 1280. Configurar apenas
  o detector mobile fazia o Paddle selecionar um reconhecedor server implicitamente
  e não constitui uma comparação válida.
- O limite do detector em 1280 foi adotado como padrão por
  `OCR_DET_LADO_MAXIMO`. Defina a variável vazia para comparar um documento
  excepcional em resolução integral.
- O recorte de perspectiva por OpenCV existe atrás de `OCR_CROPS_DOCUMENTO=1`.
  Ele é conservador e opt-in porque uma borda interna confundida com o documento
  pode apagar conteúdo.
- Os jobs da checklist não gravam JSON/XML temporários redundantes. O original e
  a extração já ficam persistidos no banco. O fluxo genérico ainda pode gerar os
  arquivos quando solicitado.
- A extração de campos permanece determinística (validadores e expressões
  regulares); não foi acrescentada chamada de LLM ao OCR.

As variáveis e seus valores documentados ficam em `.env.example`. Para testar uma
combinação nova, acrescente um perfil em `scripts/benchmark_ocr.py`; não altere a
configuração de produção somente com base no tempo.

## Validação no JPG real do acervo

No comprovante Neoenergia `DOC.05_7e5fc012...jpg`, o perfil geral levou 73,2 s.
Limitar a região do comprovante aos 55% superiores reduziu para 39,0 s, mantendo
nome, data de emissão e CEP. O vencimento da conta deixou de ser publicado
indevidamente como `data_validade`. Um recorte de 65% levou 55,3 s e perdeu o CEP;
por isso o padrão específico de `comprovante_residencia` é 0,55. O arquivo original
continua preservado e usado na avaliação de qualidade; somente a entrada do OCR é
recortada. Outros tipos documentais não recebem esse recorte.

O teste reproduzível para um arquivo real é:

```powershell
.venv\Scripts\python.exe scripts\benchmark_ocr_arquivo.py CAMINHO_DO_JPG
```
