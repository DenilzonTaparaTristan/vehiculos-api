# -*- coding: utf-8 -*-
"""
=====================================================================
  API AGENTE VEHÍCULO — api_vehiculos.py  (v3.0 — con persistencia)
  Sistema Multi-Agente de Tráfico Urbano

  Diseñada para tener el mismo nivel de sofisticación que la API de
  Semáforos del equipo (https://semaforos.onrender.com/api/semaforos):
    - Persistencia real (SQLite) en vez de un CSV de solo lectura.
    - CRUD completo: crear, leer, actualizar y eliminar vehículos.
    - Timestamps created_at / updated_at en cada registro.
    - IDs autogenerados por la base de datos.
    - Filtros por query string (categoria, mapa_clave, activo).
    - Soporte multi-distrito por vehículo (mapa_clave), igual que
      los semáforos tienen mapa_clave por intersección.

  Otras APIs del equipo:
    - Agente Catastro/Mapas:  https://tecnologia-atkj.onrender.com/api/mapas
    - Agente Semáforos:       https://semaforos.onrender.com/api/semaforos

  ───────────────────────────────────────────────────────────────────
  CÓMO EJECUTAR:
  ───────────────────────────────────────────────────────────────────
  1. Abre una terminal EN ESTA CARPETA (cd hasta aquí).
  2. Ejecuta:  python api_vehiculos.py
  3. Espera "Uvicorn running on http://0.0.0.0:8001"
  4. Abre en el navegador: http://127.0.0.1:8001/docs

  La primera vez que corre, crea vehiculos.db (SQLite) y lo llena
  con los 40 vehículos del CSV. En corridas siguientes, usa lo que
  ya esté en vehiculos.db — así los cambios hechos vía POST/PUT/DELETE
  persisten entre reinicios (mientras el disco de Render no se borre
  en un nuevo deploy; ver nota al final del archivo).
  ───────────────────────────────────────────────────────────────────
"""

import os
import sys
import csv
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# ════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ════════════════════════════════════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "vehiculos.csv")
DB_PATH  = os.path.join(BASE_DIR, "vehiculos.db")

PUERTO = int(os.environ.get("PORT", 8001))

API_MAPAS_URL     = "https://tecnologia-atkj.onrender.com/api/mapas"
API_SEMAFOROS_URL = "https://semaforos.onrender.com/api/semaforos"

CATEGORIAS_VALIDAS = ["Automóvil", "Camioneta", "Bus", "Motocicleta"]

MAPA_COLORES = {
    "Amarillo": "#FFD700", "Azul": "#2255CC", "Beige": "#D4B896",
    "Blanco": "#F0F0F0", "Dorado": "#D4A017", "Gris": "#808080",
    "Marrón": "#8B4513", "Naranja": "#FF7700", "Negro": "#1A1A1A",
    "Plateado": "#B0B0B8", "Rojo": "#CC2233", "Verde": "#228B22",
}

