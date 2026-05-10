import json
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import networkx as nx

# --- AS TUAS CLASSES DE LÓGICA (Mantidas com correções) ---

class Pessoa:
    def __init__(self, evento, last_pessoa=None):
        self.last_pessoa = last_pessoa
        self.last_timestamp = evento.timestamp
        self.last_zone = evento.zone_id
        self.last_event = evento.event_type
        self.genero = evento.gender
        self.idade = evento.age_range
        self.linger_time = evento.duration_s

class Mapa:
    def __init__(self, zonas: dict):
        self.mapa = zonas
        for zone_name in self.mapa.keys():
            self.mapa[zone_name]["pessoas"] = dict() 
        self.zonas_ativas = dict()

    def diferenca_tempo(self, pessoa_evento: Pessoa, pessoa: Pessoa) -> int:
        timestamp_evento = pessoa_evento.last_timestamp
        timestamp_pessoa = pessoa.last_timestamp
        timestamp_diff = abs((timestamp_evento - timestamp_pessoa).total_seconds())
        try:
            base_time = self.mapa[pessoa.last_zone].get("walk_seconds", {}).get(pessoa_evento.last_zone, 10)
        except KeyError:
            base_time = 10 
        erro = abs(timestamp_diff - base_time)
        return int(max(0, 30 * (1 - abs(erro) / 3)))

    def calc_corresp_pessoa(self, pessoa_evento: Pessoa, pessoa: Pessoa):
        pontuacao_total = 0
        if pessoa_evento.last_event == "exit":
            if pessoa.last_event == "exit": return 0
            pontuacao_total += 30
        elif pessoa_evento.last_event == "entry":
            if pessoa.last_event in ["entry", "linger"]: return 0
            pontuacao_total += self.diferenca_tempo(pessoa_evento, pessoa)
        elif pessoa_evento.last_event == "linger":
            if pessoa_evento.last_zone == pessoa.last_zone: pontuacao_total += 30
        
        if pessoa_evento.genero == pessoa.genero: pontuacao_total += 20
        if pessoa_evento.idade == pessoa.idade: pontuacao_total += 20
        return pontuacao_total

    def procurar_pessoa_arredores(self, evento) -> tuple:
        zona_atual = self.mapa[evento.zone_id]
        pessoa_evento = Pessoa(evento)
        pessoa_corr, maior_score = (None, None), 0
        for nome_zona in zona_atual.get("adjacent", []):
            if nome_zona not in self.zonas_ativas: continue
            for p_id, pessoa in self.mapa[nome_zona]["pessoas"].items():
                score = self.calc_corresp_pessoa(pessoa_evento, pessoa)
                if score > maior_score:
                    maior_score, pessoa_corr = score, (p_id, pessoa)
        return pessoa_corr

    def limpar_inativos(self, timestamp_atual: datetime):
        for zone_id in list(self.zonas_ativas.keys()):
            zona = self.mapa[zone_id]
            for p_id in list(zona["pessoas"].keys()):
                if (timestamp_atual - zona["pessoas"][p_id].last_timestamp).total_seconds() > 300:
                    zona["pessoas"].pop(p_id)
            if not zona["pessoas"]: self.zonas_ativas.pop(zone_id)

# --- INTERFACE GRÁFICA MELHORADA ---

