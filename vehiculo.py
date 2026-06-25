# -*- coding: utf-8 -*-
"""
=====================================================================
  AGENTE VEHÍCULO — vehiculo.py
  Sistema Multi-Agente de Tráfico Urbano

  Este módulo CONSUME 3 APIs:
    1. API Mapas/Catastro  (compañero) → https://tecnologia-atkj.onrender.com/api/mapas
    2. API Semáforos        (compañero) → https://semaforos.onrender.com/api/semaforos
    3. API Vehículos        (nuestra)   → http://127.0.0.1:8001/api/vehiculos

  Si alguna API remota no responde (por ejemplo Render "duerme" el servicio
  tras inactividad y demora en despertar), este módulo usa datos de respaldo
  (fallback) para que la simulación nunca se caiga.
=====================================================================
"""

import math
import random
import time
import requests
from typing import Optional, Dict, List, Tuple


# ════════════════════════════════════════════════════════════════════════════
#  URLS DE LAS 3 APIs
# ════════════════════════════════════════════════════════════════════════════
API_MAPAS_URL      = "https://tecnologia-atkj.onrender.com/api/mapas"
API_SEMAFOROS_URL  = "https://semaforos.onrender.com/api/semaforos"

# ── URL de NUESTRA propia API de vehículos ───────────────────────────────────
# Por defecto usa localhost (para cuando trabajas en tu PC).
# Una vez que despliegues api_vehiculos.py en Render, reemplaza la línea
# de abajo por tu URL real, por ejemplo:
#   API_VEHICULOS_BASE = "https://vehiculos-XXXX.onrender.com"
# También puedes definir la variable de entorno VEHICULOS_API_URL para
# no tocar el código (útil si este cliente también corre en la nube).
import os as _os
API_VEHICULOS_BASE = _os.environ.get("VEHICULOS_API_URL", "http://127.0.0.1:8001")
API_VEHICULOS_URL   = f"{API_VEHICULOS_BASE}/api/vehiculos"

TIMEOUT_API   = 6          # segundos de espera (Render puede tardar en "despertar")
MAX_VEHICULOS_MAPA = 10


# ════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN VISUAL Y FÍSICA POR TIPO (4 categorías del CSV)
# ════════════════════════════════════════════════════════════════════════════
TIPOS_VEHICULO: Dict[str, dict] = {
    "Motocicleta": {
        "largo": 18, "ancho": 9,
        "vel_max": 4.8, "vel_max_rev": 1.2,
        "aceleracion": 0.22, "frenado": 0.30, "friccion": 0.06,
        "freno_sem": 45, "icono": "🏍",
        "descripcion": "Ágil, alta velocidad, radio de giro pequeño",
    },
    "Automóvil": {
        "largo": 28, "ancho": 14,
        "vel_max": 3.5, "vel_max_rev": 1.0,
        "aceleracion": 0.16, "frenado": 0.22, "friccion": 0.05,
        "freno_sem": 52, "icono": "🚗",
        "descripcion": "Velocidad y maniobrabilidad equilibradas",
    },
    "Camioneta": {
        "largo": 34, "ancho": 16,
        "vel_max": 2.8, "vel_max_rev": 0.8,
        "aceleracion": 0.12, "frenado": 0.18, "friccion": 0.04,
        "freno_sem": 58, "icono": "🚙",
        "descripcion": "Mayor tamaño, frenado más largo",
    },
    "Bus": {
        "largo": 46, "ancho": 18,
        "vel_max": 2.0, "vel_max_rev": 0.5,
        "aceleracion": 0.08, "frenado": 0.12, "friccion": 0.03,
        "freno_sem": 70, "icono": "🚌",
        "descripcion": "Vehículo grande, lento, frenado muy largo",
    },
}

MAPA_COLORES: Dict[str, str] = {
    "Amarillo": "#FFD700", "Azul": "#2255CC", "Beige": "#D4B896",
    "Blanco": "#F0F0F0", "Dorado": "#D4A017", "Gris": "#808080",
    "Marrón": "#8B4513", "Naranja": "#FF7700", "Negro": "#1A1A1A",
    "Plateado": "#B0B0B8", "Rojo": "#CC2233", "Verde": "#228B22",
}
MAPA_TECHO: Dict[str, str] = {
    "Amarillo": "#B8960A", "Azul": "#112266", "Beige": "#A08060",
    "Blanco": "#C0C0C0", "Dorado": "#907000", "Gris": "#505050",
    "Marrón": "#5C2A00", "Naranja": "#B04400", "Negro": "#0A0A0A",
    "Plateado": "#707078", "Rojo": "#881122", "Verde": "#114411",
}