TIPOS_VEHICULO = {
    "Motocicleta": {"largo": 18, "ancho": 9,  "vel_max_kmh": 144, "icono": "🏍"},
    "Automóvil":   {"largo": 28, "ancho": 14, "vel_max_kmh": 105, "icono": "🚗"},
    "Camioneta":   {"largo": 34, "ancho": 16, "vel_max_kmh": 84,  "icono": "🚙"},
    "Bus":         {"largo": 46, "ancho": 18, "vel_max_kmh": 60,  "icono": "🚌"},
}


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════════════════════
#  CAPA DE PERSISTENCIA (SQLite)
# ════════════════════════════════════════════════════════════════════════════
@contextmanager
def get_db():
    """Context manager de conexión SQLite con row_factory tipo dict."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Crea la tabla de vehículos si no existe."""
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS vehiculos (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                placa             TEXT UNIQUE NOT NULL,
                color             TEXT NOT NULL,
                tamaño            TEXT,
                usuario           TEXT,
                chofer            TEXT,
                licencia          TEXT,
                soat_vencimiento  TEXT,
                categoria         TEXT NOT NULL,
                mapa_clave        TEXT NOT NULL DEFAULT 'centro',
                activo            INTEGER NOT NULL DEFAULT 1,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            )
        """)


def seed_desde_csv_si_vacio():
    """La primera vez que corre la API, si la tabla está vacía, la llena
    con los 40 vehículos del CSV. En corridas siguientes no vuelve a
    tocar nada — los datos reales viven en vehiculos.db a partir de ahí."""
    with get_db() as db:
        cur = db.execute("SELECT COUNT(*) AS n FROM vehiculos")
        if cur.fetchone()["n"] > 0:
            return   # ya poblada, no volver a sembrar

        if not os.path.exists(CSV_PATH):
            print(f"[DB] Advertencia: no se encontró {CSV_PATH} para sembrar datos.")
            return

        ahora = _ahora()
        filas = []
        with open(CSV_PATH, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                filas.append((
                    row["PLACA"].strip(),
                    row["COLOR"].strip(),
                    row["TAMAÑO"].strip(),
                    row["USUARIO"].strip(),
                    row["CHOFER"].strip(),
                    row["LICENCIA"].strip(),
                    row["SOAT VENC."].strip(),
                    row["CATEGORÍA"].strip(),
                    "centro",   # mapa_clave por defecto
                    1,          # activo
                    ahora, ahora,
                ))
        db.executemany("""
            INSERT INTO vehiculos
                (placa, color, tamaño, usuario, chofer, licencia,
                 soat_vencimiento, categoria, mapa_clave, activo,
                 created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, filas)
        print(f"[DB] Sembrados {len(filas)} vehículos desde {CSV_PATH} en {DB_PATH}")


def serializar(row: sqlite3.Row) -> dict:
    """Convierte una fila de la BD en el dict de respuesta enriquecido
    (con color_hex, icono, dimensiones — calculados, no guardados en BD
    para no duplicar la fuente de verdad de TIPOS_VEHICULO/MAPA_COLORES)."""
    d = dict(row)
    color = d.get("color", "Gris")
    cat   = d.get("categoria", "Automóvil")
    cfg   = TIPOS_VEHICULO.get(cat, TIPOS_VEHICULO["Automóvil"])
    d["color_hex"]         = MAPA_COLORES.get(color, "#808080")
    d["icono"]             = cfg["icono"]
    d["largo_px"]          = cfg["largo"]
    d["ancho_px"]          = cfg["ancho"]
    d["velocidad_max_kmh"] = cfg["vel_max_kmh"]
    d["activo"]            = bool(d["activo"])
    return d


init_db()
seed_desde_csv_si_vacio()
with get_db() as _db:
    _TOTAL_INICIAL = _db.execute("SELECT COUNT(*) AS n FROM vehiculos").fetchone()["n"]
print(f"[INIT] Vehículos en base de datos: {_TOTAL_INICIAL} (archivo: {DB_PATH})")


# ════════════════════════════════════════════════════════════════════════════
#  ESTADO EN MEMORIA (posiciones en vivo — cambia muchas veces por segundo,
#  se mantiene en RAM por rendimiento; el catálogo de vehículos sí es
#  persistente en SQLite, pero la posición X/Y en tiempo real no necesita
#  sobrevivir a un reinicio del servidor)
# ════════════════════════════════════════════════════════════════════════════
ESTADO_SIMULACION = {
    "activos": [],
    "posiciones": {},
    "controlado_por_usuario": None,
    "actualizado_en": _ahora(),
}


