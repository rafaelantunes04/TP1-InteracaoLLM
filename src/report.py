import argparse
import json
import os
import time
import ollama

# Configuração
MODELO      = "llama3.2:3b"
TEMPERATURA = 0.0
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts")


# Utilitários
def carregar_prompt(nome_ficheiro: str) -> str:
    """Lê um ficheiro de prompt da pasta prompts/."""
    caminho = os.path.join(PROMPTS_DIR, nome_ficheiro)
    with open(caminho, encoding="utf-8") as f:
        return f.read()


def chamar_ollama(prompt: str, num_predict: int = 600) -> str:
    """Envia o prompt ao Ollama e devolve o texto da resposta."""
    resposta = ollama.generate(
        model=MODELO,
        prompt=prompt,
        options={"temperature": TEMPERATURA, "seed": 42, "num_predict": num_predict},
    )
    return resposta["response"].strip()



# Extracção de insights do JSON
def extrair_dados(caminho_input: str) -> tuple[list, dict]:
    """
    Carrega insights.json e devolve:
      - lista plana de todos os insights
      - dicionário de insights por categoria

    Suporta dois formatos:
      - modo normal  : {"insights": [...], "por_categoria": {...}}
      - modo compare : {"estrategia_B_few_shot": {...}, "estrategia_A_zero_shot": {...}}
    """
    with open(caminho_input, encoding="utf-8") as f:
        dados = json.load(f)

    # Modo compare — usa estratégia B como fonte principal
    if "estrategia_B_few_shot" in dados:
        fonte = dados["estrategia_B_few_shot"]
    else:
        fonte = dados

    todos_insights  = fonte.get("insights", [])
    por_categoria   = {
        cat: conteudo.get("insights", [])
        for cat, conteudo in fonte.get("por_categoria", {}).items()
    }
    return todos_insights, por_categoria



# Formatação de insights para prompt
def _formatar_insights(insights: list) -> str:
    """Converte uma lista de insights em texto estruturado legível pelo LLM."""
    if not insights:
        return "(sem insights disponíveis)"
    linhas = []
    for ins in insights:
        linhas.append(f"[{ins.get('id', '?')}] {ins.get('titulo', '')}")
        linhas.append(f"  Observação:    {ins.get('observacao', '')}")
        linhas.append(f"  Implicação:    {ins.get('implicacao', '')}")
        linhas.append(f"  Recomendação:  {ins.get('recomendacao', '')}")
        linhas.append(f"  Urgência:      {ins.get('urgencia', '')}")
        linhas.append("")
    return "\n".join(linhas)


def _top3_por_urgencia(todos_insights: list) -> list:
    """Selecciona os 3 insights mais prioritários (urgência + confiança)."""
    ordem = {"imediata": 3, "esta_semana": 2, "proximo_mes": 1}
    ordenados = sorted(
        todos_insights,
        key=lambda i: (ordem.get(i.get("urgencia", ""), 0), i.get("confianca", 0.5)),
        reverse=True,
    )
    return ordenados[:3]


# Geração de secções
def _instrucoes_report() -> str:
    return carregar_prompt("report_instrucoes.txt")


def gerar_resumo_executivo(todos_insights: list) -> str:
    """Secção 1 — Resumo executivo (máx. 150 palavras, 3 bullets)."""
    top3 = _top3_por_urgencia(todos_insights)
    instrucoes = _instrucoes_report()

    prompt = f"""{instrucoes}

TAREFA: Resumo Executivo

Com base nos 3 insights mais importantes da semana:

{_formatar_insights(top3)}

Escreve exactamente 3 bullets (cada um começando com "• ").
Máximo 150 palavras no total.
Linguagem directa, números concretos, sem jargão técnico.
Responde APENAS com os 3 bullets, sem introdução nem conclusão."""

    return chamar_ollama(prompt, num_predict=300)


def gerar_secao_trafego(insights: list) -> str:
    """Secção 2 — Performance de tráfego."""
    instrucoes = _instrucoes_report()

    prompt = f"""{instrucoes}

TAREFA: Secção de Performance de Tráfego

INSIGHTS DE TRÁFEGO:
{_formatar_insights(insights)}

Escreve um texto corrido (sem bullets, sem sub-títulos) que cubra:
- afluência total da semana e média diária
- padrões de hora de pico e hora de menor tráfego
- dia mais movimentado e dia menos movimentado

Máximo 150 palavras. Usa números concretos dos insights.
Responde APENAS com o texto da secção."""

    return chamar_ollama(prompt, num_predict=350)


def gerar_secao_zonas(insights: list) -> str:
    """Secção 3 — Análise de zonas."""
    instrucoes = _instrucoes_report()

    prompt = f"""{instrucoes}

TAREFA: Secção de Análise de Zonas

INSIGHTS DE ZONAS:
{_formatar_insights(insights)}

Escreve um texto corrido que cubra:
- zonas com melhor performance (dwell time, taxa de paragem)
- zonas com pior performance ou possíveis zonas mortas
- para cada zona problemática: hipótese de causa e recomendação concreta

Máximo 200 palavras. Usa números concretos dos insights.
Responde APENAS com o texto da secção."""

    return chamar_ollama(prompt, num_predict=400)


def gerar_secao_funil(insights: list) -> str:
    """Secção 4 — Funil de clientes."""
    instrucoes = _instrucoes_report()

    prompt = f"""{instrucoes}

TAREFA: Secção de Funil de Clientes

INSIGHTS DE FUNIL:
{_formatar_insights(insights)}

Escreve um texto corrido que cubra:
- taxa de conversão global (entrada até à caixa)
- onde se perde tráfego ao longo do percurso na loja
- perfil demográfico dos clientes que não chegam à caixa

Máximo 150 palavras. Usa números concretos dos insights.
Responde APENAS com o texto da secção."""

    return chamar_ollama(prompt, num_predict=350)


