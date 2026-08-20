# Benchmark e configuração do OCR

Este benchmark impede que uma otimização rápida seja adotada quando ela perde
campos. Cada perfil sobe o PaddleOCR em um processo isolado e mede quatro
documentos sintéticos com gabarito (CNH, CTPS, CPF e título).

Execute na raiz de `ocr-extrator`:

```powershell
.venv\Scripts\python.exe scripts\benchmark_ocr.py
```

O relatório detalhado fica em `tmp/benchmark-ocr.json` (diretório ignorado pelo
Git). O teste realizado em 20/08/2026, nesta máquina, produziu:

| Perfil | Tempo total | Campos exatos | Confiança média | Decisão |
|---|---:|---:|---:|---|
| base | 112,5 s | 24/24 | 0,9958 | referência |
| detector limitado a 1280 | 62,3 s | 24/24 | 0,9958 | melhor candidato |
| 16 threads | 75,9 s | 24/24 | 0,9958 | ganho, mas inferior a 1280 |
| sem MKL-DNN | 174,3 s | 24/24 | 0,9958 | descartado |
| sem orientação | 210,5 s | 24/24 | 0,9958 | descartado |
| detector mobile | 444,6 s | 21/24 | 0,9880 | descartado |
| recorte de perspectiva | 210,6 s | 24/24 | 0,9958 | disponível, desligado por padrão |

## Decisões

- O modelo continua persistente e aquecido no processo; não é recriado por arquivo.
- MKL-DNN, orientação da página e orientação das linhas continuam ligados.
- O detector `server` continua sendo usado. O modelo mobile foi mais lento e perdeu
  três valores, portanto não é alternativa nesta instalação.
- O limite do detector em 1280 é configurável por `OCR_DET_LADO_MAXIMO` e só deve
  ser promovido para todos os ambientes após passar também no acervo real.
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
