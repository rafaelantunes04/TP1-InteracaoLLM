import json
import pandas as pd
import heapq

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
        

class Mapa:
    def __init__(self, zonas: dict):
        # Importar zonas e adicionar lista pessoas por zona
        self.mapa = zonas

        for zone_name in self.mapa.keys():
            self.mapa[zone_name]["pessoas"]: dict[int, Pessoa] = dict() # type: ignore
        

        # Matriz dos tempos entre zonas
        self.tempos = {}

        for origem in self.mapa.keys():
            self.tempos[origem] = {}

            for destino in self.mapa.keys():
                self.tempos[origem][destino] = self.dijkstra(origem, destino)


        self.zonas_ativas: dict[str, dict] = dict()
        """
        Lista de Nodes que têm la alguem

        key: string (id_zona)
        item: dict (obj_zona)

        Isto vai servir para acessar fácilmente para tirar de la pessoas,
         cujas, ATÉ entrarem noutra zona com sucesso, ficam aqui.

        """
    
    def precalcular_tempos(self):
        tempos = {}

        for origem in self.mapa.keys():
            tempos[origem] = {}

            for destino in self.mapa.keys():
                tempos[origem][destino] = self.dijkstra(origem, destino)

        return tempos

    
    def dijkstra(self, origem: str, destino: str) -> float:
        """
        Calcula o menor tempo de caminhada entre duas zonas usando o
         algoritmo de Dijkstra.
        """
        # Mesmo ponto
        if origem == destino:
            return 0

        # (tempo_acumulado, zona)
        fila_prioridade = [(0, origem)]

        # Zonas já processadas
        zonas_visitadas = set()

        while fila_prioridade:

            # Zona com menor custo atual
            tempo_atual, zona_atual = heapq.heappop(fila_prioridade)

            # Ignorar se já foi visitada
            if zona_atual in zonas_visitadas:
                continue

            zonas_visitadas.add(zona_atual)

            # Encontrou o destino
            if zona_atual == destino:
                return tempo_atual

            # Explorar vizinhos
            vizinhos = self.mapa[zona_atual].get("walk_seconds", {})
            for zona_vizinha, tempo_caminhada in vizinhos.items():

                if zona_vizinha in zonas_visitadas:
                    continue

                novo_tempo = tempo_atual + tempo_caminhada

                heapq.heappush(
                    fila_prioridade,
                    (novo_tempo, zona_vizinha)
                )

        # Não existe caminho possível
        return float("inf")


    def diferenca_tempo(self, pessoa_evento: Pessoa , pessoa: Pessoa) -> int:
        """
        Calcula a diferença do tempo entre duas pessoas, dando um 
         score de 0-30 do quão perto do caminho original percorrido
         está o esse tempo
        """

        #   Difereça entre timestamps
        timestamp_evento = pessoa_evento.last_timestamp
        timestamp_pessoa = pessoa.last_timestamp

        timestamp_diff = abs((timestamp_evento - timestamp_pessoa).total_seconds())
        
        #   Tempo que demora entre as duas zonas (somando percursos intermédios)
        base_time = self.tempos[pessoa.last_zone][pessoa_evento.last_zone]
        
        # Se for infinito, significa que não há caminho possível entre as zonas
        if base_time == float('inf'):
            return 0 
        
        #   Diferença do esperado
        erro = abs(timestamp_diff - base_time)

        #   score máximo = 30
        #   tolerância máxima = 5 segundos
        MAX_SCORE = 30
        MAX_ERRO = 3

        score = int(max(0, MAX_SCORE * (1 - abs(erro) / MAX_ERRO)))

        return score

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
                    horario_saida = horario_entrada + timedelta(seconds=pessoa_evento.linger_time)

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
                    return 30

        # Certificação o genero 
        if pessoa_evento.genero == pessoa.genero:
            pontuacao_total += 20
        
        # Certificação o idade
        if pessoa_evento.idade == pessoa.idade:
            pontuacao_total += 20


        return pontuacao_total

    def procurar_pessoa_arredores(self, evento: dict, saltos_maximos=2) -> tuple[int, Pessoa]:
        """
        Procura a pessoa mais legível à do evento com base nas zonas que
        rodeiam a zona do evento, até um determinado número de saltos (profundidade).
        """
        zona_atual_id = evento.zone_id
        pessoa_evento = Pessoa(evento)
        pessoa_corr = None, None
        maior_score = 0

        # 1. Obter zonas candidatas (Busca em Largura / BFS)
        zonas_candidatas = set()
        fila = [(zona_atual_id, 0)] # Tuplo: (id_da_zona, distancia_em_saltos)
        visitados = set([zona_atual_id])

        while fila:
            zona_id, saltos = fila.pop(0)
            
            # Adiciona a zona atual às candidatas (exceto a zona onde o evento ocorreu)
            if saltos > 0:
                zonas_candidatas.add(zona_id)
            
            # Se ainda não atingimos o limite de saltos, expandimos para os vizinhos
            if saltos < saltos_maximos:
                for vizinho in self.mapa[zona_id].get("adjacent", []):
                    if vizinho not in visitados:
                        visitados.add(vizinho)
                        fila.append((vizinho, saltos + 1))

        # 2. Procurar por pessoas nas zonas candidatas
        for nome_zona in zonas_candidatas:
            # Zona não tem ninguém ativo, avançar
            if nome_zona not in self.zonas_ativas:
                continue

            for id, pessoa in self.mapa[nome_zona]["pessoas"].items():
                score_pessoa = self.calc_corresp_pessoa(pessoa_evento, pessoa)
                if score_pessoa > maior_score:
                    maior_score = score_pessoa
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
        

        # Mudar a pessoas de zona
        loja.mapa[pessoa_corr[1].last_zone]["pessoas"].pop(pessoa_corr[0])
        if len(loja.mapa[pessoa_corr[1].last_zone]["pessoas"]) == 0:
            loja.zonas_ativas.pop(pessoa_corr[1].last_zone)
        
        zona_atual["pessoas"][pessoa_corr[0]] = Pessoa(evento, pessoa_corr[1])

        # Adicionar id à lista
        ids_atribuidos.append(pessoa_corr[0])

        

        

