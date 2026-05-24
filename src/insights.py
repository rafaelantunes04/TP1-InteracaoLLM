"""
Uso:
    python src/insights.py --input output/metrics.json --output output/insights.json
    python src/insights.py --input output/metrics.json --output output/insights.json --strategy A
    python src/insights.py --input output/metrics.json --output output/insights.json --compare
"""

import argparse
import json
import re
import time
import os
import ollama

# Configuração do modelo
MODELO = "mistral:latest"
TEMPERATURA = 0.0

# Diretório dos prompts
PROMPTS_DIR = "../prompts"

def carregar_prompt(nome_ficheiro: str) -> str:
    """Lê um ficheiro de prompt da pasta prompts e devolve o seu conteúdo."""
    with open(f"{PROMPTS_DIR}/{nome_ficheiro}", encoding="utf-8") as f:
        return f.read()


def construir_prompt_zero_shot(metricas: dict) -> str:
    """Estratégia A: instrução direta sem exemplos."""
    instrucoes    = carregar_prompt("instrucoes.txt")
    pedido        = carregar_prompt("pedido_insights.txt")
    schema_output = carregar_prompt("schema_output.txt")

    return f"""{instrucoes}

MÉTRICAS DA SEMANA:
{json.dumps(metricas, ensure_ascii=False, indent=2)}
{pedido}
{schema_output}
"""


def construir_prompt_few_shot(metricas: dict) -> str:
    """Estratégia B: mostra exemplos de bons e maus insights antes do pedido."""
    instrucoes       = carregar_prompt("instrucoes.txt")
    exemplos         = carregar_prompt("exemplos_few_shot.txt")
    pedido           = carregar_prompt("pedido_insights.txt")
    schema_output    = carregar_prompt("schema_output.txt")

    return f"""{instrucoes}
{exemplos}
---
Agora aplica as mesmas regras às MÉTRICAS REAIS DA SEMANA:
{json.dumps(metricas, ensure_ascii=False, indent=2)}

Lembra-te: cada insight deve ter números concretos das métricas. ZERO afirmações vagas.
{pedido}
{schema_output}
"""


def chamar_ollama(prompt: str) -> str:
    """Envia o prompt ao Ollama e devolve o texto da resposta."""
    resposta = ollama.generate(
        model=MODELO,
        prompt=prompt,
        options={"temperature": TEMPERATURA, "seed": 42}
    )
    return resposta["response"].strip()