class VisualizadorTrajetorias:
    def __init__(self, root):
        self.root = root
        self.root.title("Retail Intelligence - Analisador de Trajetórias")
        self.root.geometry("1300x800")

        try:
            with open("zones.json", "r", encoding="utf-8") as f:
                self.info_zonas = json.load(f)
            self.df_eventos = pd.read_csv("events.csv")
            self.df_eventos["timestamp"] = pd.to_datetime(self.df_eventos["timestamp"])
            self.loja = Mapa(self.info_zonas["zones"])
        except Exception as e:
            messagebox.showerror("Erro", f"Ficheiros não encontrados:\n{e}")
            self.root.destroy()
            return

        self.event_iterator = self.df_eventos.itertuples(index=True)
        self.contador_id = 1
        self.G = nx.Graph()
        self.build_graph()
        self.setup_ui()
        self.atualizar_grafo()

    def build_graph(self):
        for zone_id, data in self.info_zonas["zones"].items():
            self.G.add_node(zone_id)
            for adj in data.get("adjacent", []):
                self.G.add_edge(zone_id, adj)
        # k=2.0 aumenta a repulsão entre nós para ficarem mais separados
        self.pos = nx.spring_layout(self.G, k=2.5, iterations=100, seed=42)

    def setup_ui(self):
        # Painel Lateral
        self.frame_esq = ttk.Frame(self.root, width=300)
        self.frame_esq.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        self.frame_esq.pack_propagate(False)

        self.btn_next = ttk.Button(self.frame_esq, text="PRÓXIMO EVENTO ➔", command=self.process_next)
        self.btn_next.pack(side=tk.TOP, pady=10, fill=tk.X)

        self.lbl_info = tk.Label(self.frame_esq, text="Clique no botão para iniciar", justify=tk.LEFT, font=("Segoe UI", 10), wraplength=280)
        self.lbl_info.pack(fill=tk.BOTH, expand=True)

        # Painel Central (Grafo)
        self.frame_graph = ttk.LabelFrame(self.root, text="Mapa de Fluxo da Loja")
        self.frame_graph.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.fig, self.ax = plt.subplots(figsize=(8, 6))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.frame_graph)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Painel Inferior (Texto)
        self.txt_log = tk.Text(self.root, height=8, font=("Consolas", 10), bg="#1e1e1e", fg="#00ff00")
        self.txt_log.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

    def process_next(self):
        try:
            evento = next(self.event_iterator)
        except StopIteration:
            messagebox.showinfo("Fim", "Processamento concluído.")
            return

        self.loja.limpar_inativos(evento.timestamp)
        zona_atual = self.loja.mapa[evento.zone_id]
        pessoa_evento = Pessoa(evento)
        pessoa_corr, acao = (None, None), "Não associado"

        # Lógica de associação
        if evento.event_type == "entry":
            if evento.zone_id in {"Z_E1", "Z_E2"}:
                pessoa_corr = (self.contador_id, None)
                self.contador_id += 1
                acao = f"Nova entrada: P_{pessoa_corr[0]:04d}"
            else:
                pessoa_corr = self.loja.procurar_pessoa_arredores(evento)
                if pessoa_corr[0]: acao = f"Movimento: P_{pessoa_corr[0]:04d}"
        
        elif evento.event_type in ["linger", "exit"]:
            maior_score = 0
            for p_id, p_obj in zona_atual["pessoas"].items():
                s = self.loja.calc_corresp_pessoa(pessoa_evento, p_obj)
                if s > maior_score: maior_score, pessoa_corr = s, (p_id, p_obj)
            if pessoa_corr[0]: acao = f"Atualização: P_{pessoa_corr[0]:04d}"

        # Atualizar estado interno
        if pessoa_corr[0]:
            if pessoa_corr[1] and pessoa_corr[1].last_zone in self.loja.mapa:
                if pessoa_corr[0] in self.loja.mapa[pessoa_corr[1].last_zone]["pessoas"]:
                    self.loja.mapa[pessoa_corr[1].last_zone]["pessoas"].pop(pessoa_corr[0])
            
            zona_atual["pessoas"][pessoa_corr[0]] = Pessoa(evento, pessoa_corr[1])
            self.loja.zonas_ativas[evento.zone_id] = zona_atual

        # Atualizar Visualização
        self.lbl_info.config(text=f"ZONA: {evento.zone_id}\nEVENTO: {evento.event_type}\nPERFIL: {evento.gender} {evento.age_range}\n\nRESULTADO:\n{acao}")
        self.update_log()
        self.atualizar_grafo(evento.zone_id)

    def update_log(self):
        self.txt_log.delete(1.0, tk.END)
        log = "ESTADO ATUAL:\n"
        for zid, zdata in self.loja.zonas_ativas.items():
            log += f"{zid}: {[f'P_{pid:04d}' for pid in zdata['pessoas'].keys()]}\n"
        self.txt_log.insert(tk.END, log)

    def atualizar_grafo(self, zona_evento=None):
        self.ax.clear()
        
        # Cores dos nós
        node_colors = []
        for n in self.G.nodes():
            if n == zona_evento: node_colors.append('#ff4444') # Alerta
            elif n in self.loja.zonas_ativas: node_colors.append('#ffbb33') # Com pessoas
            else: node_colors.append('#e0e0e0') # Inativo

        # Cores e larguras das arestas (Caminhos)
        edge_colors = []
        edge_widths = []
        for u, v in self.G.edges():
            # Se ambas as zonas têm pessoas, assumimos um "caminho de fluxo" ativo
            if u in self.loja.zonas_ativas and v in self.loja.zonas_ativas:
                edge_colors.append('#00c851') # Verde
                edge_widths.append(3.0)
            else:
                edge_colors.append('#bdbdbd')
                edge_widths.append(1.0)

        nx.draw(self.G, self.pos, ax=self.ax, with_labels=True, 
                node_color=node_colors, node_size=1000, 
                font_size=8, font_weight='bold',
                edge_color=edge_colors, width=edge_widths)

        self.ax.set_title("Vermelho: Evento Atual | Laranja: Zona com Pessoas | Verde: Caminho Ativo")
        self.canvas.draw()

if __name__ == "__main__":
    root = tk.Tk()
    app = VisualizadorTrajetorias(root)
    root.mainloop()