# ════════════════════════════════════════════════════════════════════════════
#  SCHEMAS (Pydantic)
# ════════════════════════════════════════════════════════════════════════════
class Vehiculo(BaseModel):
    """Registro completo de un vehículo, incluyendo campos calculados."""
    id: int = Field(..., examples=[3])
    placa: str = Field(..., examples=["MNO928"])
    color: str = Field(..., examples=["Blanco"])
    color_hex: str = Field(..., examples=["#F0F0F0"])
    tamaño: Optional[str] = None
    usuario: Optional[str] = None
    chofer: Optional[str] = None
    licencia: Optional[str] = None
    soat_vencimiento: Optional[str] = None
    categoria: str = Field(..., examples=["Automóvil"])
    mapa_clave: str = Field("centro", description="Distrito al que está asignado este vehículo")
    activo: bool = Field(True, description="Si el vehículo está disponible para usarse en la simulación")
    icono: str
    largo_px: int
    ancho_px: int
    velocidad_max_kmh: int
    created_at: str = Field(..., description="Fecha de creación del registro (ISO 8601 UTC)")
    updated_at: str = Field(..., description="Fecha de la última modificación (ISO 8601 UTC)")


class VehiculoCreate(BaseModel):
    """Datos requeridos para registrar un vehículo nuevo."""
    placa:            str = Field(..., examples=["ZZZ999"])
    color:            str = Field(..., examples=["Rojo"])
    categoria:        str = Field(..., examples=["Automóvil"])
    tamaño:           Optional[str] = None
    usuario:          Optional[str] = None
    chofer:           Optional[str] = None
    licencia:         Optional[str] = None
    soat_vencimiento: Optional[str] = None
    mapa_clave:       str = Field("centro", description="Distrito donde se registra el vehículo")


class VehiculoUpdate(BaseModel):
    """Todos los campos son opcionales: solo se actualizan los que se envíen (PATCH-like PUT)."""
    placa:            Optional[str] = None
    color:            Optional[str] = None
    categoria:        Optional[str] = None
    tamaño:           Optional[str] = None
    usuario:          Optional[str] = None
    chofer:           Optional[str] = None
    licencia:         Optional[str] = None
    soat_vencimiento: Optional[str] = None
    mapa_clave:       Optional[str] = None
    activo:           Optional[bool] = None


class TipoVehiculoInfo(BaseModel):
    largo: int
    ancho: int
    vel_max_kmh: int
    icono: str


class PosicionVehiculo(BaseModel):
    id: int = Field(..., examples=[3])
    x: float = Field(..., examples=[458.5])
    y: float = Field(..., examples=[232.0])
    angulo: float = Field(..., examples=[0.0])
    velocidad: float = Field(..., examples=[1.2])
    mapa_clave: Optional[str] = "centro"


class EstadoActivos(BaseModel):
    activos: List[int]
    posiciones: dict
    controlado_por_usuario: Optional[int] = None


class EstadoSimulacion(BaseModel):
    activos: List[int]
    posiciones: dict
    controlado_por_usuario: Optional[int]
    actualizado_en: str


class RespuestaOk(BaseModel):
    ok: bool


class RespuestaSincronizacion(RespuestaOk):
    vehiculos_activos: int


class InfoAPI(BaseModel):
    api: str
    version: str
    estado: str
    total_vehiculos: int
    endpoints: List[str]
    docs: str
    apis_relacionadas: dict


# ════════════════════════════════════════════════════════════════════════════
#  TAGS
# ════════════════════════════════════════════════════════════════════════════
TAGS_METADATA = [
    {"name": "Vehículos",     "description": "Catálogo de vehículos con persistencia real en SQLite. Soporta CRUD completo (crear/leer/editar/eliminar)."},
    {"name": "Estado en vivo","description": "Posiciones en tiempo real de los vehículos circulando en la simulación."},
    {"name": "Sistema",       "description": "Healthcheck y metadatos generales de la API."},
]

