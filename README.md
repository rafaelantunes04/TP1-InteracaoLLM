# From Raw Detections to Real Intelligence

**Interação com Modelos de Larga Escala — Trabalho Prático #1**  
Rafael Antunes · Nº 55336

Pipeline que transforma eventos brutos de visão computacional em inteligência operacional para gestão de lojas de retalho. A partir de um stream de eventos anónimos, reconstrói trajetórias de clientes e gera um relatório semanal automático em linguagem natural.

---

## Modelo LLM utilizado

**`llama3.2:3b`** via Ollama (temperatura 0, seed 42 para reprodutibilidade)

---

## Estrutura do Repositório

```
tp1/
├── README.md
├── requirements.txt
├── data/
│   ├── events.csv          ← dataset de eventos (não incluído no repo)
│   └── zones.json          ← mapa da loja com zonas e tempos de caminhada
├── src/
│   ├── stitcher.py         ← Fase 1: reconstrução de trajetórias
│   ├── analytics.py        ← Fase 2a: cálculo de métricas
│   ├── insights.py         ← Fase 2b: geração de insights com LLM
│   ├── report.py           ← Fase 2c: relatório semanal em Markdown
│   ├── visualizador.py     ← ferramenta de visualização interativa (opcional)
│   └── etc/
│       ├── matriztempos.py ← matriz de tempos entre zonas (Dijkstra)
│       ├── pessoa.py       ← estrutura de dados por pessoa
│       └── insights_helper.py ← filtros de métricas e schema de output
├── prompts/
│   ├── instrucoes.txt
│   ├── regras.txt
│   ├── report_instrucoes.txt
│   └── exemplos_*.txt      ← exemplos few-shot por categoria (estratégia B)
├── output/
│   ├── journeys.csv
│   ├── metrics.json
│   ├── insights.json
│   └── weekly_report.md
└── evaluate.py             ← harness de avaliação ponta-a-ponta
```

---

## Instalação

### 1. Clonar o repositório e instalar dependências Python

```bash
git clone <url-do-repositorio>
cd tp1
pip install -r requirements.txt
```

### 2. Instalar o Ollama e descarregar o modelo

```bash
# Instalar Ollama: https://ollama.com/download
ollama pull llama3.2:3b
```

---

## Execução do Pipeline Completo

Os módulos são executados em sequência, cada um recebendo o output do anterior.

```bash
# Fase 1 — Reconstrução de trajetórias
python src/stitcher.py --input data/events.csv --output output/journeys.csv

# Fase 2a — Cálculo de métricas
python src/analytics.py --input output/journeys.csv --output output/metrics.json

# Fase 2b — Geração de insights (estratégia B por omissão)
python src/insights.py --input output/metrics.json --output output/insights.json

# Fase 2c — Relatório semanal
python src/report.py --input output/insights.json --output output/weekly_report.md
```

### Opções adicionais do `insights.py`

```bash
# Estratégia A (zero-shot)
python src/insights.py --input output/metrics.json --output output/insights.json --strategy A

# Comparação quantitativa A vs. B
python src/insights.py --input output/metrics.json --output output/insights.json --compare
```

---

## Harness de Avaliação

Executa o pipeline completo sobre um dataset de validação com anomalias injetadas e produz um relatório de métricas.

```bash
python evaluate.py --data events_validation.csv --output evaluation_report.json
```

Com ground-truth de anomalias conhecidas:

```bash
python evaluate.py --data events_validation.csv --output evaluation_report.json --ground-truth anomalias.json
```

**Métricas calculadas:**
- **Consistência** — % de trajetórias sem sobreposição temporal (esperado: 100%)
- **Cobertura** — % de eventos associados a alguma trajetória
- **Completude** — % de trajetórias com entrada e saída em Z\_E ou Z\_CK
- **Deteção de anomalias** — % das anomalias injetadas identificadas nos insights
- **Precisão numérica** — % de valores numéricos nos insights verificáveis no `metrics.json`
- **Ausência de alucinação** — % de afirmações factuais verificáveis no `metrics.json`

---

## Visualizador Interativo (Opcional)

Ferramenta gráfica para inspecionar o algoritmo de stitching evento a evento.

```bash
python src/visualizador.py
```

> Requer `tkinter` e `matplotlib`. Antes de executar, editar os caminhos absolutos para `zones.json` e `events.csv` no topo do ficheiro `visualizador.py`.

---

## Notas Técnicas

- O stitcher usa o algoritmo de **Dijkstra** para pré-calcular a matriz de tempos entre zonas, reduzindo o custo de cada consulta a O(1).
- A complexidade do stitching é **O(N·P)**, onde N é o número de eventos e P o número de pessoas ativas.
- Todos os componentes com aleatoriedade usam `seed=42` e `temperature=0` para garantir reprodutibilidade.
- O LLM nunca acede diretamente ao CSV — recebe apenas o `metrics.json` pré-calculado em Python.
