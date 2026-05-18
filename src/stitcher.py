import json
import pandas as pd
import argparse

from datetime import datetime, timedelta
        
from etc.matriztempos import MatrizTempos
from etc.pessoa import Pessoa


class Mapa:
    # Configuracao de valores
    
    #   Scores
    INTERVALO_PERFEITO = 95 # De 0-100, qual é o threhold em que aceita sem ver mais
    SCORE_MINIMO = 65 # De 0-100, qual é o threshold que não aceita
    
    MAX_SCORE_TEMPO = 40 # Score maximo possível do tempo
    MAX_TEMPO_EXTRA = 120 # Segundos de tolerância após o tempo base

    SCORE_GENERO = 30 # Score do genero
    SCORE_AGE_RANGE = 30 # Score da age range

    INATIVIDADE_MAX_S = 300 # Tempo maximo de inatividade

    ZONAS_ENTRADA_SAIDA = {"Z_E1", "Z_E2"} # Zonas onde se pode entrar/sair
    

    def __init__(self, zonas: dict):
        # Importar zonas e adicionar lista pessoas por zona
        self.mapa = zonas
        for zone_name in self.mapa.keys():
            self.mapa[zone_name]["pessoas"]: dict[int, Pessoa] = dict() # type: ignore

        self.matriz_tempos = MatrizTempos(self.mapa)
        self.zonas_ativas: dict[str, dict] = dict()

        self._contador_id = 1

    
    # --- Gestão de pessoas por zona ---
    
    def adicionar_pessoa(self, pid: int, pessoa: Pessoa, zona_id: str):
        """Regista a pessoa na zona e marca a zona como activa."""
        self.mapa[zona_id]["pessoas"][pid] = pessoa
        self.zonas_ativas[zona_id] = self.mapa[zona_id]

    def remover_pessoa(self, pid: int, zona_id: str):
        """Remove a pessoa da zona; desactiva a zona se ficar vazia."""
        self.mapa[zona_id]["pessoas"].pop(pid, None)
        if not self.mapa[zona_id]["pessoas"]:
            self.zonas_ativas.pop(zona_id, None)
    
    def limpar_inativos(self, timestamp_atual: datetime):
        """
        Remove pessoas que não tiveram atividade real nos últimos 5 minutos.
        Eventos 'linger' não contam como atividade.
        """
        for zone_id in list(self.zonas_ativas.keys()):
            zona = self.mapa[zone_id]

            for p_id in list(zona["pessoas"].keys()):
                pessoa = zona["pessoas"][p_id]

                ultimo_timestamp = pessoa.last_timestamp

                if pessoa.last_event == "linger" and pessoa.last_pessoa is not None:
                    ultimo_timestamp = pessoa.last_pessoa.last_timestamp

                delta = (timestamp_atual - ultimo_timestamp).total_seconds()

                if delta > self.INATIVIDADE_MAX_S:
                    zona["pessoas"].pop(p_id)

            if not zona["pessoas"]:
                self.zonas_ativas.pop(zone_id, None)

    # --- Lógica de saída ---
    
    def e_saida_real(self, pessoa_anterior: Pessoa, evento: dict) -> bool:
        """
        Confirma se a pessoa realmente saiu da loja por ter vindo dos caminhos adjacentes
         a zona de saida e ter dado exit nesta
        """
        if evento.event_type != "exit":
            return False
        
        if evento.zone_id == "Z_CK":
            return True

        if evento.zone_id not in self.ZONAS_ENTRADA_SAIDA:
            return False

        dois_atras = pessoa_anterior.last_pessoa
        if dois_atras is None:
            return False

        adjacentes = self.mapa[evento.zone_id]["walk_seconds"].keys()
        return dois_atras.last_zone in adjacentes

    # --- Pontuacao ---

    def _diff_tempo(self, pessoa_evento: Pessoa , pessoa: Pessoa) -> int:
        """
        Calcula a diferença do tempo entre duas pessoas, dando um 
         score de 0-40 do quão perto do caminho original percorrido
         está o esse tempo, tendo uma tolerância de 120s de atraso
        """
        # Difereça entre timestamps
        timestamp_evento = pessoa_evento.last_timestamp
        timestamp_pessoa = pessoa.last_timestamp

        timestamp_diff = abs((timestamp_evento - timestamp_pessoa).total_seconds())
        
        # Tempo que demora entre as duas zonas
        base_time = self.matriz_tempos.get_tempo(pessoa.last_zone, pessoa_evento.last_zone)
        
        # Chegou antes do tempo mínimo de caminhada
        if timestamp_diff < base_time:
            if timestamp_diff >= base_time * 0.8:
                return self.MAX_SCORE_TEMPO - 5
            return 5

        # Calculo da tolerancia
        extra_time = timestamp_diff - base_time

        return int(max(0, self.MAX_SCORE_TEMPO * (1 - extra_time / self.MAX_TEMPO_EXTRA)))

    def calc_corresp_pessoa(self, pessoa_evento: Pessoa , pessoa: Pessoa):
        """
        Devolve um valor de 0-100 do quão é provavel ser essa pessoa

        Peso Tempo/Linger: 40 pontos
        Peso Genero: 30 pontos
        Peso Idade: 30 pontos
        """
        pontuacao_total = 0
        

        # Avaliar transição de eventos
        match pessoa_evento.last_event:

        #   Caso o destino seja saír
            case "exit":
                if pessoa.last_event == "exit":
                    return 0
                
                # Certificação caso seja linger
                if pessoa.last_event == "linger":
                    horario_entrada = pessoa.last_pessoa.last_timestamp
                    horario_saida = horario_entrada + timedelta(seconds=pessoa.linger_time)

                    if abs((horario_saida - pessoa_evento.last_timestamp).total_seconds()) <= 3:
                        pontuacao_total += 30
                else:
                    pontuacao_total += 30

        #   Caso o destino seja entrar
            case "entry":
                if pessoa.last_event == "entry":
                    return 0
            
                if pessoa.last_event == "linger":
                    return 0

                # Certificação tempo entre zonas
                diff_tempo = self._diff_tempo(pessoa_evento, pessoa)
                if diff_tempo == 0:
                    return 0
                
                pontuacao_total += diff_tempo

        #   Caso o destino seja dar linger
            case "linger":
                if pessoa.last_event == "linger":
                    return 0

                if pessoa_evento.last_zone == pessoa.last_zone:
                    pontuacao_total += 30
                else:
                    return 0

        # Certificação o genero 
        if pessoa_evento.genero == pessoa.genero:
            pontuacao_total += self.SCORE_GENERO
        
        # Certificação o idade
        if pessoa_evento.idade == pessoa.idade:
            pontuacao_total += self.SCORE_AGE_RANGE


        return pontuacao_total

    def procurar_pessoa_arredores(self, evento) -> tuple[int, Pessoa]:
        """
        Procura pela pessoa que faz mais sentido para o dado evento,
         sendo as pessoas escolhidas dentro da zonas_ativas.
        
        Ha o intervalo perfeito que é o ceiling que dita que ja encontrou
         a pessoa perfeita a partir do score que vai de 0-100
        """
        pessoa_evento = Pessoa(evento)
        pessoa_corr = None, None
        maior_score = 0

        for nome_zona, zona in self.zonas_ativas.items():
            if nome_zona == evento.zone_id:
                continue

            for p_id, pessoa in zona["pessoas"].items():
                score = self.calc_corresp_pessoa(pessoa_evento, pessoa)

                if score >= self.INTERVALO_PERFEITO:
                    return p_id, pessoa
            
                if score > maior_score:
                    maior_score = score
                    pessoa_corr = p_id, pessoa
        
        if maior_score < self.SCORE_MINIMO:
            return None, None

        return pessoa_corr

    # --- Pipeline principal ---

    def processar_evento(self, evento) -> int:
        """
        Processa um único evento e devolve o person_id atribuído
         (0 se o evento não foi associado a nenhuma pessoa).
        """
        self.limpar_inativos(evento.timestamp)
        pessoa_corr: tuple[int | None, Pessoa | None] = (None, None)

        # --- Entrada numa zona ---
        if evento.event_type == "entry":
            pessoa_corr = self.procurar_pessoa_arredores(evento)

            # Nova pessoa a entrar pela primeira vez na loja
            if evento.zone_id in self.ZONAS_ENTRADA_SAIDA and pessoa_corr == (None, None):
                self.adicionar_pessoa(self._contador_id, Pessoa(evento), evento.zone_id)
                pid = self._contador_id
                self._contador_id += 1
                return pid

        # --- Permanência ou saída de uma zona ---
        elif evento.event_type in ("linger", "exit"):
            pessoa_evento = Pessoa(evento)
            maior_score = 0

            for p_id, pessoa in self.mapa[evento.zone_id]["pessoas"].items():
                score = self.calc_corresp_pessoa(pessoa_evento, pessoa)
                if score > maior_score:
                    maior_score = score
                    pessoa_corr = p_id, pessoa

        # Nenhuma correspondência encontrada
        if pessoa_corr == (None, None):
            return 0

        p_id_corr, pessoa_anterior = pessoa_corr
        self.remover_pessoa(p_id_corr, pessoa_anterior.last_zone)

        # Pessoa saiu da loja
        if self.e_saida_real(pessoa_anterior, evento):
            return p_id_corr

        # Atualiza estado da pessoa na nova zona
        self.adicionar_pessoa(p_id_corr, Pessoa(evento, pessoa_anterior), evento.zone_id)
        return p_id_corr

    def processar_eventos(self, df_eventos: pd.DataFrame) -> list[int]:
        """Processa todos os eventos e devolve a lista de person_id paralela ao DataFrame."""
        lista_id = []
        for evento in df_eventos.itertuples(index=True, name="Evento"):
            lista_id.append(self.processar_evento(evento))

        return lista_id


