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
from datetime import datetime, timezone
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

TIMEOUT_POR_INTENTO = 30    # segundos de espera por cada intento individual
MAX_REINTENTOS      = 4     # total: hasta 4×30 = 120s (2 min) esperando a Render
TIMEOUT_API_LOCAL   = 2     # API local: si no responde en 2s no está corriendo
MAX_VEHICULOS_MAPA  = 10

# Flag para no repetir el mismo aviso de semáforos en consola indefinidamente
_sem_aviso_logueado = False


def _get_con_reintentos(url: str, desc: str = "") -> "requests.Response | None":
    """
    Hace GET a 'url' con reintentos automáticos.
    Render free tier puede tardar hasta 120s en despertar si estaba inactivo:
    espera hasta MAX_REINTENTOS × TIMEOUT_POR_INTENTO segundos en total,
    imprimiendo un mensaje de progreso en cada intento fallido.
    Devuelve el Response si tuvo éxito, o None si agotó los reintentos.
    """
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            print(f"[{desc}] Intento {intento}/{MAX_REINTENTOS} — conectando...")
            r = requests.get(url, timeout=TIMEOUT_POR_INTENTO)
            if r.status_code == 200:
                print(f"[{desc}] ✓ Conectado (intento {intento})")
                return r
            else:
                print(f"[{desc}] HTTP {r.status_code} en intento {intento}")
        except Exception as e:
            tipo = type(e).__name__
            restantes = MAX_REINTENTOS - intento
            if restantes > 0:
                print(f"[{desc}] Intento {intento} fallido ({tipo}). Reintentando...")
            else:
                print(f"[{desc}] Intento {intento} fallido ({tipo}). Sin más intentos.")
    return None


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
    Consulta GET /api/mapas con reintentos automáticos.
    Espera hasta MAX_REINTENTOS × TIMEOUT_POR_INTENTO segundos (120s).
    Solo usa el plano de respaldo si agotó TODOS los reintentos sin respuesta.
    """
    r = _get_con_reintentos(API_MAPAS_URL, "API Mapas")
    if r is not None:
        datos = r.json()
        # Filtrar entradas sin geometría real ("string" de prueba, entradas vacías)
        validos = [
            d for d in datos
            if isinstance(d, dict) and d.get("clave") and d.get("clave") != "string"
        ]
        if validos:
            print(f"[API Mapas] {len(validos)} distritos válidos: {[d['clave'] for d in validos]}")
            return validos
        print("[API Mapas] La API respondió pero sin distritos válidos. Usando respaldo.")
    else:
        print("[API Mapas] ✗ No se pudo conectar tras todos los reintentos. Usando respaldo.")
    return [PLANO_FALLBACK]


def _es_avenida_valida(av: dict) -> bool:
    """True si el dict tiene las claves reales de geometría (no 'additionalProp1' de prueba)."""
    return isinstance(av, dict) and ("y" in av or "x" in av)


def normalizar_distrito(distrito_raw: dict) -> dict:
    """
    La API de mapas anida la geometría dentro de 'config'.
    Estructura REAL de la API (verificada contra datos reales):
      - distrito_raw["clave"], ["nombre"], ["color_tema"]
      - distrito_raw["width"], ["height"]  ← en la RAÍZ, no en config
      - distrito_raw["config"]["avenidas_horizontales"]  → [{y, x_ini, x_fin}, ...]
      - distrito_raw["config"]["avenidas_verticales"]    → [{x, y_ini, y_fin}, ...]
      - distrito_raw["config"]["intersecciones"]         → [{pos:[x,y], nombre}, ...]
      - distrito_raw["config"]["casas_config"]           → {rango_x, rango_y} o {cuadras:[]}

    La entrada 'string' de prueba tiene 'additionalProp1' en lugar de 'y'/'x';
    se filtra aquí para que no rompa el motor de carriles.
    """
    cfg = distrito_raw.get("config", distrito_raw)

    # Filtrar solo avenidas con geometría real (excluir additionalProp1)
    av_h_raw = cfg.get("avenidas_horizontales", [])
    av_v_raw = cfg.get("avenidas_verticales",   [])
    av_h = [a for a in av_h_raw if _es_avenida_valida(a)]
    av_v = [a for a in av_v_raw if _es_avenida_valida(a)]

    # Si después de filtrar no queda geometría real, usar plano de respaldo
    if not av_h or not av_v:
        av_h          = PLANO_FALLBACK["avenidas_horizontales"]
        av_v          = PLANO_FALLBACK["avenidas_verticales"]
        intersecciones = PLANO_FALLBACK["intersecciones"]
        casas          = PLANO_FALLBACK.get("casas_config", {"rango_x": [], "rango_y": []})
    else:
        intersecciones_raw = cfg.get("intersecciones", [])
        # Filtrar intersecciones válidas (deben tener "pos" con 2 coords)
        intersecciones = [
            i for i in intersecciones_raw
            if isinstance(i, dict) and isinstance(i.get("pos"), list) and len(i["pos"]) == 2
        ]
        if not intersecciones:
            intersecciones = PLANO_FALLBACK["intersecciones"]
        casas = cfg.get("casas_config", {"rango_x": [], "rango_y": []})
        if not isinstance(casas, dict):
            casas = {"rango_x": [], "rango_y": []}

    # width/height están en la RAÍZ del objeto (no dentro de config)
    return {
        "clave":                 distrito_raw.get("clave",  "centro"),
        "nombre":                distrito_raw.get("nombre", "CENTRO METROPOLITANO"),
        "color_tema":            distrito_raw.get("color_tema", "#00f0ff"),
        "width":                 int(distrito_raw.get("width",  800)),
        "height":                int(distrito_raw.get("height", 800)),
        "avenidas_horizontales": av_h,
        "avenidas_verticales":   av_v,
        "intersecciones":        intersecciones,
        "casas_config":          casas,
        "curvas":                [c for c in cfg.get("curvas", []) if isinstance(c, dict) and "R" in c],
        "nombres_avenidas":      cfg.get("nombres_avenidas", {}),
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
def _fijar_anclas_semaforos(semaforos: List[dict]) -> List[dict]:
    """
    Guarda, para cada semáforo, el estado y el instante ('ancla') en que
    ese estado era válido. A partir de esa ancla se puede extrapolar el
    color correcto en cualquier momento posterior sin volver a golpear
    la API — esto es lo que permite que los semáforos CAMBIEN DE COLOR
    en vivo, en vez de quedar congelados con el snapshot del momento en
    que se cargaron. Se llama automáticamente al construir cualquier
    lista de semáforos (locales o de la API).
    """
    for s in semaforos:
        s["_estado_ancla"] = s.get("estado", "rojo")
        ts_ancla = None
        ua = s.get("updated_at")
        if ua:
            try:
                ts_ancla = datetime.fromisoformat(str(ua).replace("Z", "+00:00")).timestamp()
            except Exception:
                ts_ancla = None
        s["_ts_ancla"] = ts_ancla if ts_ancla is not None else time.time()
    return semaforos


def actualizar_ciclo_semaforos(semaforos: List[dict]) -> None:
    """
    Recalcula 'estado' de CADA semáforo en vivo, extrapolando desde su
    ancla (estado + timestamp conocidos) usando sus propias duraciones
    de fase (tiempo_verde / tiempo_amarillo / tiempo_rojo). Se debe
    llamar en cada tick de la simulación para que los semáforos —tanto
    los reales de la API como los locales de respaldo— avancen de color
    con el paso del tiempo en vez de quedar congelados.
    """
    ahora_ts = time.time()
    orden = ["verde", "amarillo", "rojo"]
    for s in semaforos:
        estado_ancla = s.get("_estado_ancla")
        ts_ancla = s.get("_ts_ancla")
        if estado_ancla not in orden or ts_ancla is None:
            continue   # semáforo sin ancla válida (no debería pasar) -> se deja como está

        duraciones = {
            "verde":    max(1, int(s.get("tiempo_verde", 10) or 10)),
            "amarillo": max(1, int(s.get("tiempo_amarillo", 5) or 5)),
            "rojo":     max(1, int(s.get("tiempo_rojo", 10) or 10)),
        }
        transcurrido = ahora_ts - ts_ancla
        if transcurrido < 0:
            s["estado"] = estado_ancla
            continue

        idx = orden.index(estado_ancla)
        restante = transcurrido
        # Avanza fase por fase hasta ubicar en cuál está "ahora mismo"
        while restante >= duraciones[orden[idx]]:
            restante -= duraciones[orden[idx]]
            idx = (idx + 1) % 3
        s["estado"] = orden[idx]


def generar_semaforos_fallback(distrito: dict, momento: Optional[float] = None) -> List[dict]:
    """
    Genera semáforos LOCALES de respaldo, uno por cada dirección
    (NS, SN, EO, OE) en cada intersección del distrito.
    Se usa cuando la API remota de semáforos no tiene datos para
    el 'mapa_clave' actual (por ejemplo, porque el compañero todavía
    no pobló ese distrito, o el dato fue borrado/reiniciado).
    Cada semáforo alterna fases igual que en el modelo real:
    verde 10s, amarillo 5s, rojo 10s — con un 'ancla' (updated_at) para
    que su color siga avanzando en vivo tick a tick (ver
    actualizar_ciclo_semaforos), no solo en el instante de creación.

    'momento': permite pasar un timestamp fijo (en vez de time.time() real)
    para pruebas reproducibles. En producción se deja en None y usa el
    reloj real del sistema.
    """
    ahora = momento if momento is not None else time.time()
    ahora_iso = datetime.fromtimestamp(ahora, tz=timezone.utc).isoformat()
    fallback = []
    for idx, nodo in enumerate(distrito.get("intersecciones", [])):
        nx, ny = nodo["pos"]
        ciclo = (ahora + idx * 4) % 25
        fase_ns = "verde" if ciclo < 10 else ("amarillo" if ciclo < 15 else "rojo")
        fase_eo = "rojo"  if ciclo < 10 else ("amarillo" if ciclo < 15 else "verde")
        for direccion, estado in [("NS", fase_ns), ("SN", fase_ns),
                                   ("EO", fase_eo), ("OE", fase_eo)]:
            fallback.append({
                "mapa_clave": distrito.get("clave", "centro"),
                "interseccion_id": f"fallback-{idx}-{nx}-{ny}",
                "interseccion_nombre": nodo.get("nombre", f"NODO {idx}"),
                "pos_x": nx, "pos_y": ny,
                "direccion": direccion, "estado": estado,
                "tiempo_verde": 10, "tiempo_amarillo": 5, "tiempo_rojo": 10,
                "activo": True, "modo": "fallback_local", "id": -1,
                "updated_at": ahora_iso,
            })
    return _fijar_anclas_semaforos(fallback)


def _adaptar_semaforos_a_distrito(semaforos: List[dict], distrito: dict) -> List[dict]:
    """
    Los semáforos de la API tienen coordenadas de su propio distrito
    (ej. 'oeste': pos_x=250, pos_y=250/550).
    Cuando los usamos en un distrito distinto (ej. 'centro' con
    intersecciones en 250,250 / 520,250 / 250,540 / 520,540), necesitamos
    reasignar cada semáforo a la intersección más cercana del distrito activo,
    para que se dibujen en el lugar correcto del mapa.

    La dirección (NS/SN/EO/OE) se mantiene igual porque es independiente
    de las coordenadas — solo las posiciones x/y se ajustan.
    """
    intersecciones = distrito.get("intersecciones", [])
    if not intersecciones:
        return semaforos

    # Calcular intersecciones únicas del distrito destino
    nodos_destino = [(n["pos"][0], n["pos"][1]) for n in intersecciones]

    def nodo_mas_cercano(px, py):
        return min(nodos_destino, key=lambda n: (n[0]-px)**2 + (n[1]-py)**2)

    # Grupo por (pos_x, pos_y) original → reasignar al nodo más cercano
    resultado = []
    clave_dest = distrito.get("clave", "centro")
    for sem in semaforos:
        nx, ny = nodo_mas_cercano(sem.get("pos_x", 0), sem.get("pos_y", 0))
        nuevo = dict(sem)    # copia para no mutar el original
        nuevo["pos_x"]     = nx
        nuevo["pos_y"]     = ny
        nuevo["mapa_clave"] = clave_dest
        resultado.append(nuevo)
    return _fijar_anclas_semaforos(resultado)


def _completar_semaforos(semaforos_api: List[dict], distrito: dict) -> List[dict]:
    """
    La API puede devolver semáforos incompletos (ej. solo 1 de 4 intersecciones).
    Esta función detecta qué intersecciones del distrito NO tienen semáforo
    y genera semáforos locales solo para esas, complementando los reales de la API.
    Así siempre hay semáforos en TODAS las intersecciones del mapa.
    """
    intersecciones = distrito.get("intersecciones", [])
    if not intersecciones:
        return semaforos_api

    # Posiciones que ya tienen semáforo de la API
    pos_con_sem = set(
        (s.get("pos_x"), s.get("pos_y")) for s in semaforos_api
    )

    # Generar semáforos locales solo para intersecciones sin cobertura
    ahora = time.time()
    faltantes = []
    idx_faltante = 0
    for nodo in intersecciones:
        nx, ny = nodo["pos"]
        if (nx, ny) not in pos_con_sem:
            ciclo = (ahora + idx_faltante * 4) % 25
            fase_ns = "verde" if ciclo < 10 else ("amarillo" if ciclo < 15 else "rojo")
            fase_eo = "rojo"  if ciclo < 10 else ("amarillo" if ciclo < 15 else "verde")
            ahora_iso = datetime.fromtimestamp(ahora, tz=timezone.utc).isoformat()
            for direccion, estado in [("NS", fase_ns), ("SN", fase_ns),
                                       ("EO", fase_eo), ("OE", fase_eo)]:
                faltantes.append({
                    "mapa_clave":           distrito.get("clave", "centro"),
                    "interseccion_id":      f"local-{nx}-{ny}",
                    "interseccion_nombre":  nodo.get("nombre", ""),
                    "pos_x": nx, "pos_y": ny,
                    "direccion": direccion,
                    "estado":    estado,
                    "tiempo_verde": 10, "tiempo_amarillo": 5, "tiempo_rojo": 10,
                    "activo": True, "modo": "local_completado", "id": -1,
                    "updated_at": ahora_iso,
                })
            idx_faltante += 1
    if faltantes:
        print(f"[API Semáforos] Completando {len(faltantes)//4} intersecciones "
              f"sin cobertura con semáforos locales.")
    return _fijar_anclas_semaforos(semaforos_api + faltantes)


def cargar_semaforos_api(mapa_clave: str = "centro", distrito: Optional[dict] = None) -> List[dict]:
    """
    Consulta GET /api/semaforos con reintentos automáticos.
    Espera hasta MAX_REINTENTOS × TIMEOUT_POR_INTENTO segundos (120s).

    Estrategia:
    1. Usa semáforos del distrito exacto ('centro') si existen.
    2. Si no, usa el primer distrito disponible y reposiciona sus semáforos.
    3. En ambos casos, COMPLETA con semáforos locales las intersecciones
       que la API no cubrió (la API puede tener datos parciales).
    4. Si la API no responde, genera todos los semáforos localmente.
    """
    global _sem_aviso_logueado

    r = _get_con_reintentos(API_SEMAFOROS_URL, "API Semáforos")
    if r is not None:
        todos = r.json()
        if not isinstance(todos, list):
            print("[API Semáforos] ✗ La respuesta no es una lista.")
        else:
            # Filtrar entradas inválidas de prueba
            todos = [s for s in todos
                     if isinstance(s, dict) and
                     s.get("mapa_clave") not in ("string", None)]

            # 1) Distrito exacto — se devuelve tal cual venga de la API,
            # sin completar automáticamente (eso ahora es un botón manual
            # en la UI: "COMPLETAR SEMÁFOROS", independiente de la API).
            exactos = [s for s in todos if s.get("mapa_clave") == mapa_clave]
            if exactos:
                _sem_aviso_logueado = False
                print(f"[API Semáforos] ✓ {len(exactos)} semáforos de API para '{mapa_clave}'")
                return _fijar_anclas_semaforos(exactos)

            # 2) Usar otro distrito y reubicar (sin completar automático)
            claves = sorted(set(s.get("mapa_clave") for s in todos if s.get("mapa_clave")))
            if claves:
                clave_alt = claves[0]
                sem_alt   = [s for s in todos if s.get("mapa_clave") == clave_alt]
                adaptados = _adaptar_semaforos_a_distrito(sem_alt, distrito) if distrito else sem_alt
                if not _sem_aviso_logueado:
                    print(f"[API Semáforos] ✓ Usando '{clave_alt}' ({len(adaptados)} de API) "
                          f"reposicionados en '{mapa_clave}'. Usa el botón "
                          f"'COMPLETAR SEMÁFOROS' si faltan intersecciones.")
                    _sem_aviso_logueado = True
                return adaptados

            print("[API Semáforos] API respondió pero sin semáforos válidos.")
    else:
        print("[API Semáforos] ✗ No se pudo conectar tras todos los reintentos.")

    # Fallback total: todos los semáforos locales
    if distrito:
        sems_local = generar_semaforos_fallback(distrito)
        print(f"[API Semáforos] Usando {len(sems_local)} semáforos locales.")
        return sems_local
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
    Consulta GET /api/vehiculos (nuestra API local en 127.0.0.1:8001).
    Timeout corto (2s) porque es local: si no responde, no está corriendo.
    Fallback al CSV directo para que la simulación siempre tenga vehículos.
    """
    try:
        print(f"[API Vehículos] Conectando con {API_VEHICULOS_URL}...")
        r = requests.get(API_VEHICULOS_URL, timeout=TIMEOUT_API_LOCAL)
        if r.status_code == 200:
            datos = r.json()
            if datos:  # solo usar si devuelve algo
                print(f"[API Vehículos] ✓ {len(datos)} vehículos recibidos")
                return datos
            print(f"[API Vehículos] API respondió vacía. Usando CSV.")
    except Exception as e:
        tipo = type(e).__name__
        if "Connection" in tipo or "timeout" in str(e).lower():
            print(f"[API Vehículos] ✗ api_vehiculos.py no está corriendo en {API_VEHICULOS_URL}.")
            print(f"[API Vehículos]   → Abre otra terminal y ejecuta: python api_vehiculos.py")
            print(f"[API Vehículos]   → Usando CSV directamente.")
        else:
            print(f"[API Vehículos] ✗ Error ({tipo}). Usando CSV.")

    import os, csv
    base     = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base, "vehiculos.csv")
    flota    = []
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                categoria = row["CATEGORÍA"].strip()
                color     = row["COLOR"].strip()
                cfg       = TIPOS_VEHICULO.get(categoria, TIPOS_VEHICULO["Automóvil"])
                flota.append({
                    "id":              int(row["ID"]),
                    "placa":           row["PLACA"].strip(),
                    "color":           color,
                    "color_hex":       MAPA_COLORES.get(color, "#808080"),
                    "tamaño":          row["TAMAÑO"].strip(),
                    "usuario":         row["USUARIO"].strip(),
                    "chofer":          row["CHOFER"].strip(),
                    "licencia":        row["LICENCIA"].strip(),
                    "soat_vencimiento": row["SOAT VENC."].strip(),
                    "categoria":       categoria,
                    "icono":           cfg["icono"],
                })
    print(f"[CSV] ✓ Flota cargada: {len(flota)} vehículos")
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


