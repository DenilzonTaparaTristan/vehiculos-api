# -*- coding: utf-8 -*-
"""
=====================================================================
  SIMULACIÓN VISUAL — simulacion_visual.py
  Sistema Multi-Agente de Tráfico Urbano — Agente Vehículo

  CONSUME 3 APIs EN VIVO:
    1. Mapas/Catastro (compañero) → https://tecnologia-atkj.onrender.com/api/mapas
    2. Semáforos      (compañero) → https://semaforos.onrender.com/api/semaforos
    3. Vehículos      (nuestra)   → http://127.0.0.1:8001/api/vehiculos

  ───────────────────────────────────────────────────────────────────
  CÓMO EJECUTAR:
  ───────────────────────────────────────────────────────────────────
  1. Terminal 1:  python api_vehiculos.py     (deja esa terminal abierta)
  2. Terminal 2:  python simulacion_visual.py

  Las APIs de mapas y semáforos están en Render: la PRIMERA carga puede
  tardar 20-50 segundos si el servicio estaba "dormido". La ventana
  muestra un mensaje de carga mientras espera.

  CONTROLES:
    Click en un coche  → Tomar el control
    ↑ / W               → Acelerar
    ↓ / S               → Frenar / Reversa
    ← / A                → Girar izquierda en intersección
    → / D                → Girar derecha en intersección
    ESPACIO              → Freno de emergencia
    ESC                  → Salir
=====================================================================
"""

import tkinter as tk
from tkinter import ttk, messagebox
import time
import threading
import random

from vehiculo import (
    VehiculoAgente, construir_carriles, carril_inicio_aleatorio,
    cargar_flota_api, cargar_mapas_api, normalizar_distrito,
    cargar_semaforos_api, sincronizar_estado_api,
    generar_semaforos_fallback, _adaptar_semaforos_a_distrito,
    _completar_semaforos, actualizar_ciclo_semaforos,
    MAX_VEHICULOS_MAPA, TIPOS_VEHICULO, PLANO_FALLBACK,
    API_MAPAS_URL, API_SEMAFOROS_URL, API_VEHICULOS_URL,
)

# ─── Paleta visual ────────────────────────────────────────────────────────────
C_BG      = "#121214"
C_PANEL   = "#0d1117"
C_BORDE   = "#00f0ff"
C_VERDE   = "#00e878"
C_CYAN    = "#00ccff"
C_GRIS    = "#556070"
C_BLAN    = "#d0dce8"
C_ROJO    = "#ff3355"
C_AMAR    = "#ffd040"
C_ASFALTO = "#1e1e24"

PANEL_W = 290
TOTAL_H = 800
MIN_WINDOW_H = 860   # alto mínimo de ventana para que el panel completo quepa
                     # (algunos mapas miden solo 600-800px de alto, insuficiente
                     # para todos los botones del panel lateral)

DISTRITO_ACTIVO = "centro"     # clave del distrito a simular


# ════════════════════════════════════════════════════════════════════════════
#  VENTANA DE CARGA INICIAL (mientras llegan las 3 APIs)
# ════════════════════════════════════════════════════════════════════════════
class VentanaCarga:
    def __init__(self, root):
        self.top = tk.Toplevel(root)
        self.top.title("Conectando con las APIs...")
        self.top.geometry("420x220")
        self.top.configure(bg=C_BG)
        self.top.resizable(False, False)
        self.top.grab_set()

        tk.Label(self.top, text="🚗 SISTEMA MAS — AGENTE VEHÍCULO",
                 bg=C_BG, fg=C_CYAN, font=("Courier New", 12, "bold")).pack(pady=(18, 6))

        self.lbl_mapas = self._fila("Mapas/Catastro", API_MAPAS_URL)
        self.lbl_sem   = self._fila("Semáforos",      API_SEMAFOROS_URL)
        self.lbl_veh   = self._fila("Vehículos (local)", API_VEHICULOS_URL)

        self.lbl_status = tk.Label(
            self.top, text="Conectando… (Render puede tardar ~30s si estaba inactivo)",
            bg=C_BG, fg=C_GRIS, font=("Courier New", 8), wraplength=380
        )
        self.lbl_status.pack(pady=(14, 4))
        self.top.update()

    def _fila(self, nombre, url):
        f = tk.Frame(self.top, bg=C_BG)
        f.pack(fill="x", padx=20, pady=3)
        tk.Label(f, text=f"{nombre}:", bg=C_BG, fg=C_BLAN,
                 font=("Courier New", 9), width=16, anchor="w").pack(side="left")
        lbl = tk.Label(f, text="⏳ esperando...", bg=C_BG, fg=C_AMAR,
                       font=("Courier New", 9))
        lbl.pack(side="left")
        return lbl

    def marcar(self, cual, ok, detalle=""):
        lbl = {"mapas": self.lbl_mapas, "semaforos": self.lbl_sem,
               "vehiculos": self.lbl_veh}[cual]
        if ok:
            lbl.config(text=f"✓ OK {detalle}", fg=C_VERDE)
        else:
            lbl.config(text=f"⚠ fallback {detalle}", fg=C_AMAR)
        self.top.update()

    def cerrar(self):
        self.top.destroy()


