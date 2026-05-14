import json
import pandas as pd
import heapq
from itertools import combinations

from datetime import datetime, timedelta


class Pessoa:
    def __init__(self, evento: dict, last_pessoa = None):
        self.last_pessoa = last_pessoa

        self.last_timestamp = evento.timestamp
        self.last_zone = evento.zone_id
        self.last_event = evento.event_type
        self.genero = evento.gender
        self.idade = evento.age_range
        self.linger_time = evento.duration_s
        

class MatrizTempos:
    """
    Classe responsável por calcular e armazenar os tempos de deslocação 
     entre zonas, otimizando para não recalcular trajetos simétricos
    """
    def __init__(self, mapa_zonas: dict):
        self.mapa_zonas = mapa_zonas
        self._tempos = {}
        self._precalcular()


    def _precalcular(self):
        """
        Calcula e armazena o tempo mínimo entre todos os pares de zonas,
         utilizando uma chave ordenada para garantir que o trajeto seja tratado 
         como simétrico (A para B é igual a B para A) e evitar cálculos duplicados
        """
        zonas = list(self.mapa_zonas.keys())

        # Distância de uma zona para si mesma
        for zona in zonas:
            self._tempos[(zona, zona)] = 0

        # Calcular combinações únicas de pares de zonas
        for origem, destino in combinations(zonas, 2):
            tempo = self._dijkstra(origem, destino)
            
            # Usa-se um tuplo ordenado como chave para garantir simetria
            chave = tuple(sorted((origem, destino)))
            self._tempos[chave] = tempo


    def _dijkstra(self, origem: str, destino: str) -> int:
        fila_prioridade = [(0, origem)]
        zonas_visitadas = set()

        while fila_prioridade:
            tempo_atual, zona_atual = heapq.heappop(fila_prioridade)

            if zona_atual in zonas_visitadas:
                continue

            zonas_visitadas.add(zona_atual)

            if zona_atual == destino:
                return tempo_atual

            vizinhos = self.mapa_zonas[zona_atual]["walk_seconds"].items()
            for zona_vizinha, tempo_caminhada in vizinhos:
                if zona_vizinha not in zonas_visitadas:
                    novo_tempo = tempo_atual + tempo_caminhada
                    heapq.heappush(fila_prioridade, (novo_tempo, zona_vizinha))

        raise ValueError(f"Mapa inválido: não existe ligação possível entre {origem} e {destino}.")


    def get_tempo(self, origem: str, destino: str) -> int:
        chave = tuple(sorted((origem, destino)))
        return self._tempos[chave]


class Mapa:
    def __init__(self, zonas: dict):
        # Importar zonas e adicionar lista pessoas por zona
        self.mapa = zonas

        for zone_name in self.mapa.keys():
            self.mapa[zone_name]["pessoas"]: dict[int, Pessoa] = dict() # type: ignore
        

        # Matriz dos tempos entre zonas
        self.matriz_tempos = MatrizTempos(self.mapa)


        # Zonas Ativas        
        self.zonas_ativas: dict[str, dict] = dict()
        """
        Lista de Nodes que têm la alguem

        key: string (id_zona)
        item: dict (obj_zona)

        Isto vai servir para acessar fácilmente para tirar de la pessoas,
         cujas, ATÉ entrarem noutra zona com sucesso, ficam aqui.

        """


    def diferenca_tempo(self, pessoa_evento: Pessoa , pessoa: Pessoa) -> int:
        """
        Calcula a diferença do tempo entre duas pessoas, dando um 
         score de 0-40 do quão perto do caminho original percorrido
         está o esse tempo, tendo uma tolerância de 120s de atraso
        """
        # Score maximo possivel
        MAX_SCORE = 40

        # Segundos de tolerância
        MAX_EXTRA = 120

        # Difereça entre timestamps
        timestamp_evento = pessoa_evento.last_timestamp
        timestamp_pessoa = pessoa.last_timestamp

        timestamp_diff = abs((timestamp_evento - timestamp_pessoa).total_seconds())
        
        # Tempo que demora entre as duas zonas
        base_time = self.matriz_tempos.get_tempo(pessoa.last_zone, pessoa_evento.last_zone)
        
        # Chegou antes do tempo mínimo de caminhada
        if timestamp_diff < base_time:
            return 5

        # Chegou mais devagar — sempre aceitável, penaliza progressivamente
        extra_time = timestamp_diff - base_time

        

        return int(max(0, MAX_SCORE * (1 - extra_time / MAX_EXTRA)))

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

                    if horario_saida == pessoa_evento.last_timestamp:
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
                diff_tempo = self.diferenca_tempo(pessoa_evento, pessoa)
                if diff_tempo == 0:
                    return 0
                
                pontuacao_total += diff_tempo

        #   Caso o destino seja dar linger
            case "linger":
                if pessoa.last_event == "linger":
                    return 0

                if pessoa_evento.last_zone == pessoa.last_zone:
                    pontuacao_total += 30

        # Certificação o genero 
        if pessoa_evento.genero == pessoa.genero:
            pontuacao_total += 20
        
        # Certificação o idade
        if pessoa_evento.idade == pessoa.idade:
            pontuacao_total += 20


        return pontuacao_total

    def procurar_pessoa_arredores(self, evento) -> tuple[int, Pessoa]:
        """
        Procura pela pessoa que faz mais sentido para o dado evento,
         sendo as pessoas escolhidas dentro da zonas_ativas.
        
        Ha o intervalo perfeito que é o ceiling que dita que ja encontrou
         a pessoa perfeita a partir do score que vai de 0-100
        """
        INTERVALO_PERFEITO = 95

        pessoa_evento = Pessoa(evento)
        pessoa_corr = None, None
        maior_score = 0

        for nome_zona, zona in self.zonas_ativas.items():
            if nome_zona == evento.zone_id:
                continue

            for id, pessoa in zona["pessoas"].items():
                score = self.calc_corresp_pessoa(pessoa_evento, pessoa)

                if score >= INTERVALO_PERFEITO:
                    return id, pessoa
            
                if score > maior_score:
                    maior_score = score
                    pessoa_corr = id, pessoa

        return pessoa_corr

    def limpar_inativos(self, timestamp_atual: datetime):
        """
        Remove pessoas que não tiveram eventos nos últimos 5 minutos
        em relação ao timestamp do evento atual.
        """
        limite_segundos = 300
        
        # Usamos list() para evitar erros de "dictionary changed size during iteration"
        for zone_id in list(self.zonas_ativas.keys()):
            zona = self.mapa[zone_id]
            for p_id in list(zona["pessoas"].keys()):
                pessoa = zona["pessoas"][p_id]
                
                diff = (timestamp_atual - pessoa.last_timestamp).total_seconds()
                
                if diff > limite_segundos:
                    # Remove a pessoa da zona
                    zona["pessoas"].pop(p_id)
                    # Opcional: imprimir log ou guardar num histórico de trajetórias finalizadas
            
            # Se a zona ficou vazia, remove das zonas ativas
            if not zona["pessoas"]:
                self.zonas_ativas.pop(zone_id)

