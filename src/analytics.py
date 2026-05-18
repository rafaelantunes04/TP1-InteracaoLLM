import json
import argparse
import pandas as pd
import numpy as np
from collections import Counter


# ── helpers ──────────────────────────────────────────────────────────────────

CHECKOUT_ZONES  = {"Z_C1", "Z_C2", "Z_C3"}
ENTRANCE_ZONES  = {"Z_E1", "Z_E2"}
EXIT_ZONES      = {"Z_E1", "Z_E2", "Z_CK"}
PRODUCT_ZONES   = {f"Z_S{i}" for i in range(1, 8)}
NAV_ZONES       = {f"Z_N{i}" for i in range(1, 11)}

ZONE_LABELS = {
    "Z_E1": "Entrada Norte Esq.", "Z_E2": "Entrada Norte Dir.",
    "Z_C1": "Caixas Esq.", "Z_C2": "Caixas Centro", "Z_C3": "Caixas Dir.",
    "Z_CK": "Saída Pós-Pagamento",
    "Z_N1": "Corredor Esq. L1", "Z_N2": "Corredor Centro L1",
    "Z_N3": "Corredor Dir. L1", "Z_N4": "Corredor Esq. L2",
    "Z_N5": "Corredor Centro L2", "Z_N6": "Corredor Dir. L2",
    "Z_N7": "Corredor Esq. Fundo", "Z_N8": "Corredor Centro Fundo",
    "Z_N9": "Corredor Dir. Fundo", "Z_N10": "Corredor Traseiro",
    "Z_S1": "Frescos/Lacticínios", "Z_S2": "Padaria/Pastelaria",
    "Z_S3": "Talho/Charcutaria", "Z_S4": "Higiene/Limpeza",
    "Z_S5": "Bebidas/Conservas", "Z_S6": "Vinhos/Destilados",
    "Z_S7": "Congelados",
}


