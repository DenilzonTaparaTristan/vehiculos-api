# -*- coding: utf-8 -*-
"""
=====================================================================
  API AGENTE VEHÍCULO — api_vehiculos.py
  Sistema Multi-Agente de Tráfico Urbano

  Diseñada para ser GEMELA en estilo a las APIs de los compañeros:
    - Agente Catastro/Mapas:  https://tecnologia-atkj.onrender.com/api/mapas
    - Agente Semáforos:       https://semaforos.onrender.com/api/semaforos

  Esta API expone:    GET /api/vehiculos
  (en el mismo formato JSON plano — lista de objetos — que las otras dos)

  ───────────────────────────────────────────────────────────────────
  CÓMO EJECUTAR (IMPORTANTE — lee esto si la API no responde):
  ───────────────────────────────────────────────────────────────────
  1. Abre una terminal EN ESTA CARPETA (cd hasta aquí).
  2. Ejecuta:
        python api_vehiculos.py
  3. Espera a ver el mensaje "Uvicorn running on http://127.0.0.1:8001"
  4. Recién ahí abre el navegador en http://127.0.0.1:8001/docs

  ❌ ERROR COMÚN (ERR_CONNECTION_REFUSED):
     Si ves esto, significa que el proceso de uvicorn NUNCA llegó a
     levantarse (se cerró por un error de importación, un puerto ocupado,
     o reload=True fallando en tu entorno). Por eso este archivo:
       - NO usa reload=True (causa de fallos silenciosos en muchos PCs)
       - Imprime un mensaje claro de error si algo falla al iniciar
       - Usa el puerto 8001 fijo; si está ocupado, lo dice explícitamente
  ───────────────────────────────────────────────────────────────────
"""

import os
import sys
import csv
import json
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ════════════════════════════════════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "vehiculos.csv")

# Render asigna el puerto dinámicamente vía variable de entorno PORT.
# En local (tu PC) esa variable no existe, así que cae al 8001 de siempre.
PUERTO = int(os.environ.get("PORT", 8001))

# URLs de las APIs de los compañeros (consumidas por nuestro propio agente
# también desde el lado del cliente visual, pero las dejamos aquí centralizadas)
API_MAPAS_URL     = "https://tecnologia-atkj.onrender.com/api/mapas"
API_SEMAFOROS_URL = "https://semaforos.onrender.com/api/semaforos"

# Mapeo de colores del CSV a hexadecimal (para que el front lo use directo)
MAPA_COLORES = {
    "Amarillo": "#FFD700", "Azul": "#2255CC", "Beige": "#D4B896",
    "Blanco": "#F0F0F0", "Dorado": "#D4A017", "Gris": "#808080",
    "Marrón": "#8B4513", "Naranja": "#FF7700", "Negro": "#1A1A1A",
    "Plateado": "#B0B0B8", "Rojo": "#CC2233", "Verde": "#228B22",
}

# Configuración física/visual por categoría (las 4 que pidió el equipo)
TIPOS_VEHICULO = {
    "Motocicleta": {"largo": 18, "ancho": 9,  "vel_max_kmh": 144, "icono": "🏍"},
    "Automóvil":   {"largo": 28, "ancho": 14, "vel_max_kmh": 105, "icono": "🚗"},
    "Camioneta":   {"largo": 34, "ancho": 16, "vel_max_kmh": 84,  "icono": "🚙"},
    "Bus":         {"largo": 46, "ancho": 18, "vel_max_kmh": 60,  "icono": "🚌"},
}


# ════════════════════════════════════════════════════════════════════════════
#  CARGA DE DATOS
# ════════════════════════════════════════════════════════════════════════════
def cargar_vehiculos_csv() -> List[dict]:
    """Lee el CSV y devuelve la lista de vehículos en formato dict plano."""
    if not os.path.exists(CSV_PATH):
        print(f"[ERROR] No se encontró {CSV_PATH}")
        return []

    vehiculos = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            categoria = row.get("CATEGORÍA", "Automóvil").strip()
            color     = row.get("COLOR", "Gris").strip()
            cfg       = TIPOS_VEHICULO.get(categoria, TIPOS_VEHICULO["Automóvil"])

            vehiculos.append({
                "id":               int(row["ID"]),
                "placa":            row["PLACA"].strip(),
                "color":            color,
                "color_hex":        MAPA_COLORES.get(color, "#808080"),
                "tamaño":           row["TAMAÑO"].strip(),
                "usuario":          row["USUARIO"].strip(),
                "chofer":           row["CHOFER"].strip(),
                "licencia":         row["LICENCIA"].strip(),
                "soat_vencimiento": row["SOAT VENC."].strip(),
                "categoria":        categoria,
                "icono":            cfg["icono"],
                "largo_px":         cfg["largo"],
                "ancho_px":         cfg["ancho"],
                "velocidad_max_kmh": cfg["vel_max_kmh"],
            })
    return vehiculos