def gerar_secao_anomalias(insights: list) -> str:
    """Secção 5 — Anomalias da semana."""
    instrucoes = _instrucoes_report()

    prompt = f"""{instrucoes}

TAREFA: Secção de Anomalias da Semana

INSIGHTS DE ANOMALIAS:
{_formatar_insights(insights)}

Para cada anomalia escreve um parágrafo curto com:
- descrição do evento e magnitude do desvio (em σ ou %)
- possível causa
- acção recomendada

Máximo 200 palavras no total. Usa números concretos dos insights.
Responde APENAS com o texto da secção."""

    return chamar_ollama(prompt, num_predict=400)


def gerar_recomendacoes(todos_insights: list) -> str:
    """Secção 6 — Recomendações para a próxima semana (máx. 5, por urgência)."""
    instrucoes = _instrucoes_report()

    # Recolher todas as recomendações com a sua urgência
    recomendacoes = [
        {
            "recomendacao": ins.get("recomendacao", ""),
            "urgencia":     ins.get("urgencia", "proximo_mes"),
            "categoria":    ins.get("categoria", ""),
            "id":           ins.get("id", ""),
        }
        for ins in todos_insights
        if ins.get("recomendacao", "").strip()
    ]

    # Ordenar por urgência e tomar as 5 mais urgentes
    ordem = {"imediata": 3, "esta_semana": 2, "proximo_mes": 1}
    recomendacoes_ordenadas = sorted(
        recomendacoes,
        key=lambda r: ordem.get(r["urgencia"], 0),
        reverse=True,
    )[:5]

    rec_txt = "\n".join(
        f"{i+1}. [{r['urgencia'].upper()}] {r['recomendacao']}"
        for i, r in enumerate(recomendacoes_ordenadas)
    )

    prompt = f"""{instrucoes}

TAREFA: Secção de Recomendações para a Próxima Semana

RECOMENDAÇÕES DISPONÍVEIS (já ordenadas por urgência):
{rec_txt}

Reescreve estas recomendações em formato de lista numerada (máximo 5).
Cada item deve:
- começar com o nível de urgência entre parênteses: (Imediata), (Esta semana) ou (Próximo mês)
- ser específico e executável sem interpretação adicional
- ter no máximo 2 frases

Responde APENAS com a lista numerada, sem introdução nem conclusão."""

    return chamar_ollama(prompt, num_predict=400)


# Montagem do documento Markdown
def montar_report(secoes: dict, metadata: dict) -> str:
    """Monta o documento Markdown final com todas as secções."""
    modelo    = metadata.get("modelo", MODELO)
    estrategia = metadata.get("estrategia", "B")
    duracao   = metadata.get("duracao_s", "—")

    return f"""# Relatório Semanal de Loja

*Gerado automaticamente · Modelo: {modelo} · Estratégia: {estrategia} · Tempo total: {duracao}s*

---

## 1. Resumo Executivo

{secoes['resumo_executivo']}

---

## 2. Performance de Tráfego

{secoes['trafego']}

---

## 3. Análise de Zonas

{secoes['zonas']}

---

## 4. Funil de Clientes

{secoes['funil']}

---

## 5. Anomalias da Semana

{secoes['anomalias']}

---

## 6. Recomendações para a Próxima Semana

{secoes['recomendacoes']}

---

*Relatório gerado a partir de insights estruturados — todos os valores são verificáveis em `insights.json`.*
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  required=True, help="Caminho para insights.json")
    parser.add_argument("--output", required=True, help="Caminho para weekly_report.md")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[ERRO] Ficheiro não encontrado: {args.input}")
        raise FileNotFoundError(args.input)

    # Carrega os dados
    print("[1/7] A carregar insights...")
    todos_insights, por_categoria = extrair_dados(args.input)
    print(f"      {len(todos_insights)} insights carregados")

    # Gera cada secção
    inicio_total = time.time()
    secoes = {}

    print("[2/7] A gerar resumo executivo...")
    secoes["resumo_executivo"] = gerar_resumo_executivo(todos_insights)

    print("[3/7] A gerar secção de tráfego...")
    secoes["trafego"] = gerar_secao_trafego(por_categoria.get("trafego", []))

    print("[4/7] A gerar secção de zonas...")
    secoes["zonas"] = gerar_secao_zonas(por_categoria.get("zonas", []))

    print("[5/7] A gerar secção de funil...")
    secoes["funil"] = gerar_secao_funil(por_categoria.get("funil", []))

    print("[6/7] A gerar secção de anomalias...")
    secoes["anomalias"] = gerar_secao_anomalias(por_categoria.get("anomalias", []))

    print("[7/7] A gerar recomendações...")
    secoes["recomendacoes"] = gerar_recomendacoes(todos_insights)

    duracao_total = round(time.time() - inicio_total, 1)

    # Monta o documento
    with open(args.input, encoding="utf-8") as f:
        dados_raw = json.load(f)

    fonte = dados_raw.get("estrategia_B_few_shot", dados_raw)
    metadata = {
        "modelo":     fonte.get("_modelo", MODELO),
        "estrategia": fonte.get("_estrategia", "B"),
        "duracao_s":  duracao_total,
    }

    report_md = montar_report(secoes, metadata)

    # Guarda o output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"\n[OK] Relatório gerado em {args.output} ({duracao_total}s)")
