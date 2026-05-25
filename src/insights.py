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

from etc.insights_helper import (
    extrair_grupos_de_anomalias,
    schema_output,
    CATEGORIAS,
    _filtro_trafego,
    _filtro_zona,
    _filtro_funil,
    _filtro_anomalia,
    _filtro_demografico,
)


# Configuração
MODELO = "llama3.2:3b"
TEMPERATURA = 0.0
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts")

# Filtro de métricas por categoria
FILTROS = {
    "trafego":     _filtro_trafego,
    "zonas":       _filtro_zona,
    "funil":       _filtro_funil,
    "anomalias":   _filtro_anomalia,
    "demografico": _filtro_demografico,
}

# Ficheiro de exemplos few-shot por categoria
FICHEIROS_FEW_SHOT = {
    "trafego":     "exemplos_few_shot/exemplos_trafego.txt",
    "zonas":       "exemplos_few_shot/exemplos_zona.txt",
    "funil":       "exemplos_few_shot/exemplos_funil.txt",
    "anomalias":   "exemplos_few_shot/exemplos_anomalia.txt",
    "demografico": "exemplos_few_shot/exemplos_demografico.txt",
}

# Número fixo de insights por categoria
N_INSIGHTS_FIXO = {
    "trafego":     3,
    "zonas":       2,
    "funil":       3,
    "demografico": 2,
}


# Utilitários de I/O
def carregar_prompt(nome_ficheiro: str) -> str:
    """Lê um ficheiro de prompt da pasta prompts/ e devolve o seu conteúdo."""
    caminho = os.path.join(PROMPTS_DIR, nome_ficheiro)
    with open(caminho, encoding="utf-8") as f:
        return f.read()



# Pré-processamento de métricas
def pre_processar_metricas(metricas: dict) -> dict:
    """Agrupa as anomalias brutas e adiciona 'anomaly_groups' ao dict de métricas.

    Necessário antes de chamar _filtro_anomalia, que espera essa chave.
    Modifica o dict in-place e devolve-o.
    """
    grupos = extrair_grupos_de_anomalias(metricas.get("anomalies", []))
    metricas["anomaly_groups"] = grupos
    return metricas



# Construção de prompts
def _formatar_pedido(categoria: str, n_insights: int) -> str:
    """Constrói a instrução de pedido a partir da definição em CATEGORIAS."""
    temas = CATEGORIAS[categoria]
    if isinstance(temas, list):
        bullets = "\n".join(f"- {t}" for t in temas)
        return (
            f"Gera exatamente {n_insights} insights, um por cada tema:\n{bullets}\n"
            f"A ordem dos insights deve seguir a ordem dos temas acima."
        )
    else:
        return f"Gera exatamente {n_insights} insight(s) sobre: {temas}"


def construir_prompt_zero_shot(metricas_filtradas: dict, categoria: str, n_insights: int) -> str:
    """Estratégia A: instrução direta sem exemplos."""
    instrucoes = carregar_prompt("instrucoes.txt")
    regras     = carregar_prompt("regras.txt")
    pedido     = _formatar_pedido(categoria, n_insights)
    schema     = schema_output(categoria)

    return f"""{instrucoes}

{regras}

CATEGORIA: {categoria}

MÉTRICAS:
{json.dumps(metricas_filtradas, ensure_ascii=False, indent=2)}

{pedido}

{schema}
"""


def construir_prompt_few_shot(metricas_filtradas: dict, categoria: str, n_insights: int) -> str:
    """Estratégia B: exemplos de bons e maus insights antes do pedido."""
    instrucoes = carregar_prompt("instrucoes.txt")
    regras     = carregar_prompt("regras.txt")
    exemplos   = carregar_prompt(FICHEIROS_FEW_SHOT[categoria])
    pedido     = _formatar_pedido(categoria, n_insights)
    schema     = schema_output(categoria)

    return f"""{instrucoes}

{regras}

{exemplos}

---
Agora aplica as mesmas regras às MÉTRICAS REAIS:

CATEGORIA: {categoria}

MÉTRICAS:
{json.dumps(metricas_filtradas, ensure_ascii=False, indent=2)}

Lembra-te: cada insight deve ter números concretos das métricas. ZERO afirmações vagas.
{pedido}

{schema}
"""


