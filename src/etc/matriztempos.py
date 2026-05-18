import heapq
from itertools import combinations

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
