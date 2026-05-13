import json
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import networkx as nx

# --- IMPORTAÇÃO DA TUA LÓGICA DO TP1 ---
# Certifica-te que o ficheiro tp1.py está na mesma pasta
from tp1 import Pessoa, Mapa

MAX_HISTORICO = 5

class VisualizadorTrajetorias:
    def __init__(self, root):
        self.root = root
        self.root.title("Retail Intelligence - Analisador de Trajetórias (Baseado em TP1)")
        self.root.geometry("1300x800")

        self.historico_rastos = {} 
        self.cores_pessoas = {}
        self.historico_ui_eventos = []  # Lista de dicts {acao, detalhes} dos últimos N eventos

        try:
            with open("zones.json", "r", encoding="utf-8") as f:
                self.info_zonas = json.load(f)
            
            self.df_eventos = pd.read_csv("events.csv", dtype={
                "event_id": "str",
                "timestamp": "str",
                "zone_id": "category",
                "event_type": "category",
                "duration_s": "int32",
                "gender": "category",
                "age_range": "category"
            })
            
            self.df_eventos["timestamp"] = pd.to_datetime(self.df_eventos["timestamp"], format='mixed')
            
            self.loja = Mapa(self.info_zonas["zones"])
            
            self.event_iterator = self.df_eventos.itertuples(index=True, name="Evento")
            self.contador_id = 1
            self.G = nx.Graph()
            self.build_graph()
            self.setup_ui()
            self.atualizar_grafo()
            
        except Exception as e:
            messagebox.showerror("Erro Fatal", f"Erro ao carregar ficheiros ou inicializar a lógica:\n{e}")
            self.root.destroy()
            return

    def build_graph(self):
        """Constrói a estrutura visual do grafo baseada no JSON."""
        for zone_id, data in self.info_zonas["zones"].items():
            self.G.add_node(zone_id)
            for adj in data.get("adjacent", []):
                self.G.add_edge(zone_id, adj)
        
        try:
            self.pos = nx.kamada_kawai_layout(self.G)
        except Exception as e:
            print(f"Aviso ao gerar layout: {e}. A usar spring_layout alternativo.")
            self.pos = nx.spring_layout(self.G, seed=42)
        
        self.pos = nx.kamada_kawai_layout(self.G)

    def get_cor_pessoa(self, pid):
        """Gera e guarda uma cor única e distinguível para cada pessoa."""
        if pid not in self.cores_pessoas:
            cmap = cm.get_cmap('tab20')
            self.cores_pessoas[pid] = mcolors.to_hex(cmap((pid * 5) % 20))
        return self.cores_pessoas[pid]

    def limpar_rastos_inativos(self):
        """Remove rastos de pessoas que já não estão ativas na loja."""
        pessoas_ativas = set()
        for zona in self.loja.mapa.values():
            pessoas_ativas.update(zona["pessoas"].keys())
        self.historico_rastos = {pid: rastos for pid, rastos in self.historico_rastos.items() if pid in pessoas_ativas}

    def setup_ui(self):
        """Configura os elementos da interface Tkinter."""
        # Painel Lateral
        self.frame_esq = ttk.Frame(self.root, width=320)
        self.frame_esq.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        self.frame_esq.pack_propagate(False)

        self.btn_next = ttk.Button(self.frame_esq, text="PRÓXIMO EVENTO ➔", command=self.process_next)
        self.btn_next.pack(side=tk.TOP, pady=10, fill=tk.X)

        # ── Evento Atual ──────────────────────────────────────────
        frame_atual = ttk.LabelFrame(self.frame_esq, text="EVENTO ATUAL")
        frame_atual.pack(fill=tk.X, pady=(0, 6))

        self.lbl_info = tk.Label(frame_atual, text="Clique para iniciar o processamento",
                                 justify=tk.LEFT, font=("Segoe UI", 10, "bold"),
                                 wraplength=280, fg="#333")
        self.lbl_info.pack(fill=tk.X, padx=4, pady=(4, 0))

        self.lbl_detalhes = tk.Label(frame_atual, text="", justify=tk.LEFT,
                                     font=("Consolas", 9), wraplength=280, anchor="nw")
        self.lbl_detalhes.pack(fill=tk.X, padx=4, pady=(0, 4))

        # ── Histórico dos últimos N eventos ───────────────────────
        ttk.Separator(self.frame_esq, orient="horizontal").pack(fill=tk.X, pady=4)
        tk.Label(self.frame_esq, text=f"HISTÓRICO (últimos {MAX_HISTORICO})",
                 font=("Segoe UI", 9, "bold"), fg="#555").pack(anchor="w")

        self.cards_historico = []  # lista de (frame, lbl_acao, lbl_detalhes)
        for i in range(MAX_HISTORICO):
            bg = "#f5f5f5" if i % 2 == 0 else "#ebebeb"
            card = tk.Frame(self.frame_esq, bg=bg, bd=1, relief="solid")
            card.pack(fill=tk.X, pady=2, padx=2)

            lbl_a = tk.Label(card, text="", justify=tk.LEFT,
                             font=("Segoe UI", 8, "bold"), wraplength=270,
                             fg="#666", bg=bg, anchor="w")
            lbl_a.pack(fill=tk.X, padx=4, pady=(3, 0))

            lbl_d = tk.Label(card, text="", justify=tk.LEFT,
                             font=("Consolas", 8), wraplength=270,
                             fg="#888", bg=bg, anchor="nw")
            lbl_d.pack(fill=tk.X, padx=4, pady=(0, 3))

            self.cards_historico.append((card, lbl_a, lbl_d))

        # Painel Central (Grafo)
        self.frame_graph = ttk.LabelFrame(self.root, text="Fluxo em Tempo Real")
        self.frame_graph.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.fig, self.ax = plt.subplots(figsize=(8, 6))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.frame_graph)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Painel Inferior (Log)
        self.txt_log = tk.Text(self.root, height=10, font=("Consolas", 10), bg="#1e1e1e", fg="#00ff00")
        self.txt_log.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

    def atualizar_cards_historico(self):
        """Actualiza os cards do histórico com os eventos mais recentes."""
        for i, (card, lbl_a, lbl_d) in enumerate(self.cards_historico):
            if i < len(self.historico_ui_eventos):
                entrada = self.historico_ui_eventos[i]
                lbl_a.config(text=f"↩ {entrada['acao']}")
                lbl_d.config(text=entrada['detalhes'])
            else:
                lbl_a.config(text="")
                lbl_d.config(text="")

    def process_next(self):
        """Executa a lógica do TP1 para o próximo evento do CSV."""
        try:
            evento = next(self.event_iterator)
        except StopIteration:
            messagebox.showinfo("Fim", "Todos os eventos foram processados.")
            return

        # 1. Limpeza de inativos
        self.loja.limpar_inativos(evento.timestamp)
        self.limpar_rastos_inativos()
        
        zona_atual = self.loja.mapa[evento.zone_id]
        pessoa_evento = Pessoa(evento)
        pessoa_corr = (None, None)
        acao = "Ignorado"

        # 2. Lógica de Associação
        if evento.event_type == "entry":
            if evento.zone_id in {"Z_E1", "Z_E2"}:
                pessoa_corr = (self.contador_id, None)
                self.contador_id += 1
                acao = f"NOVA ENTRADA (ID: {pessoa_corr[0]:04d})"
            else:
                pessoa_corr = self.loja.procurar_pessoa_arredores(evento)
                if pessoa_corr[0] is not None:
                    acao = f"MOVIMENTO (ID: {pessoa_corr[0]:04d})"
        
        elif evento.event_type in ["linger", "exit"]:
            maior_score = 0
            for p_id, p_obj in zona_atual["pessoas"].items():
                score = self.loja.calc_corresp_pessoa(pessoa_evento, p_obj)
                if score > maior_score:
                    maior_score = score
                    pessoa_corr = (p_id, p_obj)
            
            if pessoa_corr[0] is not None:
                acao = f"ATUALIZAÇÃO {evento.event_type.upper()} (ID: {pessoa_corr[0]:04d})"

        # 3. Atualização do Estado Interno do Mapa e Histórico
        if pessoa_corr[0] is not None:
            pid = pessoa_corr[0]
            
            if pessoa_corr[1] is not None:
                last_zone_id = pessoa_corr[1].last_zone
                if pid in self.loja.mapa[last_zone_id]["pessoas"]:
                    self.loja.mapa[last_zone_id]["pessoas"].pop(pid)
                    if not self.loja.mapa[last_zone_id]["pessoas"]:
                        self.loja.zonas_ativas.pop(last_zone_id, None)

            zona_atual["pessoas"][pid] = Pessoa(evento, pessoa_corr[1])
            self.loja.zonas_ativas[evento.zone_id] = zona_atual

            if pid not in self.historico_rastos:
                self.historico_rastos[pid] = [evento.zone_id]
            else:
                if self.historico_rastos[pid][0] != evento.zone_id:
                    self.historico_rastos[pid].insert(0, evento.zone_id)
                    self.historico_rastos[pid] = self.historico_rastos[pid][:4]

        else:
            acao = "NÃO ASSOCIADO (0000)"

        # 4. Atualizar UI — guardar no histórico ANTES de atualizar os labels
        detalhes = (f"Timestamp: {evento.timestamp}\n"
                    f"Zona: {evento.zone_id}\n"
                    f"Tipo: {evento.event_type}\n"
                    f"Perfil: {evento.gender}, {evento.age_range}\n"
                    f"Duração: {evento.duration_s}s")

        self.historico_ui_eventos.insert(0, {"acao": acao, "detalhes": detalhes})
        self.historico_ui_eventos = self.historico_ui_eventos[:MAX_HISTORICO]

        self.lbl_info.config(text=f"EVENTO ATUAL: {acao}")
        self.lbl_detalhes.config(text=detalhes)
        self.atualizar_cards_historico()
        
        self.update_log()
        self.atualizar_grafo()

    def update_log(self):
        """Mostra quem está em cada zona no terminal inferior."""
        self.txt_log.delete(1.0, tk.END)
        log = "OCUPAÇÃO ATUAL DAS ZONAS:\n"
        log += "-" * 30 + "\n"
        for zid, zdata in self.loja.mapa.items():
            if zdata["pessoas"]:
                pids = [f"P_{pid:04d}" for pid in zdata["pessoas"].keys()]
                log += f"{zid:8} : {', '.join(pids)}\n"
        self.txt_log.insert(tk.END, log)

    def atualizar_grafo(self):
        """Desenha o mapa com a hierarquia de bolas."""
        self.ax.clear()
        
        nx.draw_networkx_edges(self.G, self.pos, ax=self.ax, edge_color='#bdbdbd', width=1.5)
        nx.draw_networkx_nodes(self.G, self.pos, ax=self.ax, node_color='white', 
                               edgecolors='#bdbdbd', node_size=1800)

        config_tamanhos = [1500, 900, 500, 200]
        
        for pid, rasto_zonas in self.historico_rastos.items():
            cor_pessoa = self.get_cor_pessoa(pid)
            for i, zona_id in enumerate(rasto_zonas):
                if zona_id in self.pos:
                    x, y = self.pos[zona_id]
                    self.ax.scatter(x, y, s=config_tamanhos[i], c=cor_pessoa,
                                    edgecolors='black', alpha=0.8, zorder=2 + i)

        nx.draw_networkx_labels(self.G, self.pos, ax=self.ax, font_size=8, font_weight='bold')

        self.ax.set_title("Retail Intelligence - Fluxo Dinâmico", pad=20)
        self.ax.axis("off")
        self.canvas.draw()

if __name__ == "__main__":
    root = tk.Tk()
    app = VisualizadorTrajetorias(root)
    root.mainloop()