# Chamada ao modelo
def chamar_ollama(prompt: str) -> str:
    """Envia o prompt ao Ollama e devolve o texto da resposta."""
    resposta = ollama.generate(
        model=MODELO,
        prompt=prompt,
        options={"temperature": TEMPERATURA, "seed": 42, "num_predict": 1200},
    )
    return resposta["response"].strip()


def _extrair_objetos_json(texto: str) -> list:
    """Extrai todos os objetos JSON de nível superior do texto,
    ignorando texto livre entre eles (títulos, markdown, etc.).
    """
    objetos = []
    i = 0
    while i < len(texto):
        if texto[i] == "{":
            depth, start = 0, i
            for j, c in enumerate(texto[i:]):
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                if depth == 0:
                    candidato = texto[start : start + j + 1]
                    try:
                        obj = json.loads(candidato)
                        if isinstance(obj, dict):
                            objetos.append(obj)
                    except json.JSONDecodeError:
                        pass
                    i = start + j + 1
                    break
            else:
                i += 1
        else:
            i += 1
    return objetos


def _montar_resultado(objetos: list) -> dict:
    """Monta o dict final a partir de um ou mais objetos JSON.

    Trata dois formatos que o modelo pode devolver:
    - Wrapper : {"insights": [...], "resumo_executivo": "..."}
    - Bare    : {"id": "INS_001", "categoria": ..., ...}  (insight individual)
    Devolve sempre {"insights": [...], "resumo_executivo": "..."}.
    """
    insights_merged = []
    resumo = ""
    for obj in objetos:
        if "insights" in obj:
            insights_merged.extend(obj.get("insights", []))
            if not resumo and obj.get("resumo_executivo"):
                resumo = obj["resumo_executivo"]
        elif "id" in obj and "categoria" in obj:
            insights_merged.append(obj)
    return {"insights": insights_merged, "resumo_executivo": resumo}


def extrair_json(texto: str) -> dict:
    """Extrai o JSON da resposta do modelo.

    Casos tratados:
    1. JSON dentro de bloco ```json ... ```
    2. Um único objeto wrapper  {"insights": [...]}
    3. Múltiplos objetos wrapper separados por texto livre
    4. Múltiplos objetos bare (um por insight) separados por texto livre
    Em caso de falha imprime os primeiros 800 chars para debug.
    """
    # Caso 1 - bloco markdown
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Casos 2, 3 e 4 - extrair todos os objetos ignorando texto livre
    objetos = _extrair_objetos_json(texto)

    if not objetos:
        print(f"[DEBUG] Resposta raw do modelo (800 chars):\n{texto[:800]}")
        raise ValueError("Não foi possível extrair JSON válido da resposta do modelo.")

    if len(objetos) > 1:
        print(f"  [AVISO] Modelo devolveu {len(objetos)} JSONs separados - merge automático aplicado.")

    return _montar_resultado(objetos)


# Execução por categoria
def _n_insights_categoria(categoria: str, metricas: dict) -> int:
    """Devolve o número esperado de insights para a categoria."""
    if categoria == "anomalias":
        return len(metricas.get("anomaly_groups", []))
    return N_INSIGHTS_FIXO[categoria]