# Construção do journeys.csv

def construir_journeys(df_eventos: pd.DataFrame, ids_atribuidos: list[int]) -> pd.DataFrame:
    """
    A partir do stream de eventos anotado com person_id, reconstrói as visitas
     por zona: uma linha por (pessoa × zona), com entry_time, exit_time e dwell_s.
    """
    df = df_eventos.copy()
    df["person_id"] = ids_atribuidos
    df = df[df["person_id"] != 0]

    journeys = []

    for pid, grupo in df.groupby("person_id", sort=False):
        entry_time = None
        zone_id    = None
        dwell_s    = 0
        gender     = None
        age_range  = None

        for row in grupo.itertuples():
            if row.event_type == "entry":
                entry_time = row.timestamp
                zone_id    = row.zone_id
                dwell_s    = 0
                gender     = row.gender
                age_range  = row.age_range

            elif row.event_type == "linger" and zone_id is not None:
                dwell_s = row.duration_s

            elif row.event_type == "exit" and zone_id is not None:
                journeys.append({
                    "person_id":   f"P_{pid:04d}",
                    "zone_id":     zone_id,
                    "entry_time":  entry_time,
                    "exit_time":   row.timestamp,
                    "dwell_s":     dwell_s,
                    "gender":      gender,
                    "age_range":   age_range,
                    "visit_date":  entry_time.date(),
                    "hour_of_day": entry_time.hour,
                })
                zone_id    = None
                entry_time = None
                dwell_s    = 0

    return pd.DataFrame(journeys)


# Main

def main():
    parser = argparse.ArgumentParser(description="Reconstrói trajectórias individuais a partir de eventos anónimos.")
    parser.add_argument("--input",  required=True, help="Caminho para events.csv")
    parser.add_argument("--output", required=True, help="Caminho para journeys.csv")
    parser.add_argument("--zones",  default="data/zones.json", help="Caminho para zones.json")
    args = parser.parse_args()

    with open(args.zones, "r", encoding="utf-8") as f:
        info_zonas: dict[str, dict] = json.load(f)

    df_eventos = pd.read_csv(args.input, dtype={
        "event_id":   "str",
        "timestamp":  "str",
        "zone_id":    "category",
        "event_type": "category",
        "duration_s": "int32",
        "gender":     "category",
        "age_range":  "category",
    })

    df_eventos["timestamp"] = pd.to_datetime(df_eventos["timestamp"])

    loja = Mapa(info_zonas["zones"])
    ids_atribuidos = loja.processar_eventos(df_eventos)

    df_journeys = construir_journeys(df_eventos, ids_atribuidos)
    df_journeys.to_csv(args.output, index=False)

    print("Ficheiro journeys.csv Criado com Sucesso")

if __name__ == "__main__":
    main()