SEMI_AV     = 40
CARRIL_OFF  = 18
MARGEN_NODO = 42


# ════════════════════════════════════════════════════════════════════════════
#  PLANO DE RESPALDO (fallback si la API de mapas no responde)
#  → idéntico al distrito "centro" devuelto por la API real
# ════════════════════════════════════════════════════════════════════════════
PLANO_FALLBACK = {
    "clave": "centro",
    "nombre": "CENTRO METROPOLITANO",
    "color_tema": "#00F0FF",
    "width": 800, "height": 800,
    "avenidas_horizontales": [
        {"y": 250, "x_ini": 0, "x_fin": 800},
        {"y": 540, "x_ini": 0, "x_fin": 800},
    ],
    "avenidas_verticales": [
        {"x": 250, "y_ini": 0, "y_fin": 800},
        {"x": 520, "y_ini": 0, "y_fin": 800},
    ],
    "intersecciones": [
        {"pos": [250, 250], "nombre": "CRUCE\n(AV. DE & AV. 9 )"},
        {"pos": [520, 250], "nombre": "CRUCE\n(AV. DE & AV. RI)"},
        {"pos": [250, 540], "nombre": "CRUCE\n(AV. DE & AV. 9 )"},
        {"pos": [520, 540], "nombre": "CRUCE\n(AV. DE & AV. RI)"},
    ],
    "casas_config": {
        "rango_x": [[40, 180], [320, 450], [590, 760]],
        "rango_y": [[40, 180], [320, 470], [610, 760]],
    },
}


# ════════════════════════════════════════════════════════════════════════════
#  CLIENTE DE LA API DE MAPAS (compañero de Catastro)
# ════════════════════════════════════════════════════════════════════════════
def cargar_mapas_api() -> List[dict]:
    """
    Consulta GET /api/mapas. Devuelve la lista de distritos.
    Cada distrito viene con su geometría dentro de 'config'.
    Si falla, devuelve [PLANO_FALLBACK].
    """
    try:
        r = requests.get(API_MAPAS_URL, timeout=TIMEOUT_API)
        if r.status_code == 200:
            datos = r.json()
            print(f"[API Mapas] {len(datos)} distritos recibidos")
            return datos
    except Exception as e:
        print(f"[API Mapas] No disponible ({e}). Usando plano de respaldo.")
    return [PLANO_FALLBACK]


def normalizar_distrito(distrito_raw: dict) -> dict:
    """
    La API de mapas anida la geometría dentro de 'config'.
    Esta función la "aplana" a la forma que usa nuestro motor de carriles:
    {width, height, avenidas_horizontales, avenidas_verticales, intersecciones, casas_config}
    """
    cfg = distrito_raw.get("config", distrito_raw)
    return {
        "clave":      distrito_raw.get("clave", "centro"),
        "nombre":     distrito_raw.get("nombre", "DISTRITO"),
        "color_tema": distrito_raw.get("color_tema", "#00f0ff"),
        "width":      distrito_raw.get("width", 800),
        "height":     distrito_raw.get("height", 800),
        "avenidas_horizontales": cfg.get("avenidas_horizontales", []),
        "avenidas_verticales":   cfg.get("avenidas_verticales", []),
        "intersecciones":        cfg.get("intersecciones", []),
        "casas_config":          cfg.get("casas_config", {"rango_x": [], "rango_y": []}),
        "curvas":                cfg.get("curvas", []),
    }


def obtener_distrito(clave: str = "centro") -> dict:
    """Devuelve el distrito normalizado, buscándolo por su 'clave'."""
    distritos = cargar_mapas_api()
    for d in distritos:
        if d.get("clave") == clave:
            return normalizar_distrito(d)
    # Si no se encuentra esa clave, usar el primero disponible
    if distritos:
        print(f"[Mapas] Distrito '{clave}' no encontrado, usando '{distritos[0].get('clave')}'")
        return normalizar_distrito(distritos[0])
    return normalizar_distrito(PLANO_FALLBACK)