def safe_json(obj):
    """Converte tipos NumPy para tipos nativos Python para serialização JSON."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return round(float(obj), 4)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ── carregamento ──────────────────────────────────────────────────────────────

def load_journeys(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={
        "person_id": "str",
        "zone_id":   "category",
        "gender":    "category",
        "age_range": "category",
    })
    df["entry_time"]  = pd.to_datetime(df["entry_time"])
    df["exit_time"]   = pd.to_datetime(df["exit_time"])
    df["visit_date"]  = pd.to_datetime(df["visit_date"]).dt.date
    df["hour_of_day"] = df["hour_of_day"].astype(int)
    df["dwell_s"]     = df["dwell_s"].astype(int)
    return df


# ── métricas de tráfego ───────────────────────────────────────────────────────

def calc_traffic(df: pd.DataFrame) -> dict:
    # Visitantes únicos por dia
    per_day = (
        df.groupby("visit_date")["person_id"]
        .nunique()
        .sort_index()
    )

    # Visitantes únicos por hora (agregado toda a semana)
    per_hour = (
        df.groupby("hour_of_day")["person_id"]
        .nunique()
        .sort_index()
    )

    # Tempo total de visita por pessoa: do primeiro entry ao último exit
    visit_duration = (
        df.groupby("person_id")
        .apply(lambda g: (g["exit_time"].max() - g["entry_time"].min()).total_seconds())
        .rename("total_s")
    )

    # Número médio de zonas visitadas por pessoa
    zones_per_person = df.groupby("person_id")["zone_id"].nunique()

    # Pico horário (hora com mais visitantes únicos)
    peak_hour = int(per_hour.idxmax())

    return {
        "total_unique_visitors":         int(df["person_id"].nunique()),
        "total_zone_visits":             int(len(df)),
        "visitors_per_day":              {str(k): int(v) for k, v in per_day.items()},
        "visitors_per_hour":             {int(k): int(v) for k, v in per_hour.items()},
        "busiest_day":                   str(per_day.idxmax()),
        "quietest_day":                  str(per_day.idxmin()),
        "peak_hour":                     peak_hour,
        "avg_visit_duration_s":          round(float(visit_duration.mean()), 1),
        "median_visit_duration_s":       round(float(visit_duration.median()), 1),
        "avg_zones_per_visit":           round(float(zones_per_person.mean()), 2),
        "visitors_per_day_of_week":      {
            str(k): int(v)
            for k, v in df.groupby(pd.to_datetime(df["visit_date"]).dt.day_name())["person_id"].nunique().items()
        },
    }


# ── métricas por zona ─────────────────────────────────────────────────────────

def calc_zone_metrics(df: pd.DataFrame) -> dict:
    # Tráfego total (entry count) por zona
    traffic = df.groupby("zone_id", observed=True)["person_id"].count().rename("visits")

    # Dwell time médio por zona (apenas quando dwell_s > 0, i.e. houve linger)
    linger_df = df[df["dwell_s"] > 0]
    dwell_mean = linger_df.groupby("zone_id", observed=True)["dwell_s"].mean().rename("avg_dwell_s")
    dwell_med  = linger_df.groupby("zone_id", observed=True)["dwell_s"].median().rename("med_dwell_s")

    # Taxa de paragem: visitantes com linger / visitantes totais
    linger_count  = linger_df.groupby("zone_id", observed=True)["person_id"].count()
    total_count   = df.groupby("zone_id", observed=True)["person_id"].count()
    stop_rate     = (linger_count / total_count).fillna(0).rename("stop_rate")

    zones_df = pd.concat([traffic, dwell_mean, dwell_med, stop_rate], axis=1).fillna(0)
    zones_df.index = zones_df.index.astype(str)

    # Top-10 sequências de zonas mais frequentes
    sequences = []
    for pid, grp in df.sort_values("entry_time").groupby("person_id", sort=False):
        zones_seq = list(grp["zone_id"].astype(str))
        for i in range(len(zones_seq) - 1):
            sequences.append(f"{zones_seq[i]} → {zones_seq[i+1]}")

    top_sequences = [
        {"sequence": seq, "count": int(cnt)}
        for seq, cnt in Counter(sequences).most_common(10)
    ]

    zones_out = {}
    for zone_id, row in zones_df.iterrows():
        zones_out[zone_id] = {
            "label":       ZONE_LABELS.get(zone_id, zone_id),
            "visits":      int(row["visits"]),
            "avg_dwell_s": round(float(row["avg_dwell_s"]), 1),
            "med_dwell_s": round(float(row["med_dwell_s"]), 1),
            "stop_rate":   round(float(row["stop_rate"]), 4),
        }

    return {
        "by_zone":         zones_out,
        "top10_sequences": top_sequences,
    }


# ── funil de clientes ─────────────────────────────────────────────────────────

def calc_funnel(df: pd.DataFrame) -> dict:
    all_visitors  = set(df["person_id"].unique())
    total         = len(all_visitors)

    # Quem passou por cada tipo de zona
    def visitors_in(zone_set):
        return set(df[df["zone_id"].isin(zone_set)]["person_id"].unique())

    entered_nav      = visitors_in(NAV_ZONES)
    entered_product  = visitors_in(PRODUCT_ZONES)
    reached_checkout = visitors_in(CHECKOUT_ZONES)
    exited           = visitors_in(EXIT_ZONES)

    # Quem chegou à caixa vs quem não chegou
    no_checkout = all_visitors - reached_checkout

    # Perfil dos que não chegaram à caixa
    no_ck_df = df[df["person_id"].isin(no_checkout)]
    gender_dist_no_ck  = no_ck_df.drop_duplicates("person_id")["gender"].value_counts(normalize=True).round(4).to_dict()
    age_dist_no_ck     = no_ck_df.drop_duplicates("person_id")["age_range"].value_counts(normalize=True).round(4).to_dict()

    # Perfil geral de todos
    all_df             = df.drop_duplicates("person_id")
    gender_dist_all    = all_df["gender"].value_counts(normalize=True).round(4).to_dict()
    age_dist_all       = all_df["age_range"].value_counts(normalize=True).round(4).to_dict()

    def pct(subset):
        return round(len(subset) / total * 100, 2) if total else 0

    return {
        "total_visitors":            total,
        "reached_navigation":        {"count": len(entered_nav),      "pct": pct(entered_nav)},
        "reached_product_section":   {"count": len(entered_product),  "pct": pct(entered_product)},
        "reached_checkout":          {"count": len(reached_checkout), "pct": pct(reached_checkout)},
        "conversion_rate_pct":       pct(reached_checkout),
        "did_not_reach_checkout": {
            "count":       len(no_checkout),
            "pct":         pct(no_checkout),
            "gender_dist": {str(k): float(v) for k, v in gender_dist_no_ck.items()},
            "age_dist":    {str(k): float(v) for k, v in age_dist_no_ck.items()},
        },
        "overall_gender_dist": {str(k): float(v) for k, v in gender_dist_all.items()},
        "overall_age_dist":    {str(k): float(v) for k, v in age_dist_all.items()},
    }


# ── segmentação demográfica ───────────────────────────────────────────────────

def calc_demographics(df: pd.DataFrame) -> dict:
    uniq = df.drop_duplicates("person_id")

    # Distribuição de género por hora
    gender_hour = (
        uniq.groupby(["hour_of_day", "gender"], observed=True)
        .size()
        .unstack(fill_value=0)
    )
    gender_hour_dict = {
        int(h): {str(g): int(v) for g, v in row.items()}
        for h, row in gender_hour.iterrows()
    }

    # Distribuição de faixa etária por hora
    age_hour = (
        uniq.groupby(["hour_of_day", "age_range"], observed=True)
        .size()
        .unstack(fill_value=0)
    )
    age_hour_dict = {
        int(h): {str(a): int(v) for a, v in row.items()}
        for h, row in age_hour.iterrows()
    }

    # Dwell time médio por segmento e por zona
    linger_df = df[df["dwell_s"] > 0]
    dwell_gender = (
        linger_df.groupby(["zone_id", "gender"], observed=True)["dwell_s"]
        .mean()
        .round(1)
        .unstack()
        .fillna(0)
    )
    dwell_age = (
        linger_df.groupby(["zone_id", "age_range"], observed=True)["dwell_s"]
        .mean()
        .round(1)
        .unstack()
        .fillna(0)
    )

    return {
        "gender_by_hour":       gender_hour_dict,
        "age_range_by_hour":    age_hour_dict,
        "avg_dwell_by_gender_zone": {
            str(z): {str(g): float(v) for g, v in row.items()}
            for z, row in dwell_gender.iterrows()
        },
        "avg_dwell_by_age_zone": {
            str(z): {str(a): float(v) for a, v in row.items()}
            for z, row in dwell_age.iterrows()
        },
    }


# ── deteção de anomalias ──────────────────────────────────────────────────────

def calc_anomalies(df: pd.DataFrame) -> dict:
    """
    Para cada (zona, hora), calcula média e desvio padrão dos primeiros 6 dias.
    Identifica no dia 7 onde o tráfego se desvia > 2σ.
    """
    dates_sorted = sorted(df["visit_date"].unique())
    if len(dates_sorted) < 7:
        return {"warning": "Menos de 7 dias de dados — anomalias não calculadas.", "anomalies": []}

    train_dates = dates_sorted[:6]
    test_date   = dates_sorted[6]

    # Contagem de visitas por (zona, hora, dia)
    df_count = (
        df.groupby(["visit_date", "zone_id", "hour_of_day"], observed=True)
        .size()
        .reset_index(name="visits")
    )

    train = df_count[df_count["visit_date"].isin(train_dates)]
    test  = df_count[df_count["visit_date"] == test_date]

    # Baseline: média e std para cada (zona, hora) nos primeiros 6 dias
    baseline = (
        train.groupby(["zone_id", "hour_of_day"], observed=True)["visits"]
        .agg(["mean", "std"])
        .reset_index()
    )
    baseline["std"] = baseline["std"].fillna(0)

    # Comparar dia 7 com baseline
    merged = test.merge(baseline, on=["zone_id", "hour_of_day"], how="left")
    merged["z_score"] = np.where(
        merged["std"] > 0,
        (merged["visits"] - merged["mean"]) / merged["std"],
        0
    )

    anomalies_df = merged[merged["z_score"].abs() > 2].copy()
    anomalies_df = anomalies_df.sort_values("z_score", key=abs, ascending=False)

    anomalies = []
    for _, row in anomalies_df.iterrows():
        anomalies.append({
            "zone_id":        str(row["zone_id"]),
            "zone_label":     ZONE_LABELS.get(str(row["zone_id"]), str(row["zone_id"])),
            "hour_of_day":    int(row["hour_of_day"]),
            "date":           str(test_date),
            "observed":       int(row["visits"]),
            "expected_mean":  round(float(row["mean"]), 1),
            "expected_std":   round(float(row["std"]), 1),
            "z_score":        round(float(row["z_score"]), 2),
            "direction":      "above" if row["z_score"] > 0 else "below",
        })

    # Resumo de baseline para o report
    baseline_summary = {
        str(row["zone_id"]): {
            int(row["hour_of_day"]): {
                "mean": round(float(row["mean"]), 1),
                "std":  round(float(row["std"]), 1),
            }
        }
        for _, row in baseline.iterrows()
    }

    return {
        "train_dates":       [str(d) for d in train_dates],
        "test_date":         str(test_date),
        "anomaly_count":     len(anomalies),
        "anomalies":         anomalies,
        "baseline_summary":  baseline_summary,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Calcula métricas analíticas a partir de journeys.csv e gera metrics.json."
    )
    parser.add_argument("--input",  required=True, help="Caminho para journeys.csv")
    parser.add_argument("--output", required=True, help="Caminho para metrics.json")
    args = parser.parse_args()

    print(f"[analytics] A carregar {args.input} …")
    df = load_journeys(args.input)
    print(f"[analytics] {len(df):,} linhas carregadas ({df['person_id'].nunique():,} pessoas únicas).")

    metrics = {
        "meta": {
            "generated_at": pd.Timestamp.now().isoformat(),
            "source_file":  args.input,
            "total_rows":   len(df),
        },
        "traffic":      calc_traffic(df),
        "zones":        calc_zone_metrics(df),
        "funnel":       calc_funnel(df),
        "demographics": calc_demographics(df),
        "anomalies":    calc_anomalies(df),
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2, default=safe_json)

    print(f"[analytics] metrics.json escrito em {args.output}")
    print(f"  → {metrics['traffic']['total_unique_visitors']:,} visitantes únicos")
    print(f"  → {metrics['anomalies']['anomaly_count']} anomalias detectadas no dia 7")
    print(f"  → Taxa de conversão para caixa: {metrics['funnel']['conversion_rate_pct']}%")


if __name__ == "__main__":
    main()
