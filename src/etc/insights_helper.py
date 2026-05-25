import pandas as pd

def schema_output(categoria: str) -> str:
    return f"""{{
  "insights": [
    {{
      "id": "INS_001",
      "categoria": "{categoria}",
      "titulo": "frase curta que resume o insight",
      "observacao": "o que os dados mostram: factos, números concretos",
      "implicacao": "o que isto significa operacionalmente",
      "recomendacao": "ação concreta que o gestor pode tomar",
      "urgencia": "imediata|esta_semana|proximo_mes",
      "confianca": 0.0
    }}
  ],
  "resumo_executivo": "3 bullets com os insights mais importantes"
}}"""


# Filtros de métricas — funções puras que recebem o dict completo (já
# pré-processado por pre_processar_metricas) e devolvem só o subconjunto
# relevante para cada categoria.
def extrair_grupos_de_anomalias(lista_anomalias, min_threshold=3):
    """
    Identifica e agrupa anomalias por padrões que encontra, estes podendo ser
     de espaço temporal ou da mesma zona mais de **min threshold** vezes.
    """
    df = pd.DataFrame(lista_anomalias)
    resultado_final = []
    
    # Identificar e extrair anomalias com as mesmas horas
    contagem_horas = df['hour_of_day'].value_counts()
    anom_horas = contagem_horas[contagem_horas >= min_threshold].index
    
    for h in anom_horas:
        grupo = df[df['hour_of_day'] == h].to_dict('records')
        resultado_final.append(grupo)
    
    # Identificar e extrair anomalias de zonas problematicas
    contagem_zonas = df['zone_id'].value_counts()
    anom_zona_prob = contagem_zonas[contagem_zonas >= min_threshold].index
    
    for z in anom_zona_prob:
        grupo = df[df['zone_id'] == z].to_dict('records')
        resultado_final.append(grupo)
        
    return resultado_final


def _filtro_trafego(m: dict) -> dict:
    """Tráfego: padrão diário, horário e semanal.
    Envia apenas o bloco traffic (~530 chars vs 12 kB do JSON completo).
    """
    return {"traffic": m["traffic"]}


def _filtro_zona(m: dict) -> dict:
    """Zonas: tráfego por zona, dwell, stop_rate, sequências de navegação e funil.

    Adicionado o bloco funnel para que o LLM consiga avaliar a performance de
    cada zona no percurso de conversão (navegação → produto → caixa) e não
    apenas pelo volume bruto de tráfego.
    """
    return {
        "zones": {
            "traffic":          m["zones"]["traffic"],
            "avg_dwell_s":      m["zones"]["avg_dwell_s"],
            "stop_rate":        m["zones"]["stop_rate"],
            "top_10_sequences": m["zones"]["top_10_sequences"],
        },
        "funnel": m["funnel"],
    }


def _filtro_funil(m: dict) -> dict:
    """Funil de conversão: todas as etapas, perfil de não-conversão, total de
    visitantes únicos e sequências de navegação mais frequentes.

    unique_visitors é necessário para calcular as perdas absolutas em cada etapa
    (o bloco funnel só tem valores de 'reached_*' sem referência ao total).
    top_10_sequences mostra os percursos concretos e ajuda a identificar onde
    o tráfego se perde antes da caixa.
    """
    return {
        "funnel": m["funnel"],
        "traffic": {
            "unique_visitors": m["traffic"]["unique_visitors"],
        },
        "zones": {
            "top_10_sequences": m["zones"]["top_10_sequences"],
        },
    }


def _filtro_anomalia(m: dict) -> dict:
    """Anomalias: grupos pré-processados + contexto de zona e hora.

    Sem contexto, o LLM não consegue avaliar a gravidade de um desvio:
    - zones.traffic e zones.avg_dwell_s dão o perfil normal de cada zona
      que aparece nos grupos (volume habitual, tempo de permanência típico).
    - traffic.visitors_per_hour mostra o padrão de afluência na hora anómala,
      permitindo distinguir picos normais de verdadeiras anomalias.
    Requer que pre_processar_metricas() já tenha sido chamado.
    """
    return {
        "anomaly_groups": m["anomaly_groups"],
        "zones": {
            "traffic":     m["zones"]["traffic"],
            "avg_dwell_s": m["zones"]["avg_dwell_s"],
        },
        "traffic": {
            "visitors_per_hour": m["traffic"]["visitors_per_hour"],
        },
    }


def _filtro_demografico(m: dict) -> dict:
    """Demográfico: gender_by_hour, age_by_hour, visitors_per_hour e top-N zonas
    com maior variância de dwell por idade.

    age_by_hour é reintroduzido: é a única fonte que mostra como a composição
    etária muda ao longo do dia (e.g. crianças ao fim da manhã, seniores cedo),
    essencial para insights demográficos accionáveis.

    visitors_per_hour é adicionado para que o LLM converta contagens absolutas
    de género em proporções relativas por hora (e.g. 290F às 17h num total de
    559 visitantes = 52% feminino, não apenas "mais mulheres").

    dwell_by_age_zone mantém só as N_ZONAS_DEMO zonas com maior spread entre
    segmentos etários — as restantes têm variação < 1 s e são irrelevantes.

    dwell_by_gender_zone é excluído: a variação de dwell por género é marginal
    (< 7 s em todas as zonas) e não gera insights accionáveis.
    """
    N_ZONAS_DEMO = 5

    dwell_completo = m["demographics"]["dwell_by_age_zone"]
    spreads = {
        zona: max(ages.values()) - min(ages.values())
        for zona, ages in dwell_completo.items()
    }
    top_zonas = sorted(spreads, key=lambda z: -spreads[z])[:N_ZONAS_DEMO]
    dwell_filtrado = {z: dwell_completo[z] for z in top_zonas}

    return {
        "demographics": {
            "gender_by_hour":    m["demographics"]["gender_by_hour"],
            "age_by_hour":       m["demographics"]["age_by_hour"],
            "dwell_by_age_zone": dwell_filtrado,
        },
        "traffic": {
            "visitors_per_hour": m["traffic"]["visitors_per_hour"],
        },
    }

# Definição central de categorias
CATEGORIAS = {
    "trafego": ["Afluência da Semana numa visão geral",
                "Padrões de hora de pico",
                "Dias mais e menos movimentados"],
    "zonas": ["Top 3 zonas com melhor performance",
              "Top 3 zonas com pior performance"],
    "funil": ["Análise geral da entrada até à caixa",
              "Análise de onde se perde tráfego",
              "Perfil dos clientes que não chegam à caixa"],
    "anomalias": "Analisar problema do grupo de anomalias (possível padrão)",
    "demografico": "Dois insights com visão demográfica"
}