# ════════════════════════════════════════════════════════════════════════════
#  APLICACIÓN PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════
class SimulacionApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.withdraw()   # ocultar mientras cargamos

        self.tick = 0

        # ── Ventana de carga ─────────────────────────────────────────────────
        self.ventana_carga = VentanaCarga(root)

        # ── Cargar las 3 APIs ────────────────────────────────────────────────
        self._cargar_todo()

        self.ventana_carga.cerrar()
        self.root.deiconify()

        # ── Geometría de la ventana principal ────────────────────────────────
        mapa_w = self.distrito["width"]
        mapa_h = self.distrito["height"]
        total_w = mapa_w + PANEL_W
        total_h = max(mapa_h, MIN_WINDOW_H)   # asegura espacio para todo el panel

        self.root.title(
            f"Sistema MAS — {self.distrito['nombre']}  |  Agente Vehículo "
            f"(Mapas + Semáforos + Vehículos vía API)"
        )
        self.root.geometry(f"{total_w}x{total_h}")
        self.root.configure(bg=C_BG)
        self.root.resizable(True, True)   # el usuario puede agrandar la ventana
        self.root.minsize(total_w, 500)

        # ── Frames ───────────────────────────────────────────────────────────
        self.frame_mapa = tk.Frame(self.root, width=mapa_w, height=mapa_h, bg=C_BG)
        self.frame_mapa.pack(side="left", fill="both")
        self.frame_panel = tk.Frame(self.root, width=PANEL_W, bg=C_PANEL)
        self.frame_panel.pack(side="right", fill="y")
        self.frame_panel.pack_propagate(False)

        # El panel lateral es DESPLAZABLE (scroll): así, aunque el mapa
        # activo sea bajo (600px en 'nuevo58', por ejemplo) o la ventana
        # se achique, siempre se puede llegar a TODOS los botones del
        # panel con la rueda del mouse o la barra de scroll.
        self.panel_canvas = tk.Canvas(self.frame_panel, bg=C_PANEL,
                                      highlightthickness=0, width=PANEL_W)
        self.panel_scrollbar = tk.Scrollbar(self.frame_panel, orient="vertical",
                                            command=self.panel_canvas.yview)
        self.panel_canvas.configure(yscrollcommand=self.panel_scrollbar.set)
        self.panel_canvas.pack(side="left", fill="both", expand=True)
        self.panel_scrollbar.pack(side="right", fill="y")

        self.panel_inner = tk.Frame(self.panel_canvas, bg=C_PANEL)
        self._panel_window_id = self.panel_canvas.create_window(
            (0, 0), window=self.panel_inner, anchor="nw", width=PANEL_W
        )

        def _actualizar_scrollregion(event=None):
            self.panel_canvas.configure(scrollregion=self.panel_canvas.bbox("all"))
        self.panel_inner.bind("<Configure>", _actualizar_scrollregion)

        def _on_mousewheel(event):
            # Windows/Mac mandan delta en múltiplos de 120; Linux usa Button-4/5
            delta = -1 if event.delta > 0 else 1
            self.panel_canvas.yview_scroll(delta, "units")

        def _activar_scroll(event=None):
            self.panel_canvas.bind_all("<MouseWheel>", _on_mousewheel)
            self.panel_canvas.bind_all("<Button-4>", lambda ev: self.panel_canvas.yview_scroll(-1, "units"))
            self.panel_canvas.bind_all("<Button-5>", lambda ev: self.panel_canvas.yview_scroll(1, "units"))

        def _desactivar_scroll(event=None):
            self.panel_canvas.unbind_all("<MouseWheel>")
            self.panel_canvas.unbind_all("<Button-4>")
            self.panel_canvas.unbind_all("<Button-5>")

        self.panel_canvas.bind("<Enter>", _activar_scroll)
        self.panel_canvas.bind("<Leave>", _desactivar_scroll)

        self.canvas = tk.Canvas(self.frame_mapa, width=mapa_w, height=mapa_h,
                                bg=C_BG, highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_click_mapa)

        # ── Vehículos en el mapa ─────────────────────────────────────────────
        self.vehiculos_mapa: list[VehiculoAgente] = []
        self.veh_seleccionado = None

        # ── Panel lateral ────────────────────────────────────────────────────
        self._construir_panel()

        # ── Teclado ──────────────────────────────────────────────────────────
        self.teclas_activas = set()
        self.root.bind("<KeyPress>",   self._on_key_press)
        self.root.bind("<KeyRelease>", self._on_key_release)
        self.root.focus_set()

        # ── Tiempo y sync ────────────────────────────────────────────────────
        self.last_time = time.time()
        self._last_sem_refresh = 0
        self.SEM_REFRESH_INTERVAL = 60.0  # refrescar semáforos cada 60s (no cada 4s)

        self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._sync_thread.start()

        # ── Vehículos iniciales (3 tipos distintos) ──────────────────────────
        self._agregar_vehiculo_inicial("Automóvil")
        self._agregar_vehiculo_inicial("Bus")
        self._agregar_vehiculo_inicial("Motocicleta")

        self.root.after(16, self._tick_loop)

    # ════════════════════════════════════════════════════════════════════════
    #  CARGA INICIAL DE LAS 3 APIs
    # ════════════════════════════════════════════════════════════════════════
    def _cargar_todo(self):
        """
        Carga las 3 APIs en hilos paralelos para no bloquear la UI.
        Render puede tardar hasta 45s en despertar del plan free:
        si cargáramos todo secuencial, la ventana se quedaría congelada
        ese tiempo. Con hilos, el usuario ve el progreso en tiempo real.
        """
        import threading as _th

        # Resultados compartidos entre hilos
        res = {"distritos": None, "semaforos": None, "flota": None}

        def hilo_mapas():
            res["distritos"] = cargar_mapas_api()

        def hilo_semaforos():
            # Usa la misma lógica de reintentos que las demás APIs
            from vehiculo import _get_con_reintentos
            r = _get_con_reintentos(API_SEMAFOROS_URL, "API Semáforos")
            if r is not None:
                try:
                    res["semaforos"] = r.json()
                except Exception:
                    res["semaforos"] = []
            else:
                res["semaforos"] = []

        def hilo_flota():
            res["flota"] = cargar_flota_api()

        # Lanzar los 3 en paralelo
        t_mapas = _th.Thread(target=hilo_mapas,     daemon=True)
        t_sems  = _th.Thread(target=hilo_semaforos, daemon=True)
        t_flota = _th.Thread(target=hilo_flota,     daemon=True)
        t_mapas.start(); t_sems.start(); t_flota.start()

        # Animar la ventana de carga mientras esperamos
        dots = 0
        while t_mapas.is_alive() or t_sems.is_alive() or t_flota.is_alive():
            dots = (dots + 1) % 4
            estado = "Conectando con APIs de Render" + "." * dots + " " * (3 - dots)
            estado += f"\n(Render puede tardar ~40s si el servicio estaba inactivo)"
            try:
                self.ventana_carga.lbl_status.config(text=estado)
                self.ventana_carga.top.update()
            except Exception:
                break
            time.sleep(0.4)

        # ── Procesar resultado de Mapas ──────────────────────────────────────
        distritos = res["distritos"] or [PLANO_FALLBACK]
        self._distritos_raw = distritos   # se guarda para el selector de mapas
        usando_fallback_mapa = (
            len(distritos) == 1 and
            distritos[0].get("clave") == PLANO_FALLBACK["clave"] and
            "config" not in distritos[0]
        )
        encontrado = next(
            (d for d in distritos if d.get("clave") == DISTRITO_ACTIVO),
            distritos[0] if distritos else None
        )
        self.distrito = normalizar_distrito(encontrado) if encontrado else PLANO_FALLBACK
        self.ventana_carga.marcar(
            "mapas", not usando_fallback_mapa,
            detalle=f"({self.distrito['clave']})"
        )
        self.carriles = construir_carriles(self.distrito)

        # ── Procesar resultado de Semáforos ──────────────────────────────────
        todos_sems = res["semaforos"] or []
        mapa_clave = self.distrito["clave"]

        # Filtrar entradas de prueba inválidas ("string", etc.)
        todos_sems = [s for s in todos_sems
                      if isinstance(s, dict) and
                      s.get("mapa_clave") not in ("string", None)]

        # Buscar: exacto → adaptar alternativo → fallback total
        # NOTA: ya no se completa automáticamente. Si faltan intersecciones,
        # el usuario usa el botón "COMPLETAR SEMÁFOROS" cuando quiera.
        exactos = [s for s in todos_sems if s.get("mapa_clave") == mapa_clave]
        if exactos:
            from vehiculo import _fijar_anclas_semaforos
            self.semaforos_remotos    = _fijar_anclas_semaforos(exactos)
            self.semaforos_son_reales = True
            print(f"[API Semáforos] ✓ {len(exactos)} semáforos de API para '{mapa_clave}'")
        else:
            claves = sorted(set(s.get("mapa_clave") for s in todos_sems if s.get("mapa_clave")))
            if claves:
                sem_alt = [s for s in todos_sems if s.get("mapa_clave") == claves[0]]
                self.semaforos_remotos    = _adaptar_semaforos_a_distrito(sem_alt, self.distrito)
                self.semaforos_son_reales = True
                print(f"[API Semáforos] ✓ Usando '{claves[0]}' ({len(self.semaforos_remotos)}) "
                      f"adaptado a '{mapa_clave}'")
            else:
                self.semaforos_remotos    = generar_semaforos_fallback(self.distrito)
                self.semaforos_son_reales = False
                print(f"[API Semáforos] ⚠ Sin datos. Usando {len(self.semaforos_remotos)} locales.")

        self.ventana_carga.marcar(
            "semaforos", self.semaforos_son_reales,
            detalle=f"({len(self.semaforos_remotos)})"
        )

        # ── Procesar resultado de Flota ───────────────────────────────────────
        self.flota_bd = res["flota"] or []
        self.ventana_carga.marcar(
            "vehiculos", len(self.flota_bd) > 0,
            detalle=f"({len(self.flota_bd)})"
        )
        time.sleep(0.5)


    # ── refrescar semáforos remotos periódicamente ───────────────────────────
    def _refrescar_semaforos_si_corresponde(self, now):
        if now - self._last_sem_refresh >= self.SEM_REFRESH_INTERVAL:
            self._last_sem_refresh = now
            threading.Thread(target=self._refrescar_semaforos_bg, daemon=True).start()

    def _refrescar_semaforos_bg(self):
        """Refresca semáforos en hilo separado sin bloquear la simulación."""
        try:
            from vehiculo import _get_con_reintentos
            r = _get_con_reintentos(API_SEMAFOROS_URL, "API Semáforos (refresco)")
            if r is None:
                return
            todos = r.json()
            if not isinstance(todos, list):
                return
            mapa_clave = self.distrito["clave"]
            # Filtrar inválidos
            todos = [s for s in todos if isinstance(s, dict) and
                     s.get("mapa_clave") not in ("string", None)]
            # Buscar exactos o alternativos (sin completar automáticamente)
            filtrados = [s for s in todos if s.get("mapa_clave") == mapa_clave]
            if filtrados:
                from vehiculo import _fijar_anclas_semaforos
                filtrados = _fijar_anclas_semaforos(filtrados)
            else:
                claves = sorted(set(s.get("mapa_clave") for s in todos if s.get("mapa_clave")))
                if claves:
                    alt = [s for s in todos if s.get("mapa_clave") == claves[0]]
                    filtrados = _adaptar_semaforos_a_distrito(alt, self.distrito)
            if filtrados:
                self.semaforos_remotos    = filtrados
                self.semaforos_son_reales = True
            else:
                self.semaforos_remotos    = generar_semaforos_fallback(self.distrito)
                self.semaforos_son_reales = False
        except Exception:
            pass   # silencioso en hilos de refresco

    # ── añadir vehículo inicial ──────────────────────────────────────────────
    def _agregar_vehiculo_inicial(self, categoria: str):
        candidatos = [v for v in self.flota_bd
                      if v.get("categoria") == categoria and not self._ya_en_mapa(v["id"])]
        if not candidatos:
            return
        datos = random.choice(candidatos)
        self._agregar_al_mapa(datos, controlado=False)

    def _ya_en_mapa(self, id_):
        return any(v.datos["id"] == id_ for v in self.vehiculos_mapa)

    def _agregar_al_mapa(self, datos: dict, controlado: bool = False):
        if len(self.vehiculos_mapa) >= MAX_VEHICULOS_MAPA:
            messagebox.showwarning("Límite alcanzado",
                                   f"El mapa ya tiene el máximo de {MAX_VEHICULOS_MAPA} vehículos.")
            return False
        if self._ya_en_mapa(datos["id"]):
            return False

        carril, pos = carril_inicio_aleatorio(self.carriles, self.distrito,
                                              vehiculos_existentes=self.vehiculos_mapa)
        if carril is None:
            return False

        veh = VehiculoAgente(datos, carril, pos, self.distrito, self.carriles,
                             controlado_usuario=controlado)
        if controlado:
            self._desseleccionar_todos()
            self.veh_seleccionado = veh
        self.vehiculos_mapa.append(veh)
        self._actualizar_lista_panel()
        return True

    def _desseleccionar_todos(self):
        for v in self.vehiculos_mapa:
            v.controlado_usuario = False
        self.veh_seleccionado = None

    # ════════════════════════════════════════════════════════════════════════
    #  PANEL LATERAL
    # ════════════════════════════════════════════════════════════════════════
    def _construir_panel(self):
        f = self.panel_inner
        ft = ("Courier New", 9, "bold")
        fn = ("Courier New", 8)

        tk.Label(f, text="══ AGENTE VEHÍCULO ══", bg=C_PANEL, fg=C_CYAN,
                 font=("Courier New", 10, "bold")).pack(pady=(8, 2))
        self.lbl_distrito = tk.Label(f, text=f"Distrito: {self.distrito['nombre']}",
                                     bg=C_PANEL, fg=C_GRIS, font=fn)
        self.lbl_distrito.pack()

        # Estado de las APIs (dinámico — refleja la conexión real, no texto fijo)
        f_api = tk.Frame(f, bg=C_PANEL)
        f_api.pack(fill="x", padx=8, pady=(4, 0))
        self.lbl_api_mapas = tk.Label(f_api, text="🗺 Mapas API: ...", bg=C_PANEL,
                                      fg=C_AMAR, font=("Courier New", 7),
                                      anchor="w", justify="left")
        self.lbl_api_mapas.pack(anchor="w")
        self.lbl_api_sem = tk.Label(f_api, text="🚦 Semáforos API: ...", bg=C_PANEL,
                                    fg=C_AMAR, font=("Courier New", 7),
                                    anchor="w", justify="left")
        self.lbl_api_sem.pack(anchor="w")
        self.lbl_api_veh = tk.Label(f_api, text="🚗 Vehículos API: ...", bg=C_PANEL,
                                    fg=C_AMAR, font=("Courier New", 7),
                                    anchor="w", justify="left")
        self.lbl_api_veh.pack(anchor="w")
        self._actualizar_estado_apis_panel()

        self._sep(f)

        # ── Selector de mapa/distrito ────────────────────────────────────────
        tk.Label(f, text="MAPA / DISTRITO", bg=C_PANEL, fg=C_GRIS,
                 font=ft).pack(anchor="w", padx=10)
        claves_disponibles = [d.get("clave") for d in self._distritos_raw if d.get("clave")]
        if not claves_disponibles:
            claves_disponibles = [self.distrito["clave"]]
        self.var_mapa = tk.StringVar(value=self.distrito["clave"])
        self.combo_mapas = ttk.Combobox(
            f, textvariable=self.var_mapa, values=claves_disponibles,
            state="readonly", width=28, font=fn
        )
        self.combo_mapas.pack(padx=8, pady=3, fill="x")
        tk.Button(f, text="🗺 CAMBIAR MAPA", bg="#2a1a00", fg="#ffaa33", font=ft,
                  relief="flat", cursor="hand2",
                  command=self._btn_cambiar_mapa).pack(padx=8, pady=3, fill="x")

        self._sep(f)

        tk.Label(f, text="EN EL MAPA (máx 10)", bg=C_PANEL, fg=C_GRIS,
                 font=ft).pack(anchor="w", padx=10)
        self.frame_lista = tk.Frame(f, bg=C_PANEL)
        self.frame_lista.pack(fill="x", padx=6, pady=4)

        self._sep(f)

        tk.Label(f, text="AÑADIR VEHÍCULO", bg=C_PANEL, fg=C_GRIS,
                 font=ft).pack(anchor="w", padx=10)

        self.var_tipo = tk.StringVar(value="Todos")
        tipos = ["Todos"] + list(TIPOS_VEHICULO.keys())
        frame_tipo = tk.Frame(f, bg=C_PANEL)
        frame_tipo.pack(fill="x", padx=8, pady=3)
        tk.Label(frame_tipo, text="Tipo:", bg=C_PANEL, fg=C_GRIS, font=fn).pack(side="left")
        combo_tipo = ttk.Combobox(frame_tipo, textvariable=self.var_tipo,
                                  values=tipos, state="readonly", width=13, font=fn)
        combo_tipo.pack(side="left", padx=4)
        combo_tipo.bind("<<ComboboxSelected>>", lambda e: self._actualizar_combo_vehiculos())

        self.var_veh_sel = tk.StringVar()
        self.combo_vehiculos = ttk.Combobox(f, textvariable=self.var_veh_sel,
                                            state="readonly", width=30, font=fn)
        self.combo_vehiculos.pack(padx=8, pady=3, fill="x")
        self._actualizar_combo_vehiculos()

        tk.Button(f, text="＋ AÑADIR AL MAPA", bg="#003322", fg=C_VERDE, font=ft,
                  relief="flat", bd=1, cursor="hand2",
                  command=self._btn_agregar).pack(padx=8, pady=3, fill="x")

        self._sep(f)

        tk.Label(f, text="VEHÍCULO ACTIVO", bg=C_PANEL, fg=C_GRIS,
                 font=ft).pack(anchor="w", padx=10)
        self.lbl_info = tk.Label(
            f, text="Ninguno seleccionado\nHaz click en un coche\npara tomar el control",
            bg=C_PANEL, fg=C_GRIS, font=fn, justify="left", anchor="w"
        )
        self.lbl_info.pack(anchor="w", padx=12, pady=4)

        self._sep(f)

        tk.Label(f, text="CONTROLES", bg=C_PANEL, fg=C_GRIS, font=ft).pack(anchor="w", padx=10)
        for k, v in [("↑/W","Acelerar"), ("↓/S","Frenar"), ("←/→","Girar en nodo"),
                     ("SPACE","Freno emerg."), ("CLICK","Seleccionar coche")]:
            tk.Label(f, text=f"  {k:<7} {v}", bg=C_PANEL, fg=C_GRIS, font=fn,
                     anchor="w").pack(anchor="w", padx=10)

        self._sep(f)

        tk.Label(f, text="TIPOS DE VEHÍCULO", bg=C_PANEL, fg=C_GRIS, font=ft).pack(anchor="w", padx=10)
        for cat, cfg in TIPOS_VEHICULO.items():
            tk.Label(f, text=f"  {cfg['icono']} {cat:<12} {cfg['vel_max']*30:.0f} km/h",
                     bg=C_PANEL, fg=C_BLAN, font=fn, anchor="w").pack(anchor="w", padx=10)

        self._sep(f)
        tk.Button(f, text="✕ QUITAR DEL MAPA", bg="#330011", fg=C_ROJO, font=ft,
                  relief="flat", cursor="hand2",
                  command=self._btn_quitar).pack(padx=8, pady=3, fill="x")
        tk.Button(f, text="↻ REFRESCAR SEMÁFOROS", bg="#002233", fg=C_CYAN, font=ft,
                  relief="flat", cursor="hand2",
                  command=lambda: threading.Thread(
                      target=self._refrescar_semaforos_bg, daemon=True).start()
                  ).pack(padx=8, pady=3, fill="x")
        tk.Button(f, text="＋ COMPLETAR SEMÁFOROS", bg="#1a2200", fg="#ccff33", font=ft,
                  relief="flat", cursor="hand2",
                  command=self._btn_completar_semaforos
                  ).pack(padx=8, pady=3, fill="x")

    def _sep(self, f):
        s = tk.Frame(f, bg=C_BORDE, height=1)
        s.pack(fill="x", padx=8, pady=4)

    def _actualizar_estado_apis_panel(self):
        """Refleja en el panel el estado REAL de cada API, no un texto fijo."""
        if getattr(self, "distrito", None):
            self.lbl_api_mapas.config(
                text=f"🗺 Mapas API: conectado ({self.distrito['clave']})",
                fg=C_VERDE)
        if getattr(self, "semaforos_son_reales", False):
            n = len(self.semaforos_remotos)
            self.lbl_api_sem.config(text=f"🚦 Semáforos API: conectado ({n})", fg=C_VERDE)
        else:
            n = len(getattr(self, "semaforos_remotos", []))
            self.lbl_api_sem.config(
                text=f"🚦 Semáforos: sin datos para\n"
                     f"   '{self.distrito['clave']}' — {n} locales",
                fg=C_AMAR)
        if getattr(self, "flota_bd", None):
            self.lbl_api_veh.config(text=f"🚗 Vehículos API: OK ({len(self.flota_bd)})", fg=C_VERDE)
        else:
            self.lbl_api_veh.config(text="🚗 Vehículos API: usando CSV local", fg=C_AMAR)

    def _actualizar_combo_vehiculos(self):
        tipo_filtro = self.var_tipo.get()
        if tipo_filtro == "Todos":
            disponibles = [v for v in self.flota_bd if not self._ya_en_mapa(v["id"])]
        else:
            disponibles = [v for v in self.flota_bd
                           if v.get("categoria") == tipo_filtro and not self._ya_en_mapa(v["id"])]
        opciones = []
        for v in disponibles:
            icono = TIPOS_VEHICULO.get(v.get("categoria"), {}).get("icono", "?")
            opciones.append(f"{icono} {v['id']:>2}. {v['placa']}  {v.get('categoria')}  {v.get('color')}")
        self.combo_vehiculos["values"] = opciones
        self._disponibles_filtrados = disponibles
        if opciones:
            self.combo_vehiculos.current(0)

    def _actualizar_lista_panel(self):
        for w in self.frame_lista.winfo_children():
            w.destroy()
        fuente = ("Courier New", 7, "bold")
        for veh in self.vehiculos_mapa:
            sel = veh.controlado_usuario
            bg_ = "#001a0e" if sel else C_PANEL
            fg_ = C_VERDE   if sel else C_GRIS
            icon = TIPOS_VEHICULO.get(veh.categoria, {}).get("icono", "?")
            txt  = f"{icon} {veh.datos['placa']}  {veh.categoria[:4]}"
            fila = tk.Frame(self.frame_lista, bg=bg_, bd=1, relief="flat")
            fila.pack(fill="x", pady=1)
            tk.Label(fila, text=txt, bg=bg_, fg=fg_, font=fuente).pack(side="left", padx=4)
            tk.Button(fila, text="◉",
                      bg="#002233" if not sel else "#004422",
                      fg=C_CYAN if not sel else C_VERDE,
                      font=("Courier New", 7), relief="flat", cursor="hand2",
                      command=lambda v=veh: self._tomar_control(v)).pack(side="right", padx=2)

    def _btn_agregar(self):
        if not getattr(self, "_disponibles_filtrados", None):
            messagebox.showinfo("Sin vehículos", "No hay vehículos disponibles para este filtro.")
            return
        idx = self.combo_vehiculos.current()
        if idx < 0 or idx >= len(self._disponibles_filtrados):
            return
        datos = self._disponibles_filtrados[idx]
        if self._agregar_al_mapa(datos, controlado=False):
            self._actualizar_combo_vehiculos()
            self._actualizar_lista_panel()

    def _btn_quitar(self):
        if not self.veh_seleccionado:
            messagebox.showinfo("Sin selección", "Selecciona un vehículo primero.")
            return
        self.vehiculos_mapa.remove(self.veh_seleccionado)
        self.veh_seleccionado = None
        self._actualizar_combo_vehiculos()
        self._actualizar_lista_panel()

    def _btn_completar_semaforos(self):
        """
        Botón independiente de la API: completa localmente los semáforos
        que falten en cualquier intersección del mapa, sin depender de
        que la API del compañero mande más datos. Si la API vuelve a dar
        todos los semáforos en el futuro, este botón simplemente no
        encontrará huecos que rellenar.
        """
        antes = len(self.semaforos_remotos)
        self.semaforos_remotos = _completar_semaforos(self.semaforos_remotos, self.distrito)
        agregados = len(self.semaforos_remotos) - antes
        if agregados > 0:
            messagebox.showinfo(
                "Semáforos completados",
                f"Se agregaron {agregados} semáforos locales "
                f"para cubrir todas las intersecciones."
            )
        else:
            messagebox.showinfo(
                "Sin cambios",
                "Todas las intersecciones ya tienen semáforo."
            )

    def _btn_cambiar_mapa(self):
        """
        Cambia el distrito activo de la simulación a partir de la clave
        elegida en el combobox. La API de mapas expone varios distritos
        (oeste, sur, este, centro, nuevo58, sdsadsa, etc.) — este botón
        permite recorrerlos todos sin reiniciar el programa.
        """
        nueva_clave = self.var_mapa.get()
        if not nueva_clave or nueva_clave == self.distrito["clave"]:
            return

        crudo = next((d for d in self._distritos_raw if d.get("clave") == nueva_clave), None)
        if crudo is None:
            messagebox.showerror("Distrito no encontrado",
                                 f"No se encontró geometría para '{nueva_clave}'.")
            return

        # 1) Normalizar el nuevo distrito y reconstruir carriles
        self.distrito = normalizar_distrito(crudo)
        self.carriles = construir_carriles(self.distrito)

        # 2) Redimensionar ventana/canvas al tamaño real del nuevo mapa
        nuevo_w = self.distrito["width"]
        nuevo_h = self.distrito["height"]
        total_h = max(nuevo_h, MIN_WINDOW_H)
        self.root.geometry(f"{nuevo_w + PANEL_W}x{total_h}")
        self.root.minsize(nuevo_w + PANEL_W, 500)
        self.frame_mapa.configure(width=nuevo_w, height=nuevo_h)
        self.canvas.configure(width=nuevo_w, height=nuevo_h)
        self.root.title(
            f"Sistema MAS — {self.distrito['nombre']}  |  Agente Vehículo "
            f"(Mapas + Semáforos + Vehículos vía API)"
        )
        self.lbl_distrito.config(text=f"Distrito: {self.distrito['nombre']}")

        # 3) Limpiar vehículos del mapa anterior (sus coordenadas no
        # tienen sentido en la geometría del nuevo distrito) y re-spawnear
        # algunos de partida, igual que al iniciar el programa.
        self.vehiculos_mapa.clear()
        self.veh_seleccionado = None
        self._actualizar_lista_panel()
        self._agregar_vehiculo_inicial("Automóvil")
        self._agregar_vehiculo_inicial("Bus")
        self._agregar_vehiculo_inicial("Motocicleta")

        # 4) Semáforos: usar un fallback local inmediato para no dejar el
        # mapa sin semáforos mientras se consulta la API en un hilo aparte.
        self.semaforos_remotos    = generar_semaforos_fallback(self.distrito)
        self.semaforos_son_reales = False
        threading.Thread(target=self._refrescar_semaforos_bg, daemon=True).start()

        self._actualizar_estado_apis_panel()
        messagebox.showinfo("Mapa cambiado", f"Ahora estás en: {self.distrito['nombre']}")

    def _tomar_control(self, veh: VehiculoAgente):
        self._desseleccionar_todos()
        veh.controlado_usuario = True
        self.veh_seleccionado  = veh
        self._actualizar_lista_panel()
        self.root.focus_set()

    def _on_click_mapa(self, event):
        mx, my = event.x, event.y
        mejor_veh, mejor_dist = None, 30
        for veh in self.vehiculos_mapa:
            dist = ((veh.x - mx)**2 + (veh.y - my)**2) ** 0.5
            if dist < mejor_dist:
                mejor_dist, mejor_veh = dist, veh
        if mejor_veh:
            self._tomar_control(mejor_veh)

    def _on_key_press(self, event):
        self.teclas_activas.add(event.keysym)
        if event.keysym == "Escape":
            self.root.destroy()

    def _on_key_release(self, event):
        self.teclas_activas.discard(event.keysym)

    # ── sync con nuestra API (hilo aparte) ───────────────────────────────────
    def _sync_loop(self):
        while True:
            try:
                sincronizar_estado_api(self.vehiculos_mapa, self.distrito["clave"])
            except Exception:
                pass
            time.sleep(0.5)

    # ════════════════════════════════════════════════════════════════════════
    #  RENDER
    # ════════════════════════════════════════════════════════════════════════
    def _render(self):
        self.canvas.delete("all")
        self._render_mapa()
        self._render_semaforos()
        for veh in self.vehiculos_mapa:
            veh.dibujar(self.canvas, self.tick, seleccionado=veh.controlado_usuario)
        self._render_hud()

    def _render_mapa(self):
        c = self.canvas
        d = self.distrito
        W, H = d["width"], d["height"]

        for av in d["avenidas_horizontales"]:
            y, xini, xfin = av["y"], av.get("x_ini", 0), av.get("x_fin", W)
            c.create_rectangle(xini, y-40, xfin, y+40, fill=C_ASFALTO, outline="")
            c.create_line(xini, y, xfin, y, fill="#ffcc00", width=2, dash=(12, 8))
            for off in (-18, 18):
                c.create_line(xini, y+off, xfin, y+off, fill="#334455", width=1, dash=(8, 14))
            paso = max(60, (xfin - xini) // 3)
            for x in range(int(xini)+40, int(xfin)-20, paso):
                c.create_text(x, y-22, text="→", fill="#445566", font=("Arial", 11, "bold"))
                c.create_text(x, y+22, text="←", fill="#445566", font=("Arial", 11, "bold"))

        for av in d["avenidas_verticales"]:
            x, yini, yfin = av["x"], av.get("y_ini", 0), av.get("y_fin", H)
            c.create_rectangle(x-40, yini, x+40, yfin, fill=C_ASFALTO, outline="")
            c.create_line(x, yini, x, yfin, fill="#ffcc00", width=2, dash=(12, 8))
            for off in (-18, 18):
                c.create_line(x+off, yini, x+off, yfin, fill="#334455", width=1, dash=(8, 14))
            paso = max(60, (yfin - yini) // 3)
            for y in range(int(yini)+40, int(yfin)-20, paso):
                c.create_text(x-22, y, text="↑", fill="#445566", font=("Arial", 11, "bold"))
                c.create_text(x+22, y, text="↓", fill="#445566", font=("Arial", 11, "bold"))

        # Manzanas: por rango_x/rango_y o por 'cuadras' (ambos formatos de la API real)
        casas = d.get("casas_config", {})
        if casas.get("cuadras"):
            for bloque in casas["cuadras"]:
                self._dibujar_manzana(c, bloque["x"], bloque["y"],
                                      bloque["x"]+bloque["w"], bloque["y"]+bloque["h"])
        else:
            for rx in casas.get("rango_x", []):
                for ry in casas.get("rango_y", []):
                    self._dibujar_manzana(c, rx[0], ry[0], rx[1], ry[1])

        for nodo in d["intersecciones"]:
            ix, iy = nodo["pos"]
            c.create_rectangle(ix-40, iy-40, ix+40, iy+40, fill="#25252d", outline="")
            for s in range(-38, 38, 9):
                c.create_rectangle(ix-40, iy+s, ix+40, iy+s+5, fill="#1c1c24", outline="")
            c.create_rectangle(ix-40, iy-40, ix+40, iy+40,
                               outline="#00f0ff", width=1, dash=(2, 4))
            c.create_text(ix, iy, text=nodo["nombre"], fill="#00f0ff",
                          font=("Courier New", 7, "bold"), justify="center")

        for val in range(100, W, 100):
            c.create_text(val, 10, text=f"{val}m", fill="#00f0ff", font=("Courier New", 7))
            c.create_line(val, 0, val, 5, fill="#00f0ff")
        for val in range(100, H, 100):
            c.create_text(12, val, text=f"{val}m", fill="#00f0ff", font=("Courier New", 7))
            c.create_line(0, val, 5, val, fill="#00f0ff")

    def _dibujar_manzana(self, c, x0, y0, x1, y1):
        c.create_rectangle(x0, y0, x1, y1, fill="#1a1f2a", outline="#2a3040", width=1)
        ex0, ey0, ex1, ey1 = x0+12, y0+12, x1-12, y1-12
        if ex1 > ex0+20 and ey1 > ey0+20:
            c.create_rectangle(ex0, ey0, ex1, ey1, fill="#252535", outline="#35354a", width=1)
            c.create_rectangle(ex0+4, ey0-8, ex1-4, ey0+4, fill="#3a2830", outline="")
            for wy in range(int(ey0)+10, int(ey1)-10, 18):
                for wx in range(int(ex0)+10, int(ex1)-10, 18):
                    c.create_rectangle(wx, wy, wx+8, wy+6, fill="#334488", outline="")

    def _render_semaforos(self):
        """
        Dibuja semáforos a partir de los datos REALES de la API de semáforos.
        Cada intersección tiene hasta 4 registros (NS, SN, EO, OE); se dibuja
        un punto de color por cada uno, ligeramente desplazado.
        """
        COL = {"verde": "#39ff14", "amarillo": "#ffcc00", "rojo": "#ff0055"}
        offsets = {"NS": (-12, -50), "SN": (12, 50), "EO": (-50, 12), "OE": (50, -12)}

        for sem in self.semaforos_remotos:
            sx, sy = sem.get("pos_x", 0), sem.get("pos_y", 0)
            dx, dy = offsets.get(sem.get("direccion", "NS"), (0, -50))
            x, y = sx + dx, sy + dy
            col = COL.get(sem.get("estado", "rojo"), "#ff0055")

            self.canvas.create_rectangle(x-2, y-2, x+2, y+14, fill="#333333", outline="")
            self.canvas.create_oval(x-9, y-9, x+9, y+9, fill="#121214",
                                    outline="#33333b", width=2)
            self.canvas.create_oval(x-11, y-11, x+11, y+11, fill="", outline=col, width=1)
            self.canvas.create_oval(x-6, y-6, x+6, y+6, fill=col, outline="")

    def _render_hud(self):
        veh = self.veh_seleccionado
        if veh:
            info = veh.info_completa()
            self.canvas.create_rectangle(10, self.distrito["height"]-110,
                                         200, self.distrito["height"]-10,
                                         fill="#0d1117", outline="#00f0ff", width=1)
            y0 = self.distrito["height"] - 100
            for linea in info.split("\n"):
                self.canvas.create_text(18, y0, text=linea, fill=C_BLAN,
                                        font=("Courier New", 8), anchor="w")
                y0 += 13
            self.lbl_info.config(text=veh.info_completa(), fg=C_VERDE)
        else:
            self.lbl_info.config(
                text="Ninguno seleccionado\nHaz click en un coche\npara tomar el control",
                fg=C_GRIS)

        cnt = len(self.vehiculos_mapa)
        self.canvas.create_text(
            self.distrito["width"]-10, self.distrito["height"]-14,
            text=f"Vehículos en mapa: {cnt}/{MAX_VEHICULOS_MAPA}",
            fill=C_GRIS, font=("Courier New", 8), anchor="e")

    # ════════════════════════════════════════════════════════════════════════
    #  LOOP PRINCIPAL
    # ════════════════════════════════════════════════════════════════════════
    def _tick_loop(self):
        now = time.time()
        self.last_time = now

        self._refrescar_semaforos_si_corresponde(now)

        # Extrapola el color de cada semáforo (real o local) según el
        # tiempo transcurrido desde su última ancla conocida — esto es
        # lo que hace que cambien de color en vivo tick a tick, en vez
        # de quedar congelados con el snapshot del último fetch/refresco.
        actualizar_ciclo_semaforos(self.semaforos_remotos)

        for veh in self.vehiculos_mapa:
            if veh.controlado_usuario:
                veh.procesar_teclas(self.teclas_activas)
            # Le pasamos la lista de los DEMÁS vehículos activos para que
            # cada uno pueda detectar si tiene otro coche adelante en su
            # mismo carril y frenar a tiempo (anti-colisión).
            otros = [v for v in self.vehiculos_mapa if v is not veh]
            veh.actualizar(self.semaforos_remotos, otros)

        if self.tick % 30 == 0:   # refrescar etiquetas de estado ~2 veces/seg
            self._actualizar_estado_apis_panel()

        self._render()
        self.tick += 1
        self.root.after(16, self._tick_loop)


# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  SIMULACIÓN MAS — Agente Vehículo")
    print("  Asegúrate de tener corriendo: python api_vehiculos.py")
    print("=" * 60)
    root = tk.Tk()
    app = SimulacionApp(root)
    root.mainloop()