# ════════════════════════════════════════════════════════════════════════════
#  CLIENTE DE LA API DE SEMÁFOROS (compañero de Semáforos)
# ════════════════════════════════════════════════════════════════════════════
def cargar_semaforos_api(mapa_clave: str = "centro") -> List[dict]:
    """
    Consulta GET /api/semaforos y filtra solo los del distrito actual.
    Formato real de cada registro:
      {mapa_clave, interseccion_id, pos_x, pos_y, direccion, estado,
       tiempo_verde, tiempo_amarillo, tiempo_rojo, activo, modo, id}
    direccion puede ser: NS, SN, EO, OE
    """
    try:
        r = requests.get(API_SEMAFOROS_URL, timeout=TIMEOUT_API)
        if r.status_code == 200:
            todos = r.json()
            filtrados = [s for s in todos if s.get("mapa_clave") == mapa_clave]
            print(f"[API Semáforos] {len(filtrados)} semáforos en '{mapa_clave}'")
            return filtrados
    except Exception as e:
        print(f"[API Semáforos] No disponible ({e}). Sin semáforos remotos.")
    return []


def semaforo_bloquea(direccion_movimiento: str, estado: str) -> bool:
    """
    True si el semáforo en ROJO o AMARILLO bloquea el paso
    para un vehículo que se mueve en 'direccion_movimiento'.
    direccion_movimiento usa el mismo código que la API: NS, SN, EO, OE.
    """
    return estado in ("rojo", "amarillo")


# ════════════════════════════════════════════════════════════════════════════
#  CLIENTE DE NUESTRA PROPIA API DE VEHÍCULOS
# ════════════════════════════════════════════════════════════════════════════
def cargar_flota_api() -> List[dict]:
    """
    Consulta GET /api/vehiculos (nuestra API local).
    Si no está corriendo, hace fallback al CSV directo.
    """
    try:
        r = requests.get(API_VEHICULOS_URL, timeout=2)
        if r.status_code == 200:
            datos = r.json()
            print(f"[API Vehículos] {len(datos)} vehículos recibidos")
            return datos
    except Exception as e:
        print(f"[API Vehículos] No disponible ({e}). Leyendo CSV local...")

    import os, csv
    base = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base, "vehiculos.csv")
    flota = []
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                categoria = row["CATEGORÍA"].strip()
                color     = row["COLOR"].strip()
                cfg       = TIPOS_VEHICULO.get(categoria, TIPOS_VEHICULO["Automóvil"])
                flota.append({
                    "id": int(row["ID"]), "placa": row["PLACA"].strip(),
                    "color": color, "color_hex": MAPA_COLORES.get(color, "#808080"),
                    "tamaño": row["TAMAÑO"].strip(), "usuario": row["USUARIO"].strip(),
                    "chofer": row["CHOFER"].strip(), "licencia": row["LICENCIA"].strip(),
                    "soat_vencimiento": row["SOAT VENC."].strip(),
                    "categoria": categoria, "icono": cfg["icono"],
                })
    print(f"[CSV] Flota cargada: {len(flota)} vehículos")
    return flota


def sincronizar_estado_api(vehiculos_activos: list, mapa_clave: str = "centro"):
    """Envía posiciones actuales a nuestra API. No bloquea si falla."""
    try:
        posiciones = {}
        ids_activos = []
        controlado = None
        for v in vehiculos_activos:
            ids_activos.append(v.datos["id"])
            posiciones[str(v.datos["id"])] = {
                "x": round(v.x, 1), "y": round(v.y, 1),
                "angulo": round(v.angulo % 360, 1),
                "velocidad": round(v.vel, 3),
                "mapa_clave": mapa_clave,
            }
            if v.controlado_usuario:
                controlado = v.datos["id"]
        payload = {"activos": ids_activos, "posiciones": posiciones,
                   "controlado_por_usuario": controlado}
        requests.post(f"{API_VEHICULOS_BASE}/api/vehiculos/estado/actualizar",
                     json=payload, timeout=1)
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
#  GEOMETRÍA DE CARRILES (a partir del distrito normalizado)
# ════════════════════════════════════════════════════════════════════════════
class CarrilVial:
    def __init__(self, orient: str, coord_fija: float,
                 rango_ini: float, rango_fin: float, sentido: int,
                 codigo_direccion: str):
        self.orient           = orient       # "H" o "V"
        self.coord_fija       = coord_fija
        self.rango_ini        = rango_ini
        self.rango_fin        = rango_fin
        self.sentido          = sentido      # +1 o -1
        self.codigo_direccion = codigo_direccion  # "EO","OE","NS","SN" (p/semáforos)