app = FastAPI(
    title="API Agente Vehículo — Sistema MAS de Tráfico Urbano",
    description=(
        "## Módulo de Vehículos (v3 — con persistencia SQLite)\n\n"
        "CRUD completo sobre la flota de vehículos, con timestamps y "
        "soporte multi-distrito (`mapa_clave`), en el mismo espíritu que "
        "la API de Semáforos del equipo.\n\n"
        "- 🗺️ Mapas: `https://tecnologia-atkj.onrender.com/api/mapas`\n"
        "- 🚦 Semáforos: `https://semaforos.onrender.com/api/semaforos`"
    ),
    version="3.0.0",
    contact={"name": "Agente Vehículo — Sistema MAS"},
    openapi_tags=TAGS_METADATA,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ════════════════════════════════════════════════════════════════════════════
#  VEHÍCULOS — LECTURA
#  Orden de rutas: literales ANTES que "/{id}" (ver nota de FastAPI abajo).
# ════════════════════════════════════════════════════════════════════════════
@app.get(
    "/api/vehiculos", tags=["Vehículos"],
    summary="Lista de vehículos (con filtros opcionales)",
    response_model=List[Vehiculo],
)
def get_vehiculos(
    categoria:  Optional[str]  = Query(None, description="Filtrar por categoría exacta"),
    mapa_clave: Optional[str]  = Query(None, description="Filtrar por distrito asignado"),
    activo:     Optional[bool] = Query(None, description="Filtrar solo activos (true) o inactivos (false)"),
):
    sql = "SELECT * FROM vehiculos WHERE 1=1"
    params = []
    if categoria:
        sql += " AND LOWER(categoria) = LOWER(?)"
        params.append(categoria)
    if mapa_clave:
        sql += " AND mapa_clave = ?"
        params.append(mapa_clave)
    if activo is not None:
        sql += " AND activo = ?"
        params.append(1 if activo else 0)
    sql += " ORDER BY id"
    with get_db() as db:
        filas = db.execute(sql, params).fetchall()
    return [serializar(f) for f in filas]


#  IMPORTANTE — ORDEN DE RUTAS: FastAPI evalúa las rutas en el orden en
#  que se declaran. "/api/vehiculos/{id}" es un comodín que aceptaría
#  "tipos", "colores", etc. como si fueran un id — por eso TODAS las
#  rutas literales van declaradas antes que la ruta con parámetro {id}.

@app.get(
    "/api/vehiculos/categoria/{categoria}", tags=["Vehículos"],
    summary="Filtrar vehículos por categoría (ruta explícita)",
    response_model=List[Vehiculo],
    responses={404: {"description": "No existen vehículos para esa categoría"}},
)
def get_por_categoria(categoria: str):
    with get_db() as db:
        filas = db.execute(
            "SELECT * FROM vehiculos WHERE LOWER(categoria)=LOWER(?) ORDER BY id",
            (categoria,)
        ).fetchall()
    if not filas:
        raise HTTPException(404, f"Sin resultados para '{categoria}'. Válidas: {CATEGORIAS_VALIDAS}")
    return [serializar(f) for f in filas]


@app.get(
    "/api/vehiculos/mapa/{mapa_clave}", tags=["Vehículos"],
    summary="Vehículos asignados a un distrito",
    description="Devuelve los vehículos cuyo `mapa_clave` coincide con el distrito indicado.",
    response_model=List[Vehiculo],
)
def get_por_mapa(mapa_clave: str):
    with get_db() as db:
        filas = db.execute(
            "SELECT * FROM vehiculos WHERE mapa_clave=? ORDER BY id", (mapa_clave,)
        ).fetchall()
    return [serializar(f) for f in filas]


@app.get(
    "/api/vehiculos/tipos", tags=["Vehículos"],
    summary="Parámetros de los 4 tipos de vehículo",
    response_model=dict[str, TipoVehiculoInfo],
)
def get_tipos():
    return TIPOS_VEHICULO


@app.get(
    "/api/vehiculos/colores", tags=["Vehículos"],
    summary="Mapeo de colores a hexadecimal",
    response_model=dict[str, str],
)
def get_colores():
    return MAPA_COLORES


# ════════════════════════════════════════════════════════════════════════════
#  ESTADO EN VIVO
# ════════════════════════════════════════════════════════════════════════════
@app.get(
    "/api/vehiculos/estado/actual", tags=["Estado en vivo"],
    summary="Estado actual de la simulación",
    response_model=EstadoSimulacion,
)
def get_estado():
    ESTADO_SIMULACION["actualizado_en"] = _ahora()
    return ESTADO_SIMULACION


@app.post(
    "/api/vehiculos/estado/actualizar", tags=["Estado en vivo"],
    summary="Sincronizar el estado completo de vehículos activos",
    response_model=RespuestaSincronizacion,
)
def post_estado(data: EstadoActivos):
    ESTADO_SIMULACION["activos"]                 = data.activos
    ESTADO_SIMULACION["posiciones"]               = data.posiciones
    ESTADO_SIMULACION["controlado_por_usuario"]   = data.controlado_por_usuario
    ESTADO_SIMULACION["actualizado_en"]            = _ahora()
    return {"ok": True, "vehiculos_activos": len(data.activos)}


@app.post(
    "/api/vehiculos/estado/posicion", tags=["Estado en vivo"],
    summary="Actualizar la posición de un solo vehículo",
    response_model=RespuestaOk,
)
def post_posicion(pos: PosicionVehiculo):
    ESTADO_SIMULACION["posiciones"][str(pos.id)] = {
        "x": pos.x, "y": pos.y, "angulo": pos.angulo,
        "velocidad": pos.velocidad, "mapa_clave": pos.mapa_clave,
    }
    if pos.id not in ESTADO_SIMULACION["activos"]:
        ESTADO_SIMULACION["activos"].append(pos.id)
    ESTADO_SIMULACION["actualizado_en"] = _ahora()
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
#  VEHÍCULOS — ESCRITURA (CRUD)
# ════════════════════════════════════════════════════════════════════════════
@app.post(
    "/api/vehiculos", tags=["Vehículos"], status_code=201,
    summary="Registrar un vehículo nuevo",
    description="Crea un vehículo con id autogenerado y timestamps. La `placa` debe ser única.",
    response_model=Vehiculo,
    responses={409: {"description": "Ya existe un vehículo con esa placa"}},
)
def crear_vehiculo(datos: VehiculoCreate):
    if datos.categoria not in CATEGORIAS_VALIDAS:
        raise HTTPException(422, f"Categoría inválida. Válidas: {CATEGORIAS_VALIDAS}")
    ahora = _ahora()
    with get_db() as db:
        try:
            cur = db.execute("""
                INSERT INTO vehiculos
                    (placa, color, tamaño, usuario, chofer, licencia,
                     soat_vencimiento, categoria, mapa_clave, activo,
                     created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,1,?,?)
            """, (datos.placa, datos.color, datos.tamaño, datos.usuario,
                  datos.chofer, datos.licencia, datos.soat_vencimiento,
                  datos.categoria, datos.mapa_clave, ahora, ahora))
        except sqlite3.IntegrityError:
            raise HTTPException(409, f"Ya existe un vehículo con placa '{datos.placa}'")
        nuevo_id = cur.lastrowid
        fila = db.execute("SELECT * FROM vehiculos WHERE id=?", (nuevo_id,)).fetchone()
    return serializar(fila)


@app.get(
    "/api/vehiculos/{id}", tags=["Vehículos"],
    summary="Obtener un vehículo por ID",
    response_model=Vehiculo,
    responses={404: {"description": "No existe un vehículo con ese ID"}},
)
def get_vehiculo_por_id(id: int):
    with get_db() as db:
        fila = db.execute("SELECT * FROM vehiculos WHERE id=?", (id,)).fetchone()
    if fila is None:
        raise HTTPException(404, f"Vehículo {id} no encontrado")
    return serializar(fila)


@app.put(
    "/api/vehiculos/{id}", tags=["Vehículos"],
    summary="Actualizar un vehículo existente",
    description="Solo se actualizan los campos incluidos en el body; el resto se conserva igual.",
    response_model=Vehiculo,
    responses={404: {"description": "No existe un vehículo con ese ID"},
               409: {"description": "La placa ya está en uso por otro vehículo"}},
)
def actualizar_vehiculo(id: int, datos: VehiculoUpdate):
    campos = datos.model_dump(exclude_unset=True)
    if not campos:
        raise HTTPException(422, "No se envió ningún campo para actualizar")
    if "categoria" in campos and campos["categoria"] not in CATEGORIAS_VALIDAS:
        raise HTTPException(422, f"Categoría inválida. Válidas: {CATEGORIAS_VALIDAS}")

    with get_db() as db:
        existe = db.execute("SELECT id FROM vehiculos WHERE id=?", (id,)).fetchone()
        if existe is None:
            raise HTTPException(404, f"Vehículo {id} no encontrado")

        if "activo" in campos:
            campos["activo"] = 1 if campos["activo"] else 0

        campos["updated_at"] = _ahora()
        set_clause = ", ".join(f"{k}=?" for k in campos)
        valores = list(campos.values()) + [id]
        try:
            db.execute(f"UPDATE vehiculos SET {set_clause} WHERE id=?", valores)
        except sqlite3.IntegrityError:
            raise HTTPException(409, f"La placa '{campos.get('placa')}' ya está en uso")

        fila = db.execute("SELECT * FROM vehiculos WHERE id=?", (id,)).fetchone()
    return serializar(fila)


@app.delete(
    "/api/vehiculos/{id}", tags=["Vehículos"],
    summary="Eliminar un vehículo",
    response_model=RespuestaOk,
    responses={404: {"description": "No existe un vehículo con ese ID"}},
)
def eliminar_vehiculo(id: int):
    with get_db() as db:
        existe = db.execute("SELECT id FROM vehiculos WHERE id=?", (id,)).fetchone()
        if existe is None:
            raise HTTPException(404, f"Vehículo {id} no encontrado")
        db.execute("DELETE FROM vehiculos WHERE id=?", (id,))
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
#  RAÍZ
# ════════════════════════════════════════════════════════════════════════════
@app.get("/", tags=["Sistema"], summary="Healthcheck e información general", response_model=InfoAPI)
def root():
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) AS n FROM vehiculos").fetchone()["n"]
    return {
        "api": "Agente Vehículo — Sistema MAS Tráfico",
        "version": "3.0.0",
        "estado": "ok",
        "total_vehiculos": total,
        "endpoints": [
            "GET    /api/vehiculos",
            "POST   /api/vehiculos",
            "GET    /api/vehiculos/{id}",
            "PUT    /api/vehiculos/{id}",
            "DELETE /api/vehiculos/{id}",
            "GET    /api/vehiculos/categoria/{categoria}",
            "GET    /api/vehiculos/mapa/{mapa_clave}",
            "GET    /api/vehiculos/tipos",
            "GET    /api/vehiculos/colores",
            "GET    /api/vehiculos/estado/actual",
            "POST   /api/vehiculos/estado/actualizar",
            "POST   /api/vehiculos/estado/posicion",
        ],
        "docs": f"http://127.0.0.1:{PUERTO}/docs  (en Render: <tu-url>/docs)",
        "apis_relacionadas": {"mapas": API_MAPAS_URL, "semaforos": API_SEMAFOROS_URL},
    }


# ════════════════════════════════════════════════════════════════════════════
#  ARRANQUE
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("  API AGENTE VEHÍCULO — v3.0 (SQLite)")
    print(f"  Base de datos   : {DB_PATH}")
    print(f"  Vehículos en BD : {_TOTAL_INICIAL}")
    print(f"  Puerto          : {PUERTO}")
    print(f"  (Local)  URL    : http://127.0.0.1:{PUERTO}")
    print(f"  (Local)  Docs   : http://127.0.0.1:{PUERTO}/docs")
    print("=" * 60)
    print("  NOTA: en el plan free de Render el disco es efímero entre")
    print("  deploys (redeploy = vehiculos.db se reinicia desde el CSV).")
    print("  Mientras el servicio siga corriendo sin redeploy, los")
    print("  cambios hechos vía POST/PUT/DELETE persisten normalmente.")
    print("=" * 60)

    try:
        uvicorn.run(app, host="0.0.0.0", port=PUERTO, reload=False)
    except OSError as e:
        print(f"\n❌ ERROR al iniciar el servidor: {e}")
        print(f"   Es probable que el puerto {PUERTO} ya esté en uso.")
        sys.exit(1)