def extrair_json(texto: str) -> dict:
    """Extrai o JSON da resposta do modelo.
    O modelo por vezes envolve o JSON em ```json ... ``` — tentamos os dois casos.
    """
    # Caso 1: JSON dentro de bloco markdown
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    # Caso 2: JSON direto no texto
    match = re.search(r"(\{.*\})", texto, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    raise ValueError(f"Não foi possível extrair JSON da resposta:\n{texto[:500]}")


def avaliar_insights(lista_insights: list, metricas: dict) -> dict:
    """Avalia a qualidade dos insights gerados com 4 critérios simples.
    Usado no modo --compare para comparar as duas estratégias.
    """
    metricas_str = json.dumps(metricas)
    pontuacoes = []

    for ins in lista_insights:
        observacao   = ins.get("observacao", "")
        recomendacao = ins.get("recomendacao", "")

        # Tem números na observação?
        tem_numeros = bool(re.search(r"\d+[\.,]?\d*", observacao))

        # Quantos números são verificáveis nas métricas reais?
        numeros_obs      = re.findall(r"\d+[\.,]?\d*", observacao)
        verificados      = sum(1 for n in numeros_obs if n.replace(",", ".") in metricas_str)
        taxa_verificacao = verificados / max(len(numeros_obs), 1)

        # A recomendação é específica (pelo menos 8 palavras)?
        recomendacao_especifica = len(recomendacao.split()) >= 8

        # Confiança declarada pelo modelo
        confianca = ins.get("confianca", 0.5)

        pontuacao = (
            0.35 * int(tem_numeros) +
            0.35 * taxa_verificacao +
            0.20 * int(recomendacao_especifica) +
            0.10 * confianca
        )
        pontuacoes.append(pontuacao)

    return {
        "n_insights":         len(lista_insights),
        "pontuacao_media":    round(sum(pontuacoes) / max(len(pontuacoes), 1), 3),
        "pct_com_numeros":    round(
            sum(1 for ins in lista_insights
                if re.search(r"\d+[\.,]?\d*", ins.get("observacao", "")))
            / max(len(lista_insights), 1) * 100, 1
        ),
        "pct_rec_especifica": round(
            sum(1 for ins in lista_insights if len(ins.get("recomendacao", "").split()) >= 8)
            / max(len(lista_insights), 1) * 100, 1
        ),
    }


def correr_estrategia(metricas: dict, estrategia: str) -> dict:
    """Constrói o prompt, chama o modelo e devolve os insights como dicionário."""
    inicio = time.time()

    if estrategia == "A":
        prompt = construir_prompt_zero_shot(metricas) 
    else:
        prompt = construir_prompt_few_shot(metricas)

    resposta_raw = chamar_ollama(prompt)

    duracao = round(time.time() - inicio, 1)
    print(f"  → Concluído em {duracao}s")

    resultado = extrair_json(resposta_raw)
    resultado["_estrategia"] = estrategia
    resultado["_modelo"]     = MODELO
    resultado["_duracao_s"]  = duracao
    return resultado


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",    required=True, help="Caminho para metrics.json")
    parser.add_argument("--output",   required=True, help="Caminho para insights.json")
    parser.add_argument("--strategy", default="B",   choices=["A", "B"],
                        help="Estratégia: A (zero-shot) ou B (few-shot). Default: B")
    parser.add_argument("--compare",  action="store_true",
                        help="Corre as duas estratégias e compara os resultados")
    args = parser.parse_args()

    # Carrega as métricas
    caminho_input = args.input
    if not os.path.exists(caminho_input):
        print(f"[ERRO] Ficheiro não encontrado: {caminho_input}")
        raise FileNotFoundError()

    with open(caminho_input, encoding="utf-8") as f:
        metricas = json.load(f)

    # Comparação
    if args.compare:
        # Corre as duas estratégias e guarda a comparação
        print("\n[1/2] Estratégia A - Zero-Shot")
        resultado_a = correr_estrategia(metricas, "A")

        print("\n[2/2] Estratégia B - Few-Shot")
        resultado_b = correr_estrategia(metricas, "B")

        avaliacao_a = avaliar_insights(resultado_a.get("insights", []), metricas)
        avaliacao_b = avaliar_insights(resultado_b.get("insights", []), metricas)

        output = {
            "estrategia_A_zero_shot": {**resultado_a, "_avaliacao": avaliacao_a},
            "estrategia_B_few_shot":  {**resultado_b, "_avaliacao": avaliacao_b},
            "comparacao": {
                "vencedor":              "A" if avaliacao_a["pontuacao_media"] > avaliacao_b["pontuacao_media"] else "B",
                "pontuacao_A":           avaliacao_a["pontuacao_media"],
                "pontuacao_B":           avaliacao_b["pontuacao_media"],
                "pct_numeros_A":         avaliacao_a["pct_com_numeros"],
                "pct_numeros_B":         avaliacao_b["pct_com_numeros"],
                "pct_rec_especifica_A":  avaliacao_a["pct_rec_especifica"],
                "pct_rec_especifica_B":  avaliacao_b["pct_rec_especifica"],
            },
            # O report.py usa os insights da estratégia B por defeito
            "insights":         resultado_b.get("insights", []),
            "resumo_executivo": resultado_b.get("resumo_executivo", ""),
        }
        print(f"\n[COMPARAÇÃO] Pontuação A={avaliacao_a['pontuacao_media']} | B={avaliacao_b['pontuacao_media']}")
        print(f"  Vencedor: Estratégia {output['comparacao']['vencedor']}")

    else:
        # Corre só a estratégia escolhida
        print(f"\nA correr estratégia {args.strategy}...")
        resultado  = correr_estrategia(metricas, args.strategy)
        avaliacao  = avaliar_insights(resultado.get("insights", []), metricas)
        resultado["_avaliacao"] = avaliacao
        output = resultado
        print(f"  Pontuação média: {avaliacao['pontuacao_media']}")

    # Guarda o output
    caminho_output = args.output
    os.makedirs(os.path.dirname(caminho_output), exist_ok=True)
    with open(caminho_output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] {len(output.get('insights', []))} insights guardados em {caminho_output}")