def construir_carriles(distrito: dict) -> List[CarrilVial]:
    """
    Genera carriles a partir del distrito normalizado.
    Asigna códigos de dirección compatibles con la API de semáforos:
      H sentido +1 (→ este)  = "OE" (Oeste->Este)
      H sentido -1 (← oeste) = "EO" (Este->Oeste)
      V sentido +1 (↓ sur)   = "NS" (Norte->Sur)
      V sentido -1 (↑ norte) = "SN" (Sur->Norte)
    """
    carriles = []
    W = distrito.get("width", 800)
    H = distrito.get("height", 800)

    for av in distrito.get("avenidas_horizontales", []):
        y    = av["y"]
        xini = av.get("x_ini", 0)
        xfin = av.get("x_fin", W)
        carriles.append(CarrilVial("H", y - CARRIL_OFF, xini, xfin, +1, "OE"))
        carriles.append(CarrilVial("H", y + CARRIL_OFF, xfin, xini, -1, "EO"))

    for av in distrito.get("avenidas_verticales", []):
        x    = av["x"]
        yini = av.get("y_ini", 0)
        yfin = av.get("y_fin", H)
        carriles.append(CarrilVial("V", x - CARRIL_OFF, yfin, yini, -1, "SN"))
        carriles.append(CarrilVial("V", x + CARRIL_OFF, yini, yfin, +1, "NS"))

    return carriles


def carril_inicio_aleatorio(carriles: List[CarrilVial], distrito: dict) -> Tuple[CarrilVial, float]:
    if not carriles:
        return None, 0.0
    c = random.choice(carriles)
    margen = 60
    lo = min(c.rango_ini, c.rango_fin) + margen
    hi = max(c.rango_ini, c.rango_fin) - margen
    pos = random.uniform(lo, hi) if hi > lo else (lo + hi) / 2
    return c, pos


def en_interseccion(x, y, distrito: dict):
    for nodo in distrito.get("intersecciones", []):
        nx, ny = nodo["pos"]
        if math.hypot(x - nx, y - ny) < MARGEN_NODO:
            return True, (nx, ny)
    return False, None


def nodo_mas_cercano(x, y, distrito: dict, radio=MARGEN_NODO):
    """Devuelve (nx, ny) del nodo más cercano si está dentro del radio, sino None."""
    for nodo in distrito.get("intersecciones", []):
        nx, ny = nodo["pos"]
        if math.hypot(x - nx, y - ny) < radio:
            return (nx, ny)
    return None