VEHICULOS_DB = cargar_vehiculos_csv()
print(f"[INIT] Vehículos cargados desde CSV: {len(VEHICULOS_DB)}")


# ════════════════════════════════════════════════════════════════════════════
#  ESTADO EN MEMORIA (posiciones en vivo — análogo al "estado" de semáforos)
# ════════════════════════════════════════════════════════════════════════════
ESTADO_SIMULACION = {
    "activos": [],                 # IDs de vehículos actualmente en el mapa
    "posiciones": {},               # {id: {x, y, angulo, velocidad, mapa_clave}}
    "controlado_por_usuario": None,  # ID del vehículo bajo control del usuario
    "actualizado_en": datetime.now(timezone.utc).isoformat(),
}


# ════════════════════════════════════════════════════════════════════════════
#  SCHEMAS (Pydantic)
# ════════════════════════════════════════════════════════════════════════════
class PosicionVehiculo(BaseModel):
    id: int
    x: float
    y: float
    angulo: float
    velocidad: float
    mapa_clave: Optional[str] = "centro"


class EstadoActivos(BaseModel):
    activos: List[int]
    posiciones: dict
    controlado_por_usuario: Optional[int] = None


# ════════════════════════════════════════════════════════════════════════════
#  APP FASTAPI
# ════════════════════════════════════════════════════════════════════════════
app = FastAPI(
    title="API Agente Vehículo",
    description=(
        "Módulo de vehículos del Sistema Multi-Agente de Tráfico Urbano. "
        "Compatible en formato con las APIs de Mapas y Semáforos del equipo."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ════════════════════════════════════════════════════════════════════════════
#  ENDPOINT PRINCIPAL — mismo patrón que /api/mapas y /api/semaforos
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/vehiculos", summary="Lista plana de vehículos (formato compatible)")
def get_vehiculos():
    """
    Devuelve TODOS los vehículos en una lista plana de objetos JSON,
    igual que hacen /api/mapas y /api/semaforos de los otros agentes.
    """
    return VEHICULOS_DB


#  IMPORTANTE — ORDEN DE RUTAS:
#  FastAPI evalúa las rutas en el orden en que se declaran. Como
#  "/api/vehiculos/{id}" es un comodín que acepta cualquier texto,
#  TODAS las rutas literales (tipos, colores, categoria/..., estado/...)
#  deben declararse ANTES que "/{id}", o de lo contrario FastAPI intentará
#  convertir "tipos", "colores", etc. a un entero y devolverá un error 422.

@app.get("/api/vehiculos/categoria/{categoria}", summary="Filtrar por categoría")
def get_por_categoria(categoria: str):
    matches = [v for v in VEHICULOS_DB
               if v["categoria"].lower() == categoria.lower()]
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"Sin resultados para '{categoria}'. "
                   f"Válidas: {list(TIPOS_VEHICULO.keys())}"
        )
    return matches


@app.get("/api/vehiculos/tipos", summary="Configuración de los 4 tipos de vehículo")
def get_tipos():
    """Dimensiones, velocidad e ícono de cada categoría — para el frontend."""
    return TIPOS_VEHICULO


@app.get("/api/vehiculos/colores", summary="Mapeo color -> hex")
def get_colores():
    return MAPA_COLORES


@app.get("/api/vehiculos/{id}", summary="Vehículo por ID")
def get_vehiculo_por_id(id: int):
    for v in VEHICULOS_DB:
        if v["id"] == id:
            return v
    raise HTTPException(status_code=404, detail=f"Vehículo {id} no encontrado")


# ════════════════════════════════════════════════════════════════════════════
#  ESTADO EN VIVO (posiciones) — análogo a lo que hace /api/semaforos
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/vehiculos/estado/actual", summary="Estado en vivo de la simulación")
def get_estado():
    ESTADO_SIMULACION["actualizado_en"] = datetime.now(timezone.utc).isoformat()
    return ESTADO_SIMULACION


@app.post("/api/vehiculos/estado/actualizar", summary="Sincronizar posiciones")
def post_estado(data: EstadoActivos):
    ESTADO_SIMULACION["activos"]                = data.activos
    ESTADO_SIMULACION["posiciones"]              = data.posiciones
    ESTADO_SIMULACION["controlado_por_usuario"]  = data.controlado_por_usuario
    ESTADO_SIMULACION["actualizado_en"]          = datetime.now(timezone.utc).isoformat()
    return {"ok": True, "vehiculos_activos": len(data.activos)}


@app.post("/api/vehiculos/estado/posicion", summary="Actualizar 1 vehículo")
def post_posicion(pos: PosicionVehiculo):
    ESTADO_SIMULACION["posiciones"][str(pos.id)] = {
        "x": pos.x, "y": pos.y, "angulo": pos.angulo,
        "velocidad": pos.velocidad, "mapa_clave": pos.mapa_clave,
    }
    if pos.id not in ESTADO_SIMULACION["activos"]:
        ESTADO_SIMULACION["activos"].append(pos.id)
    ESTADO_SIMULACION["actualizado_en"] = datetime.now(timezone.utc).isoformat()
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
#  RAÍZ — útil para verificar rápido que el servidor está vivo
# ════════════════════════════════════════════════════════════════════════════
@app.get("/", summary="Healthcheck / info de la API")
def root():
    return {
        "api": "Agente Vehículo — Sistema MAS Tráfico",
        "version": "2.0.0",
        "estado": "ok",
        "total_vehiculos": len(VEHICULOS_DB),
        "endpoints": [
            "GET  /api/vehiculos",
            "GET  /api/vehiculos/{id}",
            "GET  /api/vehiculos/categoria/{categoria}",
            "GET  /api/vehiculos/tipos",
            "GET  /api/vehiculos/colores",
            "GET  /api/vehiculos/estado/actual",
            "POST /api/vehiculos/estado/actualizar",
            "POST /api/vehiculos/estado/posicion",
        ],
        "docs": f"http://127.0.0.1:{PUERTO}/docs  (en Render: <tu-url>/docs)",
        "apis_relacionadas": {
            "mapas":     API_MAPAS_URL,
            "semaforos": API_SEMAFOROS_URL,
        },
    }


# ════════════════════════════════════════════════════════════════════════════
#  ARRANQUE — sin reload=True, con manejo explícito de errores
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn

    if not VEHICULOS_DB:
        print("=" * 60)
        print(" ⚠  ADVERTENCIA: no se cargaron vehículos del CSV.")
        print(f"    Verifica que exista el archivo: {CSV_PATH}")
        print("=" * 60)

    print("=" * 60)
    print("  API AGENTE VEHÍCULO — Sistema MAS Tráfico")
    print(f"  Vehículos en BD : {len(VEHICULOS_DB)}")
    print(f"  Puerto          : {PUERTO}")
    print(f"  (Local)  URL    : http://127.0.0.1:{PUERTO}")
    print(f"  (Local)  Docs   : http://127.0.0.1:{PUERTO}/docs")
    print("=" * 60)

    try:
        # host="0.0.0.0" es OBLIGATORIO para Render (y para cualquier hosting
        # en la nube): significa "escucha en todas las interfaces de red",
        # no solo en localhost. Si usas 127.0.0.1 aquí, Render no podrá
        # enrutar tráfico externo hacia tu app y el deploy fallará el healthcheck.
        uvicorn.run(app, host="0.0.0.0", port=PUERTO, reload=False)
    except OSError as e:
        print(f"\n❌ ERROR al iniciar el servidor: {e}")
        print(f"   Es probable que el puerto {PUERTO} ya esté en uso.")
        print(f"   Cierra cualquier proceso anterior o cambia PUERTO en este archivo.")
        sys.exit(1)