def correr_categoria(metricas: dict, categoria: str, estrategia: str) -> dict:
    """Filtra as métricas, constrói o prompt e chama o modelo para uma categoria.

    Devolve o dict com 'insights', 'resumo_executivo' e metadados.
    """
    n_insights = _n_insights_categoria(categoria, metricas)

    if n_insights == 0:
        print(f"  [AVISO] {categoria}: sem grupos de anomalias. A saltar.")
        return {
            "insights":         [],
            "resumo_executivo": "",
            "_estrategia":      estrategia,
            "_modelo":          MODELO,
            "_duracao_s":       0.0,
            "_n_insights_pedido": 0,
        }

    metricas_filtradas = FILTROS[categoria](metricas)

    inicio = time.time()

    if estrategia == "A":
        prompt = construir_prompt_zero_shot(metricas_filtradas, categoria, n_insights)
    else:
        prompt = construir_prompt_few_shot(metricas_filtradas, categoria, n_insights)

    resposta_raw = chamar_ollama(prompt)
    duracao = round(time.time() - inicio, 1)
    print(f"    [{categoria}] concluído em {duracao}s")

    resultado = extrair_json(resposta_raw)
    resultado["_estrategia"]        = estrategia
    resultado["_modelo"]            = MODELO
    resultado["_duracao_s"]         = duracao
    resultado["_n_insights_pedido"] = n_insights
    return resultado


def correr_todas_categorias(metricas: dict, estrategia: str) -> dict:
    """Corre o LLM para cada categoria e agrega os resultados.

    Devolve um dict com:
      - por_categoria: {categoria: resultado_categoria, ...}
      - insights:      lista agregada de todos os insights
      - resumo_executivo: string vazia (gerado em report.py a partir dos insights)
      - _estrategia, _modelo, _duracao_total_s
    """
    por_categoria: dict  = {}
    todos_insights: list = []
    duracao_total        = 0.0

    for categoria in CATEGORIAS:
        print(f"\n  → Categoria: {categoria}")
        resultado = correr_categoria(metricas, categoria, estrategia)
        por_categoria[categoria] = resultado
        todos_insights.extend(resultado.get("insights", []))
        duracao_total += resultado.get("_duracao_s", 0.0)
    
    for i, ins in enumerate(todos_insights, start=1):
        ins["id"] = f"INS_{i:03d}"

    return {
        "por_categoria":     por_categoria,
        "insights":          todos_insights,
        "resumo_executivo":  "",
        "_estrategia":       estrategia,
        "_modelo":           MODELO,
        "_duracao_total_s":  round(duracao_total, 1),
    }


