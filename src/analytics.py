import json
import argparse
import pandas as pd
import numpy as np

ZONAS = {
    "corredores": {f"Z_N{i}" for i in range(1, 11)},
    "produtos":   {f"Z_S{i}" for i in range(1, 8)},
    "caixas":     {"Z_C1", "Z_C2", "Z_C3", "Z_CK"}
}

if __name__ == "__main__":
    # Argumentos
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    # Carregar dados e correcões
    df = pd.read_csv(args.input)

    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"]  = pd.to_datetime(df["exit_time"])

    # Calculo das Metricas
    metricas = {}

    # 1. TRAFEGO

    # Duracao de cada visita = diferenca entre a última saída e a primeira entrada da pessoa
    duracoes = df.groupby("person_id").apply(
        lambda x: (x["exit_time"].max() - x["entry_time"].min()).total_seconds(),
        include_groups=False
    )

    metricas["traffic"] = {
        "unique_visitors":      int(df["person_id"].nunique()),
        "visitors_per_day":     df.groupby("visit_date")["person_id"].nunique().to_dict(),
        "visitors_per_hour":    df.groupby("hour_of_day")["person_id"].nunique().to_dict(),
        "visitors_per_weekday": df.groupby(pd.to_datetime(df["visit_date"]).dt.day_name())["person_id"].nunique().to_dict(),
        "avg_visit_duration_s": round(float(duracoes.mean()), 1)
    }

    # 2. ZONAS
    linger = df[df["dwell_s"] > 0] # todos os eventos linger

    # Top 10 sequencias
    df_ord = df.sort_values(["person_id", "entry_time"])
    df_ord["zona_seguinte"] = df_ord.groupby("person_id")["zone_id"].shift(-1)
    pares = df_ord.dropna(subset=["zona_seguinte"])

    top10_sequencias = (pares["zone_id"] + " -> " + pares["zona_seguinte"]).value_counts().head(10).to_dict()

    metricas["zones"] = {
        "traffic":         df.groupby("zone_id")["person_id"].count().to_dict(),
        "avg_dwell_s":     linger.groupby("zone_id")["dwell_s"].mean().round(1).to_dict(),
        # stop_rate: proporcao de visitantes que parou (teve linger) em cada zona
        "stop_rate":       (linger.groupby("zone_id")["person_id"].nunique() / df.groupby("zone_id")["person_id"].nunique()).fillna(0).round(4).to_dict(),
        "top_10_sequences": top10_sequencias
    }

    # 3. FUNIL

    # Quantas pessoas chegaram a cada tipo de zona ao longo da visita
    todos = set(df["person_id"].unique())
    def pessoas_em(zonas):
        return set(df[df["zone_id"].isin(zonas)]["person_id"].unique())


    chegaram_caixa = pessoas_em(ZONAS["caixas"])
    
    nao_chegaram   = todos - chegaram_caixa
    perfil_nao_caixa = df[df["person_id"].isin(nao_chegaram)].drop_duplicates("person_id")

    metricas["funnel"] = {
        "reached_nav":          len(pessoas_em(ZONAS["corredores"])),
        "reached_prod":         len(pessoas_em(ZONAS["produtos"])),
        "reached_checkout":     len(chegaram_caixa),
        "conversion_rate_pct":  round(float(len(chegaram_caixa) / len(todos) * 100), 2),
        "no_checkout_profile": {
            "gender": perfil_nao_caixa["gender"].value_counts(normalize=True).to_dict(),
            "age":    perfil_nao_caixa["age_range"].value_counts(normalize=True).to_dict()
        }
    }

    # 4. DEMOGRAFIA
    unicos = df.drop_duplicates("person_id")

    metricas["demographics"] = {
        "gender_by_hour":      unicos.groupby(["hour_of_day", "gender"]).size().unstack(fill_value=0).to_dict("index"),
        "age_by_hour":         unicos.groupby(["hour_of_day", "age_range"]).size().unstack(fill_value=0).to_dict("index"),
        "dwell_by_gender_zone": linger.groupby(["zone_id", "gender"])["dwell_s"].mean().unstack(fill_value=0).to_dict("index"),
        "dwell_by_age_zone":    linger.groupby(["zone_id", "age_range"])["dwell_s"].mean().unstack(fill_value=0).to_dict("index")
    }

    # 5. ANOMALIAS
    # Para cada par (zona, hora), compara o dia 7 com o comportamento normal dos 6 dias anteriores.
    # "Normal" = média +- 2 desvios padrão. Fora disso é anomalia.

    datas = sorted(df["visit_date"].unique())

    if len(datas) < 7:
        metricas["anomalies"] = []
    else:
        dias_normais = datas[:6]
        dia_teste    = datas[6]

        # Conta visitas por dia + zona + hora
        contagens = (
            df.groupby(["visit_date", "zone_id", "hour_of_day"])
            .size()
            .reset_index(name="visits")
        )

        # Calcula média e desvio padrão dos 6 dias normais, para cada zona+hora
        normais = contagens[contagens["visit_date"].isin(dias_normais)]
        base = (
            normais.groupby(["zone_id", "hour_of_day"])["visits"]
            .agg(["mean", "std"])
            .fillna(0)
            .reset_index()
        )

        # Junta os valores do dia 7 com a baseline (um merge por zona+hora)
        dia7 = (
            contagens[contagens["visit_date"] == dia_teste]
            .merge(base, on=["zone_id", "hour_of_day"], how="left")
        )

        # z-score: quantos desvios padrão o dia 7 se afasta da média
        dia7["z_score"] = np.where(
            dia7["std"] > 0,
            (dia7["visits"] - dia7["mean"]) / dia7["std"],
            0
        )

        # Guarda só as anomalias (|z| > 2), ordenadas da mais grave para a menos grave
        anomalias = (
            dia7[dia7["z_score"].abs() > 2]
            .sort_values("z_score", key=abs, ascending=False)
        )
        anomalias[["mean", "z_score"]] = anomalias[["mean", "z_score"]].round(2)

        metricas["anomalies"] = anomalias[["zone_id", "hour_of_day", "visits", "mean", "z_score"]].to_dict("records")

    # Guardar para Json
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(metricas, f, ensure_ascii=False, indent=2, default=str)

    print(f"Sucesso! {args.output} gerado com base em {args.input}.")