if __name__ == "__main__":
    # Import de ficheiros
    with open("zones.json", "r", encoding="utf-8") as f:
        info_zonas: dict[str, dict] = json.load(f)

    df_eventos = pd.read_csv("events.csv", dtype={
        "event_id": "str",
        "timestamp": "str",
        "zone_id": "category",
        "event_type": "category",
        "duration_s": "int32",
        "gender": "category",
        "age_range": "category"
    })
    df_eventos["timestamp"] = pd.to_datetime(df_eventos["timestamp"])

    # Logica
    loja = Mapa(info_zonas["zones"])


    ids_atribuidos = []

    contador_id = 1
    
    for evento in df_eventos.itertuples(index=True, name="Evento"):
        loja.limpar_inativos(evento.timestamp)
        zona_atual = loja.mapa[evento.zone_id]
        pessoa_evento = Pessoa(evento)
        pessoa_corr: tuple[int, Pessoa] = None, None

        if evento.event_type == "entry":
            # Nova pessoa entrou na mapa
            if evento.zone_id in {"Z_E1", "Z_E2"}:
                pessoa_corr = contador_id, None
                contador_id += 1

                # Adicionar Pessoa à respetiva zona
                zona_atual["pessoas"][pessoa_corr[0]] = pessoa_evento
                loja.zonas_ativas[evento.zone_id] = zona_atual
                
                continue
        
            # Entrou noutra zona
            pessoa_corr = loja.procurar_pessoa_arredores(evento)

    
        elif evento.event_type in ["linger", "exit"]:
            maior_score = 0
            for id, pessoa in zona_atual["pessoas"].items():
                score_pessoa = loja.calc_corresp_pessoa(pessoa_evento, pessoa)
                if score_pessoa > maior_score:
                    maior_score = score_pessoa
                    pessoa_corr = id, pessoa

        
        if pessoa_corr == (None, None):
            ids_atribuidos.append(0)
            continue
        

        # Mudar a pessoa de zona
        loja.mapa[pessoa_corr[1].last_zone]["pessoas"].pop(pessoa_corr[0])
        if len(loja.mapa[pessoa_corr[1].last_zone]["pessoas"]) == 0:
            loja.zonas_ativas.pop(pessoa_corr[1].last_zone)
        
        # Caso tenha saido da loja só adicionar aos ids atribuidos e não voltar a adicionar
        if evento.event_type == "exit" and evento.zone_id == "Z_CK":
            ids_atribuidos.append(pessoa_corr[0])
            continue

        zona_atual["pessoas"][pessoa_corr[0]] = Pessoa(evento, pessoa_corr[1])

        # Adicionar id à lista
        ids_atribuidos.append(pessoa_corr[0])

        

        