# ════════════════════════════════════════════════════════════════════════════
#  CLASE PRINCIPAL: VehiculoAgente
# ════════════════════════════════════════════════════════════════════════════
class VehiculoAgente:
    """
    Representa un vehículo activo en el mapa.
    Obtiene su tipo/colores de la API de vehículos, su geometría de la
    API de mapas (carriles), y obedece la API de semáforos.
    """

    def __init__(self, datos: dict, carril_inicial: CarrilVial, pos_inicial: float,
                 distrito: dict, carriles: List[CarrilVial],
                 controlado_usuario: bool = False):

        self.datos       = datos
        self.categoria   = datos.get("categoria", "Automóvil")
        self.tipo_config = TIPOS_VEHICULO.get(self.categoria, TIPOS_VEHICULO["Automóvil"])

        color_nombre         = datos.get("color", "Gris")
        self.color_hex       = datos.get("color_hex") or MAPA_COLORES.get(color_nombre, "#808080")
        self.color_techo_hex = MAPA_TECHO.get(color_nombre, "#404040")

        self.distrito = distrito
        self.carriles = carriles
        self.W = distrito.get("width", 800)
        self.H = distrito.get("height", 800)

        self.carril_actual = carril_inicial
        if carril_inicial.orient == "H":
            self.x = float(pos_inicial)
            self.y = float(carril_inicial.coord_fija)
        else:
            self.x = float(carril_inicial.coord_fija)
            self.y = float(pos_inicial)
        self.angulo = self._angulo_carril(carril_inicial)
        self.vel    = 0.0

        self.controlado_usuario = controlado_usuario
        self.frenando      = False
        self.bloqueado_sem = False

        self._giro_izq = False
        self._giro_der = False

        self._tick_giro   = random.randint(40, 120)
        self._cuenta_giro = 0

        self.historial = []
        self.MAX_HIST  = 40

        self.distancia_total = 0.0
        self.vel_max = 0.0

    # ── helpers ──────────────────────────────────────────────────────────────
    def _angulo_carril(self, c: CarrilVial) -> float:
        if c.orient == "H":
            return 0.0 if c.sentido == +1 else 180.0
        return 90.0 if c.sentido == +1 else 270.0

    @property
    def largo(self): return self.tipo_config["largo"]
    @property
    def ancho(self):  return self.tipo_config["ancho"]
    @property
    def etiqueta(self):
        return f"{self.tipo_config['icono']} {self.datos['placa']}"

    def info_completa(self) -> str:
        d, cfg = self.datos, self.tipo_config
        return (
            f"ID: {d['id']}  Placa: {d['placa']}\n"
            f"Tipo: {self.categoria} {cfg['icono']}\n"
            f"Color: {d['color']}  Tamaño: {d.get('tamaño','-')}\n"
            f"Chofer: {d.get('chofer','-')}\n"
            f"SOAT: {d.get('soat_vencimiento', d.get('soat_venc','-'))}\n"
            f"Vel: {abs(self.vel)*30:.1f} km/h"
        )

    # ── input teclado ────────────────────────────────────────────────────────
    def procesar_teclas(self, teclas: set):
        if not self.controlado_usuario:
            return
        cfg = self.tipo_config
        if "Up" in teclas or "w" in teclas:
            self.vel = min(self.vel + cfg["aceleracion"], cfg["vel_max"])
        if "Down" in teclas or "s" in teclas:
            if self.vel > 0:
                self.vel = max(0.0, self.vel - cfg["frenado"])
            else:
                self.vel = max(-cfg["vel_max_rev"], self.vel - cfg["aceleracion"] * 0.5)
        if "space" in teclas:
            self.vel *= 0.80
        if "Left" in teclas or "a" in teclas:
            self._giro_izq = True
        if "Right" in teclas or "d" in teclas:
            self._giro_der = True

    # ── IA NPC ───────────────────────────────────────────────────────────────
    def _ia_npc(self):
        cfg = self.tipo_config
        vel_crucero = cfg["vel_max"] * random.uniform(0.5, 0.9)
        if self.vel < vel_crucero:
            self.vel = min(self.vel + cfg["aceleracion"] * 0.7, vel_crucero)
        self._cuenta_giro += 1
        if self._cuenta_giro >= self._tick_giro:
            self._cuenta_giro = 0
            self._tick_giro   = random.randint(50, 150)
            d = random.random()
            if d < 0.4:   self._giro_izq = True
            elif d < 0.7: self._giro_der = True

    # ── verificar semáforo (usando datos REALES de la API de semáforos) ─────
    def verificar_semaforo(self, semaforos: List[dict]):
        """
        semaforos: lista de dicts con formato de la API real:
          {pos_x, pos_y, direccion, estado, ...}
        """
        cfg = self.tipo_config
        c   = self.carril_actual
        cod = c.codigo_direccion   # "OE","EO","NS","SN"

        for sem in semaforos:
            if sem.get("direccion") != cod:
                continue
            sx, sy = sem.get("pos_x", 0), sem.get("pos_y", 0)

            if c.orient == "H":
                dist_adel = (sx - self.x) * c.sentido
                dist_lat  = abs(sy - self.y)
            else:
                dist_adel = (sy - self.y) * c.sentido
                dist_lat  = abs(sx - self.x)

            if 0 < dist_adel < cfg["freno_sem"] and dist_lat < SEMI_AV:
                if semaforo_bloquea(cod, sem.get("estado", "verde")):
                    self.bloqueado_sem = True
                    return
        self.bloqueado_sem = False

    # ── giro en intersección ─────────────────────────────────────────────────
    def _intentar_giro(self):
        en_nodo, _ = en_interseccion(self.x, self.y, self.distrito)
        if not en_nodo or not (self._giro_izq or self._giro_der):
            return

        c = self.carril_actual
        nueva_ori = "V" if c.orient == "H" else "H"
        candidatos = []
        for carril in self.carriles:
            if carril.orient != nueva_ori:
                continue
            dist = (abs(carril.coord_fija - self.x) if nueva_ori == "V"
                    else abs(carril.coord_fija - self.y))
            candidatos.append((dist, carril))
        candidatos.sort(key=lambda t: t[0])
        if not candidatos:
            self._giro_izq = self._giro_der = False
            return

        mejor = None
        for _, carril in candidatos:
            if self._giro_izq:
                if c.orient == "H" and c.sentido == +1 and carril.sentido == -1: mejor = carril; break
                if c.orient == "H" and c.sentido == -1 and carril.sentido == +1: mejor = carril; break
                if c.orient == "V" and c.sentido == +1 and carril.sentido == +1: mejor = carril; break
                if c.orient == "V" and c.sentido == -1 and carril.sentido == -1: mejor = carril; break
            if self._giro_der:
                if c.orient == "H" and c.sentido == +1 and carril.sentido == +1: mejor = carril; break
                if c.orient == "H" and c.sentido == -1 and carril.sentido == -1: mejor = carril; break
                if c.orient == "V" and c.sentido == +1 and carril.sentido == -1: mejor = carril; break
                if c.orient == "V" and c.sentido == -1 and carril.sentido == +1: mejor = carril; break
        if mejor is None:
            mejor = candidatos[0][1]

        self.carril_actual = mejor
        if mejor.orient == "V":
            self.x = float(mejor.coord_fija)
        else:
            self.y = float(mejor.coord_fija)
        self.angulo = self._angulo_carril(mejor)
        self.vel    = max(0.4, self.vel * 0.65)
        self._giro_izq = self._giro_der = False

    # ── física principal ─────────────────────────────────────────────────────
    def actualizar(self, semaforos: List[dict]):
        cfg = self.tipo_config
        if not self.controlado_usuario:
            self._ia_npc()

        self.verificar_semaforo(semaforos)
        if self.bloqueado_sem and self.vel > 0:
            self.vel = max(0.0, self.vel - cfg["frenado"] * 1.8)
            self.frenando = True
        else:
            self.frenando = self.bloqueado_sem

        if self.vel > 0:
            self.vel = max(0.0, self.vel - cfg["friccion"])
        elif self.vel < 0:
            self.vel = min(0.0, self.vel + cfg["friccion"])
        self.vel = max(-cfg["vel_max_rev"], min(cfg["vel_max"], self.vel))

        self._intentar_giro()

        c = self.carril_actual
        ds = self.vel * c.sentido
        px, py = self.x, self.y
        if c.orient == "H":
            self.x += ds; self.y = float(c.coord_fija)
        else:
            self.y += ds; self.x = float(c.coord_fija)

        m = 12
        if self.x < m:        self.x = m;        self.vel *= -0.3
        if self.x > self.W-m: self.x = self.W-m; self.vel *= -0.3
        if self.y < m:        self.y = m;        self.vel *= -0.3
        if self.y > self.H-m: self.y = self.H-m; self.vel *= -0.3

        ang_obj = self._angulo_carril(c)
        diff = (ang_obj - self.angulo + 180) % 360 - 180
        self.angulo += diff * 0.22

        dist = math.hypot(self.x - px, self.y - py)
        self.distancia_total += dist
        self.vel_max = max(self.vel_max, abs(self.vel))

        self.historial.append((int(self.x), int(self.y)))
        if len(self.historial) > self.MAX_HIST:
            self.historial.pop(0)

    # ════════════════════════════════════════════════════════════════════════
    #  DIBUJO (Tkinter)
    # ════════════════════════════════════════════════════════════════════════
    def dibujar(self, canvas, tick: int, seleccionado: bool = False):
        self._dibujar_rastro(canvas)
        self._dibujar_sprite(canvas, tick, seleccionado)
        self._dibujar_etiqueta(canvas, tick, seleccionado)

    def _dibujar_rastro(self, canvas):
        if len(self.historial) < 3:
            return
        for i in range(1, len(self.historial)):
            frac = i / len(self.historial)
            color = f"#{int(frac*60):02x}{int(frac*180):02x}{int(frac*100):02x}"
            x1, y1 = self.historial[i-1]; x2, y2 = self.historial[i]
            canvas.create_line(x1, y1, x2, y2, fill=color, width=max(1, int(frac*2)))

    def _rot(self, px, py, cx, cy, ang_rad):
        dx = px*math.cos(ang_rad) - py*math.sin(ang_rad)
        dy = px*math.sin(ang_rad) + py*math.cos(ang_rad)
        return (cx+dx, cy+dy)

    def _dibujar_sprite(self, canvas, tick, sel):
        cx, cy, ang = self.x, self.y, math.radians(self.angulo)
        col, tec    = self.color_hex, self.color_techo_hex
        W2, H2      = self.largo/2, self.ancho/2

        if self.categoria == "Motocicleta":
            self._sprite_moto(canvas, cx, cy, ang, col, W2, H2)
        elif self.categoria == "Bus":
            self._sprite_bus(canvas, cx, cy, ang, col, tec, W2, H2)
        elif self.categoria == "Camioneta":
            self._sprite_camioneta(canvas, cx, cy, ang, col, tec, W2, H2)
        else:
            self._sprite_auto(canvas, cx, cy, ang, col, tec, W2, H2)

        if sel:
            blink = (tick // 12) % 2 == 0
            bc = "#00ff99" if blink else "#00cc77"
            def r(px, py): return self._rot(px, py, cx, cy, ang)
            carro = [r(-W2,-H2), r(W2,-H2), r(W2,H2), r(-W2,H2)]
            canvas.create_polygon(carro, fill="", outline=bc, width=2)

    def _sprite_auto(self, canvas, cx, cy, ang, col, tec, W2, H2):
        def r(px, py): return self._rot(px, py, cx, cy, ang)
        carro = [r(-W2,-H2), r(W2,-H2), r(W2,H2), r(-W2,H2)]
        canvas.create_polygon(carro, fill=col, outline="#000000", width=1)
        tx, ty = W2*0.55, H2*0.62
        techo = [r(-tx,-ty), r(tx*0.8,-ty), r(tx*0.8,ty), r(-tx,ty)]
        canvas.create_polygon(techo, fill=tec, outline="")
        pb = [r(tx*0.35,-ty+1), r(tx*0.8,-ty+1), r(tx*0.8,ty-1), r(tx*0.35,ty-1)]
        canvas.create_polygon(pb, fill="#88ccee", outline="")
        for fy in [-H2+2, H2-2]:
            fx, fy_ = r(W2, fy)
            canvas.create_oval(fx-2,fy_-2,fx+2,fy_+2, fill="#FFEE44", outline="")
        for fy in [-H2+2, H2-2]:
            tx_, ty_ = r(-W2, fy)
            canvas.create_oval(tx_-2,ty_-2,tx_+2,ty_+2, fill="#FF2244", outline="")
        for rxy in [(-W2+4,-H2),(-W2+4,H2),(W2-4,-H2),(W2-4,H2)]:
            wx, wy = r(*rxy)
            canvas.create_oval(wx-3,wy-3,wx+3,wy+3, fill="#111111", outline="#444444")

    def _sprite_camioneta(self, canvas, cx, cy, ang, col, tec, W2, H2):
        def r(px, py): return self._rot(px, py, cx, cy, ang)
        carro = [r(-W2,-H2), r(W2,-H2), r(W2,H2), r(-W2,H2)]
        canvas.create_polygon(carro, fill=col, outline="#000000", width=1)
        cab = [r(W2*0.3,-H2*0.9), r(W2,-H2*0.9), r(W2,H2*0.9), r(W2*0.3,H2*0.9)]
        canvas.create_polygon(cab, fill=tec, outline="")
        pb = [r(W2*0.55,-H2*0.75), r(W2*0.95,-H2*0.75), r(W2*0.95,H2*0.75), r(W2*0.55,H2*0.75)]
        canvas.create_polygon(pb, fill="#88ccee", outline="")
        for fy in [-H2+3, H2-3]:
            tx_, ty_ = r(-W2, fy)
            canvas.create_oval(tx_-2,ty_-2,tx_+2,ty_+2, fill="#FF2244", outline="")
        for fy in [-H2+3, H2-3]:
            fx, fy_ = r(W2, fy)
            canvas.create_oval(fx-2,fy_-2,fx+2,fy_+2, fill="#FFEE44", outline="")
        for rxy in [(-W2+5,-H2),(-W2+5,H2),(0,-H2),(0,H2),(W2-5,-H2),(W2-5,H2)]:
            wx, wy = r(*rxy)
            canvas.create_oval(wx-3,wy-3,wx+3,wy+3, fill="#111111", outline="#444444")

    def _sprite_bus(self, canvas, cx, cy, ang, col, tec, W2, H2):
        def r(px, py): return self._rot(px, py, cx, cy, ang)
        carro = [r(-W2,-H2), r(W2,-H2), r(W2,H2), r(-W2,H2)]
        canvas.create_polygon(carro, fill=col, outline="#000000", width=1)
        canvas.create_polygon(
            [r(-W2+2,-H2+2), r(W2-2,-H2+2), r(W2-2,H2-2), r(-W2+2,H2-2)],
            fill=tec, outline=""
        )
        paso = (2*W2-10)/4
        for i in range(4):
            wx = -W2+5+i*paso
            for wy in [-H2+3, H2-6]:
                p1x,p1y = r(wx, wy); p2x,p2y = r(wx+paso*0.7, wy)
                canvas.create_line(p1x,p1y,p2x,p2y, fill="#aaddff", width=2)
        p1x,p1y = r(W2-4,-H2+1); p2x,p2y = r(W2-4,H2-1)
        canvas.create_line(p1x,p1y,p2x,p2y, fill="#333333", width=2)
        for fy in [-H2+2, H2-2]:
            fx, fy_ = r(W2, fy)
            canvas.create_oval(fx-3,fy_-3,fx+3,fy_+3, fill="#FFEE44", outline="")
        for fy in [-H2+2, H2-2]:
            tx_, ty_ = r(-W2, fy)
            canvas.create_oval(tx_-3,ty_-3,tx_+3,ty_+3, fill="#FF2244", outline="")
        for rxy in [(-W2+6,-H2),(-W2+6,H2),(W2-6,-H2),(W2-6,H2)]:
            wx, wy = r(*rxy)
            canvas.create_oval(wx-4,wy-4,wx+4,wy+4, fill="#111111", outline="#444444")

    def _sprite_moto(self, canvas, cx, cy, ang, col, W2, H2):
        def r(px, py): return self._rot(px, py, cx, cy, ang)
        carro = [r(-W2,-H2), r(W2,-H2), r(W2,H2), r(-W2,H2)]
        canvas.create_polygon(carro, fill=col, outline="#000000", width=1)
        p1x,p1y = r(-W2+2,0); p2x,p2y = r(W2-2,0)
        canvas.create_line(p1x,p1y,p2x,p2y, fill="#ffffff", width=1)
        fx, fy_ = r(W2,0)
        canvas.create_oval(fx-3,fy_-3,fx+3,fy_+3, fill="#FFEE44", outline="")
        for rxy in [(-W2+3,0),(W2-3,0)]:
            wx, wy = r(*rxy)
            canvas.create_oval(wx-3,wy-3,wx+3,wy+3, fill="#111111", outline="#555555")
        hx, hy = r(0,0)
        canvas.create_oval(hx-3,hy-3,hx+3,hy+3, fill="#cc8833", outline="")

    def _dibujar_etiqueta(self, canvas, tick, sel):
        col_borde = "#00ff99" if sel else "#334455"
        col_texto = "#00e878" if sel else "#778899"
        ey = self.y - self.ancho - 12
        canvas.create_rectangle(self.x-22, ey-7, self.x+22, ey+7,
                                fill="#0d1117", outline=col_borde, width=1)
        canvas.create_text(self.x, ey,
                           text=f"{self.tipo_config['icono']} {self.datos['placa']}",
                           fill=col_texto, font=("Courier New", 7, "bold"))
        if sel:
            canvas.create_line(self.x, ey+7, self.x, self.y-self.ancho,
                               fill="#00ff99", width=1)