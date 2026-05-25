"""
Uso:
    python evaluate.py --data events_validation.csv --output evaluation_report.json
    python evaluate.py --data events_validation.csv --output evaluation_report.json --ground-truth anomalies.json
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime

import pandas as pd


# Configuração
ZONAS_ENTRADA_SAIDA = {"Z_E1", "Z_E2", "Z_CK"}


class PipelineEvaluator:
    """Avalia o pipeline completo: stitcher → analytics → insights → report."""

    def __init__(self, events_csv: str, ground_truth_anomalies: str = None):
        self.events_csv = events_csv
        self.ground_truth = ground_truth_anomalies
        
        # Criar directório temporário para outputs intermédios
        self.temp_dir = tempfile.mkdtemp(prefix="tp1_eval_")
        
        self.journeys_csv = os.path.join(self.temp_dir, "journeys.csv")
        self.metrics_json = os.path.join(self.temp_dir, "metrics.json")
        self.insights_json = os.path.join(self.temp_dir, "insights.json")
        self.report_md = os.path.join(self.temp_dir, "weekly_report.md")
        
        self.metricas = {}
        self.tempo_total = 0.0

    def executar_pipeline(self):
        """Executa os 4 módulos do pipeline em sequência."""
        print("\n" + "="*70)
        print("EXECUÇÃO DO PIPELINE")
        print("="*70)
        
        inicio_total = time.time()
        
        # 1. Stitcher
        print("\n[1/4] Executando stitcher.py...")
        inicio = time.time()
        resultado = subprocess.run([
            "python", "src/stitcher.py",
            "--input", self.events_csv,
            "--output", self.journeys_csv
        ], capture_output=True, text=True)
        
        if resultado.returncode != 0:
            raise RuntimeError(f"Erro no stitcher.py:\n{resultado.stderr}")
        
        duracao = time.time() - inicio
        print(f"       Concluído em {duracao:.1f}s")
        self.metricas["tempo_stitcher_s"] = round(duracao, 1)
        
        # 2. Analytics
        print("\n[2/4] Executando analytics.py...")
        inicio = time.time()
        resultado = subprocess.run([
            "python", "src/analytics.py",
            "--input", self.journeys_csv,
            "--output", self.metrics_json
        ], capture_output=True, text=True)
        
        if resultado.returncode != 0:
            raise RuntimeError(f"Erro no analytics.py:\n{resultado.stderr}")
        
        duracao = time.time() - inicio
        print(f"       Concluído em {duracao:.1f}s")
        self.metricas["tempo_analytics_s"] = round(duracao, 1)
        
        # 3. Insights
        print("\n[3/4] Executando insights.py...")
        inicio = time.time()
        resultado = subprocess.run([
            "python", "src/insights.py",
            "--input", self.metrics_json,
            "--output", self.insights_json,
            "--strategy", "B"
        ], capture_output=True, text=True)
        
        if resultado.returncode != 0:
            raise RuntimeError(f"Erro no insights.py:\n{resultado.stderr}")
        
        duracao = time.time() - inicio
        print(f"       Concluído em {duracao:.1f}s")
        self.metricas["tempo_insights_s"] = round(duracao, 1)
        
        # 4. Report
        print("\n[4/4] Executando report.py...")
        inicio = time.time()
        resultado = subprocess.run([
            "python", "src/report.py",
            "--input", self.insights_json,
            "--output", self.report_md
        ], capture_output=True, text=True)
        
        if resultado.returncode != 0:
            raise RuntimeError(f"Erro no report.py:\n{resultado.stderr}")
        
        duracao = time.time() - inicio
        print(f"       Concluído em {duracao:.1f}s")
        self.metricas["tempo_report_s"] = round(duracao, 1)
        
        self.tempo_total = time.time() - inicio_total
        self.metricas["tempo_total_pipeline_s"] = round(self.tempo_total, 1)
        
        print(f"\n Pipeline completo executado em {self.tempo_total:.1f}s")

    def avaliar_consistencia(self) -> dict:
        """
        Métrica 1: Consistência temporal
        Verifica se há trajectórias onde a pessoa está em duas zonas ao mesmo tempo.
        Deve ser 100%.
        """
        print("\n[AVALIAÇÃO 1/6] Consistência temporal...")
        
        df = pd.read_csv(self.journeys_csv)
        df["entry_time"] = pd.to_datetime(df["entry_time"])
        df["exit_time"] = pd.to_datetime(df["exit_time"])
        
        total_pessoas = df["person_id"].nunique()
        violacoes = 0
        pessoas_com_violacao = set()
        
        for person_id, grupo in df.groupby("person_id"):
            # Ordenar por entry_time
            grupo = grupo.sort_values("entry_time")
            
            for i in range(len(grupo) - 1):
                atual = grupo.iloc[i]
                proxima = grupo.iloc[i + 1]
                
                # Violação: próxima zona começa antes da zona atual terminar
                if proxima["entry_time"] < atual["exit_time"]:
                    violacoes += 1
                    pessoas_com_violacao.add(person_id)
        
        pct_consistente = (total_pessoas - len(pessoas_com_violacao)) / total_pessoas * 100
        
        resultado = {
            "total_trajectórias": int(total_pessoas),
            "trajectórias_consistentes": int(total_pessoas - len(pessoas_com_violacao)),
            "violações_detectadas": int(violacoes),
            "percentagem_consistente": round(pct_consistente, 2),
            "aprovado": pct_consistente == 100.0
        }
        
        print(f"      Consistência: {pct_consistente:.1f}% ({total_pessoas - len(pessoas_com_violacao)}/{total_pessoas})")
        return resultado

    def avaliar_cobertura(self) -> dict:
        """
        Métrica 2: Cobertura
        % de eventos do dataset original que foram atribuídos a alguma trajectória.
        """
        print("\n[AVALIAÇÃO 2/6] Cobertura de eventos...")
        
        # Eventos originais
        df_eventos = pd.read_csv(self.events_csv)
        total_eventos = len(df_eventos)
        
        # Eventos nas trajectórias reconstruídas
        df_journeys = pd.read_csv(self.journeys_csv)
        
        # Cada linha de journeys representa 1 entry + 0-1 linger + 1 exit
        # Para contar eventos cobertos, somamos:
        # - 1 entry por linha
        # - 1 exit por linha
        # - 1 linger se dwell_s > 0
        eventos_cobertos = len(df_journeys) * 2  # entry + exit
        eventos_cobertos += (df_journeys["dwell_s"] > 0).sum()  # lingers
        
        pct_cobertura = eventos_cobertos / total_eventos * 100
        
        resultado = {
            "total_eventos_originais": int(total_eventos),
            "eventos_atribuídos": int(eventos_cobertos),
            "eventos_descartados": int(total_eventos - eventos_cobertos),
            "percentagem_cobertura": round(pct_cobertura, 2)
        }
        
        print(f"      Cobertura: {pct_cobertura:.1f}% ({eventos_cobertos}/{total_eventos})")
        return resultado

    def avaliar_completude(self) -> dict:
        """
        Métrica 3: Completude
        % de trajectórias que começam numa zona de entrada (Z_E) e terminam numa zona de saída (Z_E ou Z_CK).
        """
        print("\n[AVALIAÇÃO 3/6] Completude de trajectórias...")
        
        df = pd.read_csv(self.journeys_csv)
        df["entry_time"] = pd.to_datetime(df["entry_time"])
        
        total_pessoas = df["person_id"].nunique()
        completas = 0
        
        for person_id, grupo in df.groupby("person_id"):
            grupo = grupo.sort_values("entry_time")
            
            primeira_zona = grupo.iloc[0]["zone_id"]
            ultima_zona = grupo.iloc[-1]["zone_id"]
            
            # Completa: começa em Z_E1/Z_E2 e termina em Z_E1/Z_E2/Z_CK
            if primeira_zona in {"Z_E1", "Z_E2"} and ultima_zona in ZONAS_ENTRADA_SAIDA:
                completas += 1
        
        pct_completas = completas / total_pessoas * 100
        
        resultado = {
            "total_trajectórias": int(total_pessoas),
            "trajectórias_completas": int(completas),
            "trajectórias_incompletas": int(total_pessoas - completas),
            "percentagem_completas": round(pct_completas, 2)
        }
        
        print(f"      Completude: {pct_completas:.1f}% ({completas}/{total_pessoas})")
        return resultado

    def avaliar_detecao_anomalias(self) -> dict:
        """
        Métrica 4: Deteção de anomalias
        % das anomalias injetadas que foram corretamente identificadas nos insights.
        Requer ficheiro ground-truth com anomalias conhecidas.
        """
        print("\n[AVALIAÇÃO 4/6] Deteção de anomalias...")
        
        if not self.ground_truth or not os.path.exists(self.ground_truth):
            print("      [AVISO] Sem ficheiro ground-truth - métrica não disponível")
            return {
                "ground_truth_disponível": False,
                "mensagem": "Ficheiro ground-truth não fornecido"
            }
        
        # Carregar ground truth
        with open(self.ground_truth, encoding="utf-8") as f:
            gt = json.load(f)
        
        # Formato esperado: {"anomalies": [{"zone_id": "Z_N4", "hour": 16, "day": 7}, ...]}
        anomalias_esperadas = gt.get("anomalies", [])
        
        # Carregar anomalias detectadas
        with open(self.insights_json, encoding="utf-8") as f:
            insights_data = json.load(f)
        
        insights_anomalias = [
            ins for ins in insights_data.get("insights", [])
            if ins.get("categoria") == "anomalia"
        ]
        
        # Extrair (zona, hora) dos insights
        anomalias_detectadas = []
        for ins in insights_anomalias:
            titulo = ins.get("titulo", "")
            observacao = ins.get("observacao", "")
            
            # Tentar extrair zona e hora
            match_zona = re.search(r"Z_[A-Z]+\d+", titulo + " " + observacao)
            match_hora = re.search(r"(\d{1,2})h", titulo + " " + observacao)
            
            if match_zona and match_hora:
                anomalias_detectadas.append({
                    "zone_id": match_zona.group(0),
                    "hour": int(match_hora.group(1))
                })
        
        # Matching: anomalia detectada se (zona, hora) coincidem
        detectadas_corretas = 0
        for esperada in anomalias_esperadas:
            for detectada in anomalias_detectadas:
                if (esperada.get("zone_id") == detectada.get("zone_id") and
                    esperada.get("hour") == detectada.get("hour")):
                    detectadas_corretas += 1
                    break
        
        total_esperadas = len(anomalias_esperadas)
        pct_detecao = detectadas_corretas / total_esperadas * 100 if total_esperadas > 0 else 0
        
        resultado = {
            "ground_truth_disponível": True,
            "anomalias_esperadas": int(total_esperadas),
            "anomalias_detectadas": len(anomalias_detectadas),
            "anomalias_correctas": int(detectadas_corretas),
            "percentagem_detecção": round(pct_detecao, 2)
        }
        
        print(f"      Deteção: {pct_detecao:.1f}% ({detectadas_corretas}/{total_esperadas})")
        return resultado

    def avaliar_precisao_numerica(self) -> dict:
        """
        Métrica 5: Precisão numérica
        % de valores numéricos nos insights que são verificáveis nos dados calculados (metrics.json).
        """
        print("\n[AVALIAÇÃO 5/6] Precisão numérica...")
        
        # Carregar metrics e insights
        with open(self.metrics_json, encoding="utf-8") as f:
            metrics = json.load(f)
        
        with open(self.insights_json, encoding="utf-8") as f:
            insights_data = json.load(f)
        
        # Converter metrics para string para busca rápida
        metrics_str = json.dumps(metrics)
        
        # Extrair todos os números dos insights
        insights = insights_data.get("insights", [])
        numeros_total = 0
        numeros_verificados = 0
        
        for ins in insights:
            observacao = ins.get("observacao", "")
            
            # Extrair números (inteiros e decimais)
            numeros = re.findall(r"\d+[.,]?\d*", observacao)
            numeros_total += len(numeros)
            
            # Verificar se cada número aparece em metrics.json
            for num in numeros:
                num_normalizado = num.replace(",", ".")
                
                # Verificação flexível: procura o número ou variações (arredondamentos)
                if num_normalizado in metrics_str or num in metrics_str:
                    numeros_verificados += 1
                else:
                    # Tentar variações: arredondado para inteiro, uma casa decimal
                    try:
                        val = float(num_normalizado)
                        if str(int(val)) in metrics_str or f"{val:.1f}" in metrics_str:
                            numeros_verificados += 1
                    except ValueError:
                        pass
        
        pct_verificacao = numeros_verificados / numeros_total * 100 if numeros_total > 0 else 0
        
        resultado = {
            "números_extraídos": int(numeros_total),
            "números_verificáveis": int(numeros_verificados),
            "percentagem_precisão": round(pct_verificacao, 2)
        }
        
        print(f"      Precisão: {pct_verificacao:.1f}% ({numeros_verificados}/{numeros_total})")
        return resultado

    def avaliar_ausencia_alucinacao(self) -> dict:
        """
        Métrica 6: Ausência de alucinação
        % de afirmações factuais no report que são verificáveis no metrics.json ou insights.json.
        
        Aproximação simples: extrai números do report e verifica se estão nos dados.
        """
        print("\n[AVALIAÇÃO 6/6] Ausência de alucinação...")
        
        # Carregar report
        with open(self.report_md, encoding="utf-8") as f:
            report_text = f.read()
        
        # Carregar metrics e insights
        with open(self.metrics_json, encoding="utf-8") as f:
            metrics = json.load(f)
        
        with open(self.insights_json, encoding="utf-8") as f:
            insights_data = json.load(f)
        
        # Concatenar fontes verificáveis
        fontes_verificaveis = json.dumps(metrics) + json.dumps(insights_data)
        
        # Extrair números do report
        numeros_report = re.findall(r"\d+[.,]?\d*", report_text)
        numeros_total = len(numeros_report)
        numeros_verificados = 0
        
        for num in numeros_report:
            num_normalizado = num.replace(",", ".")
            
            if num_normalizado in fontes_verificaveis or num in fontes_verificaveis:
                numeros_verificados += 1
            else:
                # Variações
                try:
                    val = float(num_normalizado)
                    if str(int(val)) in fontes_verificaveis or f"{val:.1f}" in fontes_verificaveis:
                        numeros_verificados += 1
                except ValueError:
                    pass
        
        pct_verificacao = numeros_verificados / numeros_total * 100 if numeros_total > 0 else 100
        
        resultado = {
            "afirmações_numéricas": int(numeros_total),
            "afirmações_verificáveis": int(numeros_verificados),
            "percentagem_ausência_alucinação": round(pct_verificacao, 2)
        }
        
        print(f"      Ausência alucinação: {pct_verificacao:.1f}% ({numeros_verificados}/{numeros_total})")
        return resultado

    def gerar_relatorio(self, output_path: str):
        """Gera o relatório final de avaliação em JSON."""
        print("\n" + "="*70)
        print("GERANDO RELATÓRIO DE AVALIAÇÃO")
        print("="*70)
        
        relatorio = {
            "timestamp": datetime.now().isoformat(),
            "dataset_avaliado": self.events_csv,
            "tempo_total_execução_s": self.tempo_total,
            
            "tempos_por_módulo": {
                "stitcher_s": self.metricas.get("tempo_stitcher_s", 0),
                "analytics_s": self.metricas.get("tempo_analytics_s", 0),
                "insights_s": self.metricas.get("tempo_insights_s", 0),
                "report_s": self.metricas.get("tempo_report_s", 0),
            },
            
            "métricas": {
                "1_consistência": self.metricas.get("consistencia", {}),
                "2_cobertura": self.metricas.get("cobertura", {}),
                "3_completude": self.metricas.get("completude", {}),
                "4_detecção_anomalias": self.metricas.get("detecao_anomalias", {}),
                "5_precisão_numérica": self.metricas.get("precisao_numerica", {}),
                "6_ausência_alucinação": self.metricas.get("ausencia_alucinacao", {}),
            },
            
            "resumo": self._gerar_resumo(),
            
            "ficheiros_gerados": {
                "journeys": self.journeys_csv,
                "metrics": self.metrics_json,
                "insights": self.insights_json,
                "report": self.report_md,
            }
        }
        
        # Guardar
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(relatorio, f, ensure_ascii=False, indent=2)
        
        print(f"\n Relatório guardado em: {output_path}")
        self._imprimir_resumo(relatorio["resumo"])

    def _gerar_resumo(self) -> dict:
        """Gera um resumo executivo das métricas."""
        consistencia = self.metricas.get("consistencia", {})
        cobertura = self.metricas.get("cobertura", {})
        completude = self.metricas.get("completude", {})
        detecao = self.metricas.get("detecao_anomalias", {})
        precisao = self.metricas.get("precisao_numerica", {})
        alucinacao = self.metricas.get("ausencia_alucinacao", {})
        
        # Pontuação global (média ponderada)
        pesos = {
            "consistencia": 0.25,
            "cobertura": 0.15,
            "completude": 0.15,
            "detecao": 0.20,
            "precisao": 0.15,
            "alucinacao": 0.10,
        }
        
        pontuacao_global = (
            pesos["consistencia"] * consistencia.get("percentagem_consistente", 0) +
            pesos["cobertura"] * cobertura.get("percentagem_cobertura", 0) +
            pesos["completude"] * completude.get("percentagem_completas", 0) +
            pesos["detecao"] * detecao.get("percentagem_detecção", 0) +
            pesos["precisao"] * precisao.get("percentagem_precisão", 0) +
            pesos["alucinacao"] * alucinacao.get("percentagem_ausência_alucinação", 0)
        )
        
        return {
            "pontuação_global": round(pontuacao_global, 2),
            "aprovado_consistência": consistencia.get("aprovado", False),
            "cobertura_pct": cobertura.get("percentagem_cobertura", 0),
            "completude_pct": completude.get("percentagem_completas", 0),
            "detecção_pct": detecao.get("percentagem_detecção", 0),
            "precisão_pct": precisao.get("percentagem_precisão", 0),
            "ausência_alucinação_pct": alucinacao.get("percentagem_ausência_alucinação", 0),
        }

    def _imprimir_resumo(self, resumo: dict):
        """Imprime o resumo no terminal."""
        print("\n" + "="*70)
        print("RESUMO DA AVALIAÇÃO")
        print("="*70)
        print(f"\n  Pontuação Global: {resumo['pontuação_global']:.1f}/100")
        print(f"\n   Consistência:         {'APROVADO' if resumo['aprovado_consistência'] else 'FALHOU'}")
        print(f"   Cobertura:            {resumo['cobertura_pct']:.1f}%")
        print(f"   Completude:           {resumo['completude_pct']:.1f}%")
        print(f"   Deteção Anomalias:    {resumo['detecção_pct']:.1f}%")
        print(f"   Precisão Numérica:    {resumo['precisão_pct']:.1f}%")
        print(f"   Ausência Alucinação:  {resumo['ausência_alucinação_pct']:.1f}%")
        print("\n" + "="*70)

    def avaliar_tudo(self, output_path: str):
        """Pipeline completo de avaliação."""
        try:
            # 1. Executar pipeline
            self.executar_pipeline()
            
            # 2. Avaliar cada métrica
            print("\n" + "="*70)
            print("AVALIAÇÃO DE MÉTRICAS")
            print("="*70)
            
            self.metricas["consistencia"] = self.avaliar_consistencia()
            self.metricas["cobertura"] = self.avaliar_cobertura()
            self.metricas["completude"] = self.avaliar_completude()
            self.metricas["detecao_anomalias"] = self.avaliar_detecao_anomalias()
            self.metricas["precisao_numerica"] = self.avaliar_precisao_numerica()
            self.metricas["ausencia_alucinacao"] = self.avaliar_ausencia_alucinacao()
            
            # 3. Gerar relatório
            self.gerar_relatorio(output_path)
            
            return True
            
        except Exception as e:
            print(f"\n[ERRO] Falha na avaliação: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Harness de avaliação do pipeline completo stitcher→analytics→insights→report"
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Caminho para events_validation.csv (dataset com anomalias injetadas)"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Caminho para evaluation_report.json (output da avaliação)"
    )
    parser.add_argument(
        "--ground-truth",
        help="Caminho opcional para ficheiro JSON com anomalias conhecidas"
    )
    args = parser.parse_args()
    
    # Validar inputs
    if not os.path.exists(args.data):
        print(f"[ERRO] Ficheiro não encontrado: {args.data}")
        return 1
    
    # Executar avaliação
    evaluator = PipelineEvaluator(args.data, args.ground_truth)
    sucesso = evaluator.avaliar_tudo(args.output)
    
    return 0 if sucesso else 1


if __name__ == "__main__":
    exit(main())