# Avaliação de qualidade
def avaliar_insights(lista_insights: list, metricas: dict) -> dict:
    """Usa o Ollama para avaliar os insights com base em critérios de negócio reais."""
    if not lista_insights:
        return {"pontuacao_media": 0, "n_insights": 0}

    metricas_str = json.dumps(metricas, ensure_ascii=False)
    pontuacoes = []

    for ins in lista_insights:
        prompt_avaliacao = f"""
        Atua como um Gestor de Retalho sénior rigoroso. Avalia este insight gerado por um analista júnior.
        
        MÉTRICAS REAIS:
        {metricas_str}
        
        INSIGHT A AVALIAR:
        Título: {ins.get('titulo')}
        Observação: {ins.get('observacao')}
        Recomendação: {ins.get('recomendacao')}
        
        AVALIAÇÃO (Responde APENAS com um número de 0.0 a 1.0 baseando-te nestes critérios):
        - A observação faz sentido matematicamente e não tem números absurdos/alucinados?
        - A recomendação é específica, acionável e útil (ex: sugere ações físicas, horas ou locais exatos em vez de jargão de marketing)?
        - O insight deriva inteligência útil (ex: diferenças de percentagem) em vez de apenas copiar as métricas?
        """
        
        try:
            # Pede ao Ollama para dar uma nota
            resposta = ollama.generate(
                model=MODELO,
                prompt=prompt_avaliacao,
                options={"temperature": 0.0, "num_predict": 10}
            )
            # Extrai o número da resposta (ex: "0.8")
            nota = float(re.search(r"0\.\d+|1\.0", resposta["response"]).group())
            pontuacoes.append(nota)
        except Exception as e:
            pontuacoes.append(0.5) # Fallback em caso de erro

    pontuacao_media = sum(pontuacoes) / len(pontuacoes)

    return {
        "pontuacao_media": round(pontuacao_media, 3)
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",    required=True, help="Caminho para metrics.json")
    parser.add_argument("--output",   required=True, help="Caminho para insights.json")
    parser.add_argument("--strategy", default="B", choices=["A", "B"],
                        help="Estratégia: A (zero-shot) ou B (few-shot). Default: B")
    parser.add_argument("--compare",  action="store_true",
                        help="Corre as duas estratégias e compara os resultados")
    args = parser.parse_args()

    # Carrega e pré-processa as métricas
    if not os.path.exists(args.input):
        print(f"[ERRO] Ficheiro não encontrado: {args.input}")
        raise FileNotFoundError(args.input)

    with open(args.input, encoding="utf-8") as f:
        metricas = json.load(f)

    metricas = pre_processar_metricas(metricas)
    n_grupos = len(metricas["anomaly_groups"])
    print(f"[INFO] {n_grupos} grupo(s) de anomalias detectados → {n_grupos} insight(s) de anomalias")

    #  Comparação
    if args.compare:
        print("\n[1/2] Estratégia A – Zero-Shot")
        resultado_a = correr_todas_categorias(metricas, "A")

        print("\n[2/2] Estratégia B – Few-Shot")
        resultado_b = correr_todas_categorias(metricas, "B")

        # print("\n[INFO] A carregar resultados do ficheiro JSON para evitar re-execução do modelo...")
        # with open(args.output, "r", encoding="utf-8") as f:
        #     dados_guardados = json.load(f)

        # resultado_a = dados_guardados["estrategia_A_zero_shot"]
        # resultado_b = dados_guardados["estrategia_B_few_shot"]

        avaliacao_a = avaliar_insights(resultado_a["insights"], metricas)
        avaliacao_b = avaliar_insights(resultado_b["insights"], metricas)

        vencedor = "A" if avaliacao_a["pontuacao_media"] > avaliacao_b["pontuacao_media"] else "B"
        print(f"\n[COMPARAÇÃO] Pontuação A={avaliacao_a['pontuacao_media']} | B={avaliacao_b['pontuacao_media']}")
        print(f"  Vencedor: Estratégia {vencedor}")

        output = {
            "estrategia_A_zero_shot": {**resultado_a, "_avaliacao": avaliacao_a},
            "estrategia_B_few_shot":  {**resultado_b, "_avaliacao": avaliacao_b},
            "comparacao": {
                "vencedor":             vencedor,
                "pontuacao_A":          avaliacao_a["pontuacao_media"],
                "pontuacao_B":          avaliacao_b["pontuacao_media"],
                "pct_numeros_A":        avaliacao_a["pct_com_numeros"],
                "pct_numeros_B":        avaliacao_b["pct_com_numeros"],
                "pct_rec_especifica_A": avaliacao_a["pct_rec_especifica"],
                "pct_rec_especifica_B": avaliacao_b["pct_rec_especifica"],
            },
            # report.py usa a estratégia B por defeito
            "por_categoria":    resultado_b["por_categoria"],
            "insights":         resultado_b["insights"],
            "resumo_executivo": resultado_b["resumo_executivo"],
        }

    # Modo normal (uma estratégia)
    else:
        print(f"\nA correr estratégia {args.strategy} para todas as categorias...")
        output    = correr_todas_categorias(metricas, args.strategy)
        avaliacao = avaliar_insights(output["insights"], metricas)
        output["_avaliacao"] = avaliacao
        print(f"\n  Pontuação média: {avaliacao['pontuacao_media']}")
        for cat, res in output["por_categoria"].items():
            n = len(res.get("insights", []))
            print(f"    {cat}: {n} insight(s)")

    # Guarda o output
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] {len(output['insights'])} insights guardados em {args.output}")