def carril_inicio_aleatorio(carriles: List[CarrilVial], distrito: dict,
                             vehiculos_existentes: Optional[list] = None,
                             intentos_max: int = 25) -> Tuple[CarrilVial, float]:
    """
    Elige un carril y posición inicial aleatoria válida.
    Si se pasa 'vehiculos_existentes' (los VehiculoAgente ya activos en el
    mapa), se evita colocar el nuevo vehículo solapado con alguno de ellos
    — sin esto, dos vehículos podían nacer ya "chocados" desde el spawn,
    lo que rompía la anti-colisión (que está pensada para frenar ante un
    vehículo que se acerca, no para separar vehículos que ya nacen encima).
    """
    if not carriles:
        return None, 0.0

    DIST_SEGURA_SPAWN = 70   # separación mínima al nacer, en px

    for _ in range(intentos_max):
        c = random.choice(carriles)
        margen = 60
        lo = min(c.rango_ini, c.rango_fin) + margen
        hi = max(c.rango_ini, c.rango_fin) - margen
        pos = random.uniform(lo, hi) if hi > lo else (lo + hi) / 2

        if not vehiculos_existentes:
            return c, pos

        # Verificar que no quede demasiado cerca de ningún vehículo ya
        # presente en el MISMO carril físico.
        choque = False
        for v in vehiculos_existentes:
            oc = v.carril_actual
            if oc.orient != c.orient:
                continue
            if abs(oc.coord_fija - c.coord_fija) > 4:
                continue
            otra_pos = v.x if c.orient == "H" else v.y
            if abs(otra_pos - pos) < DIST_SEGURA_SPAWN:
                choque = True
                break
        if not choque:
            return c, pos

    # Si tras varios intentos no se encontró hueco libre, se usa la última
    # posición probada de todos modos (mejor spawnear con algo de riesgo
    # que no spawnear nunca si el mapa está muy lleno).
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
        self.bloqueado_colision = False

        # Watchdog anti-atasco: cuenta ticks consecutivos casi sin movimiento.
        # Si un vehículo lleva demasiado tiempo detenido SIN estar bloqueado
        # por colisión real (solo por ejemplo esperando semáforo desde una
        # posición rara), se le permite un pequeño avance de cortesía para
        # que nunca quede pegado de forma permanente en el mapa.
        self._ticks_sin_mover = 0
        self.TICKS_ATASCO_MAX = 240   # ~4 segundos a 60fps
        self._inmune_semaforo_ticks = 0   # ticks restantes ignorando semáforos

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
        if self._inmune_semaforo_ticks > 0:
            # Vehículo en ventana de inmunidad tras el watchdog anti-atasco:
            # avanza libremente unos instantes para despegarse del punto
            # donde quedó detenido, en vez de volver a frenar en el acto.
            self.bloqueado_sem = False
            return

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

    # ── cambio al carril de regreso al llegar al borde del mapa ──────────────
    def _cambiar_a_carril_regreso(self):
        """
        Se ejecuta cuando el vehículo toca el borde físico del mapa.
        Busca, dentro de la lista de carriles, el carril de la MISMA
        avenida (mismo eje H o V, mismo coord_fija aproximado del lado
        contrario) pero con sentido OPUESTO, y se cambia a él — exactamente
        como si el vehículo diera la vuelta en la esquina de la cuadra y
        retomara la circulación por el carril de regreso, en vez de quedar
        congelado esperando una intersección que puede no existir en ese borde.
        """
        c = self.carril_actual
        candidatos = [
            carril for carril in self.carriles
            if carril.orient == c.orient and carril.sentido == -c.sentido
        ]
        if not candidatos:
            # No hay carril de regreso disponible (mapa con una sola vía):
            # como último recurso, simplemente invierte el sentido lógico
            # del propio carril para no quedar nunca parado sin salida.
            self.vel = 0.3
            return

        # Elegir el carril de regreso más cercano en la otra coordenada
        candidatos.sort(key=lambda k: abs(
            (k.coord_fija - c.coord_fija) if c.orient == "H" else (k.coord_fija - c.coord_fija)
        ))
        nuevo = candidatos[0]
        self.carril_actual = nuevo
        if nuevo.orient == "H":
            self.y = float(nuevo.coord_fija)
        else:
            self.x = float(nuevo.coord_fija)
        self.angulo = self._angulo_carril(nuevo)
        # Mantener algo de velocidad para que el vehículo siga circulando
        # de inmediato, en vez de arrancar desde cero otra vez.
        self.vel = max(0.6, abs(self.vel) * 0.6)

    # ── giro en intersección ─────────────────────────────────────────────────
    def _intentar_giro(self, vehiculos_cercanos: Optional[list] = None):
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

        # ── Verificación de espacio antes de comprometerse al giro ──────────
        # Si el carril destino ya tiene otro vehículo justo en el punto
        # donde aterrizaría self, el giro se pospone (se mantiene la
        # intención activa para reintentar el próximo tick) en vez de
        # ejecutarse y depender de que el clamp resuelva un solapamiento
        # ya consumado. Esto evita el caso límite de 3+ vehículos muy
        # juntos donde no hay espacio matemáticamente suficiente.
        if vehiculos_cercanos:
            destino = self.x if mejor.orient == "V" else self.y
            for v in vehiculos_cercanos:
                if v is self:
                    continue
                oc = v.carril_actual
                if oc is not mejor and not (oc.orient == mejor.orient and
                                            oc.sentido == mejor.sentido and
                                            abs(oc.coord_fija - mejor.coord_fija) <= 4):
                    continue
                pos_v = v.x if mejor.orient == "V" else v.y
                if abs(pos_v - destino) < (self.largo / 2 + v.largo / 2):
                    return   # sin espacio: no gira este tick, reintenta luego

        self.carril_actual = mejor
        if mejor.orient == "V":
            self.x = float(mejor.coord_fija)
        else:
            self.y = float(mejor.coord_fija)
        self.angulo = self._angulo_carril(mejor)
        self.vel    = max(0.4, self.vel * 0.65)
        self._giro_izq = self._giro_der = False

    # ── física principal ─────────────────────────────────────────────────────
    def actualizar(self, semaforos: List[dict], vehiculos_cercanos: Optional[list] = None):
        """
        vehiculos_cercanos: lista de los OTROS VehiculoAgente activos en el mapa.
        Se usa para anti-colisión: si hay otro vehículo adelante, en el mismo
        carril, dentro de la distancia de seguridad, este vehículo frena.
        """
        cfg = self.tipo_config
        if not self.controlado_usuario:
            self._ia_npc()

        if self._inmune_semaforo_ticks > 0:
            self._inmune_semaforo_ticks -= 1

        self.verificar_semaforo(semaforos)

        # ── Anti-colisión: detectar vehículo adelante en el mismo carril ────
        self.bloqueado_colision = False
        if vehiculos_cercanos:
            self._verificar_colision(vehiculos_cercanos)

        bloqueo_total = self.bloqueado_sem or self.bloqueado_colision
        if bloqueo_total and self.vel > 0:
            factor_frenado = cfg["frenado"] * (2.2 if self.bloqueado_colision else 1.8)
            self.vel = max(0.0, self.vel - factor_frenado)
            self.frenando = True
        else:
            self.frenando = bloqueo_total

        # ── Watchdog anti-atasco ─────────────────────────────────────────────
        # Solo cuenta como "atascado" si está casi sin moverse Y NO es por
        # colisión real con otro vehículo (eso sí debe respetarse siempre,
        # o causaríamos choques). Si el bloqueo es por semáforo en un punto
        # donde igual no hay riesgo de colisión, se permite avance de cortesía.
        if abs(self.vel) < 0.05 and not self.bloqueado_colision:
            self._ticks_sin_mover += 1
        else:
            self._ticks_sin_mover = 0

        if self._ticks_sin_mover > self.TICKS_ATASCO_MAX:
            self.vel = max(self.vel, 0.5)
            self.bloqueado_sem = False
            self._ticks_sin_mover = 0
            # Ventana de ~120 ticks (≈2s a 60fps) donde el vehículo ignora
            # semáforos para alejarse del punto de atasco. La distancia de
            # seguridad con otros vehículos (bloqueado_colision) NUNCA se
            # desactiva aquí, así que esto no provoca choques — solo libera
            # atascos por semáforo cuando el vehículo quedó detenido
            # demasiado tiempo en un punto sin riesgo de colisión real.
            self._inmune_semaforo_ticks = 120

        if self.vel > 0:
            self.vel = max(0.0, self.vel - cfg["friccion"])
        elif self.vel < 0:
            self.vel = min(0.0, self.vel + cfg["friccion"])
        self.vel = max(-cfg["vel_max_rev"], min(cfg["vel_max"], self.vel))

        self._intentar_giro(vehiculos_cercanos)

        c = self.carril_actual
        ds = self.vel * c.sentido
        px, py = self.x, self.y
        if c.orient == "H":
            self.x += ds; self.y = float(c.coord_fija)
        else:
            self.y += ds; self.x = float(c.coord_fija)

        # ── Límite del mapa: cuando un vehículo llega al final físico de su
        # carril (el extremo del mapa, no necesariamente una intersección),
        # NO existe forma de seguir avanzando en ese mismo carril porque cada
        # carril tiene un único sentido fijo. La solución correcta es
        # cambiarlo al carril de regreso de la MISMA avenida (mismo eje,
        # sentido opuesto), simulando que da la vuelta en la cuadra y
        # continúa circulando — así nunca queda atascado esperando una
        # intersección que puede no estar cerca de ese borde.
        m = 12
        tocando_borde = False
        if self.x < m:        self.x = m;        tocando_borde = True
        if self.x > self.W-m: self.x = self.W-m; tocando_borde = True
        if self.y < m:        self.y = m;        tocando_borde = True
        if self.y > self.H-m: self.y = self.H-m; tocando_borde = True

        if tocando_borde:
            self._cambiar_a_carril_regreso()

        # ── Clamp físico duro anti-solapamiento ──────────────────────────────
        # Se aplica DESPUÉS de cualquier cambio de carril (giro en
        # intersección o cambio al carril de regreso en el borde), porque
        # esos "snaps" de posición pueden colocar al vehículo directamente
        # encima de otro que ya esté en el carril destino. El frenado
        # gradual no es suficiente garantía por sí solo — sobre todo con
        # vehículos grandes (Bus/Camioneta) cuyo frenado es lento — así que
        # esta es la última línea de defensa: recorta la posición para que
        # la carrocería NUNCA quede dentro de otro vehículo del mismo carril.
        if vehiculos_cercanos:
            self._aplicar_clamp_anticolision(vehiculos_cercanos)

        ang_obj = self._angulo_carril(c)
        diff = (ang_obj - self.angulo + 180) % 360 - 180
        self.angulo += diff * 0.22

        dist = math.hypot(self.x - px, self.y - py)
        self.distancia_total += dist
        self.vel_max = max(self.vel_max, abs(self.vel))

        self.historial.append((int(self.x), int(self.y)))
        if len(self.historial) > self.MAX_HIST:
            self.historial.pop(0)

    def _aplicar_clamp_anticolision(self, vehiculos_cercanos: list):
        """
        Recorta la posición para que nunca penetre la carrocería de otro
        vehículo del mismo carril. Cubre tanto el caso normal (vehículo
        adelante, mismo sentido de avance) como el caso de un "snap" de
        giro o cambio de carril que coloca al vehículo prácticamente
        encima de otro ya presente.

        Cuando hay VARIOS vehículos en el mismo carril, no basta con
        corregir contra el primero que se encuentre: tras corregir, el
        vehículo podría seguir solapado con otro distinto (esto pasaba con
        3+ vehículos muy juntos en el mismo carril tras un giro). Por eso
        se repite la verificación varias veces, resolviendo en cada pasada
        el solapamiento más severo, hasta quedar libre de conflictos o
        agotar los intentos.
        """
        c = self.carril_actual
        mismo_carril = [
            v for v in vehiculos_cercanos
            if v is not self
            and v.carril_actual.orient == c.orient
            and v.carril_actual.sentido == c.sentido
            and abs(v.carril_actual.coord_fija - c.coord_fija) <= 4
        ]
        if not mismo_carril:
            return

        # Resolución determinista: se prioriza siempre el vehículo que está
        # ADELANTE en el sentido de avance del carril. Esto evita un
        # ciclo de "ping-pong" que podía ocurrir cuando dos vehículos a la
        # vez no dejaban espacio matemáticamente suficiente para encajar
        # a self entre ambos (por ejemplo, tres vehículos muy juntos justo
        # tras un giro) — intentar satisfacer ambas restricciones a la vez
        # en esos casos es imposible, así que se resuelve siempre contra
        # el más relevante (el de adelante) y se acepta, como último
        # recurso en ese escenario límite, un pequeño solape residual con
        # el de atrás antes que oscilar sin converger.
        propia = self.x if c.orient == "H" else self.y

        def en_frente(v):
            ajena = v.x if c.orient == "H" else v.y
            return (ajena - propia) * c.sentido >= 0

        candidatos_frente = [v for v in mismo_carril if en_frente(v)]
        candidatos_atras  = [v for v in mismo_carril if not en_frente(v)]

        def distancia(v):
            ajena = v.x if c.orient == "H" else v.y
            return abs(ajena - propia)

        objetivo = None
        if candidatos_frente:
            objetivo = min(candidatos_frente, key=distancia)
        elif candidatos_atras:
            objetivo = min(candidatos_atras, key=distancia)
        if objetivo is None:
            return

        min_gap = self.largo / 2 + objetivo.largo / 2
        ajena = objetivo.x if c.orient == "H" else objetivo.y
        diff = propia - ajena
        if abs(diff) >= min_gap:
            return   # sin solapamiento real con el vehículo prioritario
        nueva = ajena + (min_gap if diff >= 0 else -min_gap)
        if c.orient == "H":
            self.x = nueva
        else:
            self.y = nueva
        self.vel = 0.0

    def _verificar_colision(self, vehiculos_cercanos: list):
        """
        Revisa si hay otro vehículo ADELANTE, en el MISMO carril (misma
        orientación, mismo coord_fija aproximado, mismo sentido), dentro
        de la distancia de seguridad. Si lo hay, marca bloqueado_colision.

        La distancia de seguridad se calcula con la física real de frenado:
        mitad de cada carrocería + un colchón fijo + la distancia que el
        propio vehículo necesitaría para frenar del todo a su velocidad
        actual (v² / (2·frenado)), que es lo que evita que dos vehículos
        terminen solapados cuando van casi a la misma velocidad — un
        margen que solo dependiera de 'vel*6' no escala correctamente con
        la capacidad real de frenado de cada tipo (un Bus frena mucho más
        lento que una Motocicleta, así que necesita más espacio).
        """
        c = self.carril_actual
        cfg = self.tipo_config
        for otro in vehiculos_cercanos:
            if otro is self:
                continue
            oc = otro.carril_actual
            if oc.orient != c.orient or oc.sentido != c.sentido:
                continue
            if abs(oc.coord_fija - c.coord_fija) > 4:
                continue

            if c.orient == "H":
                dist_centros = (otro.x - self.x) * c.sentido
            else:
                dist_centros = (otro.y - self.y) * c.sentido

            # Distancia real entre parachoques (no entre centros).
            gap = dist_centros - (self.largo / 2 + otro.largo / 2)

            # Margen de seguridad: un colchón fijo (espacio mínimo siempre
            # presente, incluso con ambos vehículos detenidos) más un
            # término proporcional a la propia velocidad (para frenar con
            # antelación cuando se viaja rápido). A diferencia de un cálculo
            # de "distancia de frenado pura" (vel²/2·frenado), que se
            # reduce a casi 0 apenas el vehículo decelera un poco —
            # permitiendo que seguidores lentos sigan "reptando" hacia un
            # vehículo detenido adelante hasta solaparse — este margen
            # nunca baja de COLCHON_MINIMO, así que dos vehículos jamás
            # quedan a menos de esa distancia sin importar qué tan lento
            # vaya cada uno.
            COLCHON_MINIMO = 16
            margen_por_velocidad = abs(self.vel) * 10
            distancia_seguridad = COLCHON_MINIMO + margen_por_velocidad

            if 0 <= gap < distancia_seguridad:
                self.bloqueado_colision = True
                return
            # Si el gap ya es negativo (las carrocerías están solapadas por
            # cualquier motivo, por ejemplo justo tras un giro), frenar
            # SIEMPRE de inmediato sin importar la distancia de frenado.
            if gap < 0:
                self.bloqueado_colision = True
                return
                return


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