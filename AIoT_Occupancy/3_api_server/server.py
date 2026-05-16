"""
STEP 3 - FastAPI Backend Server (COM Port / Serial Mode)
=========================================================
Reads VL53L0X distance directly from STM32 via USB serial (COM4).
NO WiFi needed - just plug in the USB cable.

Run:
    cd 3_api_server
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload

Change the default COM port at the top of this file if needed.

Endpoints:
    GET  /health            -- health check + serial status
    GET  /stream            -- SSE stream for React live updates
    GET  /history           -- last N readings
    DELETE /history         -- clear history
    POST /predict           -- manual single prediction  {"distance_mm": 423}
    POST /com/connect       -- connect to a COM port     {"port":"COM4","baud":115200}
    POST /com/disconnect    -- disconnect serial
    GET  /com/ports         -- list all available COM ports
"""

import sys
import os
import asyncio
import json
import threading
import time
from datetime import datetime
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "2_train_model"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager

import serial
import serial.tools.list_ports

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG  ← Change your COM port here
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_COM_PORT = "COM4"
DEFAULT_BAUD     = 115200

# ─────────────────────────────────────────────────────────────────────────────
# GLOBALS
# ─────────────────────────────────────────────────────────────────────────────
inference      = None
history        = deque(maxlen=200)
sse_clients    = []
serial_port    = None
serial_thread  = None
serial_running = False
serial_status  = {
    "connected":      False,
    "port":           None,
    "error":          None,
    "readings_count": 0
}

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def parse_distance(raw: str):
    """
    Parse distance and return value in MM.
    Handles ALL common STM32 printf formats:
        Distance: 8.6 cm     -> 86.0 mm   (your board's current format)
        Distance: 86 mm      -> 86.0 mm
        DIST:86              -> 86.0 mm
        distance_mm=86       -> 86.0 mm
        86                   -> 86.0 mm
        86.5                 -> 86.5 mm
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        lo = raw.lower()

        # Format: "Distance: 8.6 cm"  or  "dist: 8.6 cm"
        if "distance" in lo and "cm" in lo:
            val_str = lo.split(":")[1].replace("cm","").strip()
            val = float(val_str.split()[0])
            return round(val * 10.0, 1)   # cm -> mm

        # Format: "Distance: 86 mm"
        if "distance" in lo and "mm" in lo:
            val_str = lo.split(":")[1].replace("mm","").strip()
            return float(val_str.split()[0])

        # Format: "DIST:86"
        if lo.startswith("dist:"):
            return float(raw.split(":")[1].split()[0])

        # Format: "distance_mm=86"
        if "distance_mm=" in lo:
            return float(lo.split("distance_mm=")[1].split()[0])

        # Format: bare number (with optional mm/cm suffix)
        stripped = raw.replace("mm","").replace("cm","").strip()
        if stripped.replace(".","").replace("-","").isdigit():
            val = float(stripped)
            # Heuristic: if value < 30, assume cm (ToF sensors don't read < 30mm)
            if val < 30:
                return round(val * 10.0, 1)
            return val

    except Exception:
        pass
    return None


def broadcast(result: dict):
    """Push a result dict to every connected SSE client."""
    dead = []
    for q in sse_clients:
        try:
            q.put_nowait(result)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        if q in sse_clients:
            sse_clients.remove(q)


def push_reading(distance_mm: float):
    """Run AI inference and broadcast result."""
    if inference is None:
        return
    try:
        result = inference.predict(distance_mm)
        result["timestamp"] = datetime.utcnow().isoformat()
        history.append(result)
        serial_status["readings_count"] += 1
        broadcast(result)
    except Exception as e:
        print(f"[INFER] Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# SERIAL READER (background thread)
# ─────────────────────────────────────────────────────────────────────────────
def serial_reader_thread(port: str, baud: int):
    global serial_port, serial_running, serial_status

    print(f"[SERIAL] Opening {port} at {baud} baud ...")

    # Show all ports for debugging
    available = serial.tools.list_ports.comports()
    print("[SERIAL] Available ports:")
    for p in available:
        print(f"           {p.device}  -  {p.description}")

    ser = None
    for attempt in range(5):
        try:
            ser = serial.Serial(port, baud, timeout=2)
            break
        except serial.SerialException as e:
            err = str(e)
            if "Access is denied" in err or "PermissionError" in err:
                print(f"[SERIAL] ACCESS DENIED on {port} (attempt {attempt+1}/5)")
                print(f"[SERIAL] FIX: Close STM32CubeIDE serial terminal or any")
                print(f"[SERIAL]      other program using {port} (PuTTY, Tera Term etc)")
                print(f"[SERIAL] Retrying in 4 seconds...")
                serial_status["error"] = f"ACCESS DENIED - Close STM32CubeIDE terminal on {port}"
            elif "could not open port" in err.lower() and "filenotfounderror" in err.lower():
                print(f"[SERIAL] Port {port} not found. Check Device Manager.")
                serial_status["error"] = f"Port {port} not found"
                serial_running = False
                return
            else:
                print(f"[SERIAL] Error: {e}")
                serial_status["error"] = err
            import time as _t; _t.sleep(4)

    if ser is None:
        serial_status["connected"] = False
        serial_running = False
        print(f"[SERIAL] Could not open {port} after 5 attempts. Fix the issue and use /com/connect")
        return

    serial_port               = ser
    serial_status["connected"] = True
    serial_status["port"]      = port
    serial_status["error"]     = None
    print(f"[SERIAL] Connected to {port}  OK")

    time.sleep(1.5)          # wait for STM32 to boot / print header
    ser.reset_input_buffer()

    while serial_running:
        try:
            if ser.in_waiting == 0:
                time.sleep(0.02)
                continue

            raw  = ser.readline().decode("utf-8", errors="ignore").strip()
            dist = parse_distance(raw)

            # Always log raw line so user can see what board is printing
            if raw:
                print(f"[STM32]  {repr(raw)}")

            if dist is not None and 30 <= dist <= 2000:
                print(f"[PARSE]  --> {dist:.0f} mm  (matched)")
                push_reading(dist)
            elif raw:
                print(f"[SKIP]   no distance found in this line")

        except serial.SerialException as e:
            print(f"[SERIAL] Read error: {e}")
            serial_status["error"] = str(e)
            break
        except Exception as e:
            print(f"[SERIAL] Unexpected: {e}")
            time.sleep(0.1)

    try:
        ser.close()
    except Exception:
        pass

    serial_status["connected"] = False
    serial_status["port"]      = None
    print("[SERIAL] Port closed")


def start_serial(port: str = DEFAULT_COM_PORT, baud: int = DEFAULT_BAUD):
    global serial_thread, serial_running
    stop_serial()
    serial_running = True
    serial_thread  = threading.Thread(
        target=serial_reader_thread, args=(port, baud), daemon=True)
    serial_thread.start()


def stop_serial():
    global serial_running, serial_port
    serial_running = False
    if serial_port:
        try:
            serial_port.close()
        except Exception:
            pass
        serial_port = None
    if serial_thread and serial_thread.is_alive():
        serial_thread.join(timeout=3)

# ─────────────────────────────────────────────────────────────────────────────
# LIFESPAN
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global inference

    # Load AI models
    try:
        from train_occupancy_model import OccupancyInference
        inference = OccupancyInference()
        print("[API] AI models loaded OK")
    except FileNotFoundError:
        print("[API] Models not found!")
        print("[API] Run first:  python ../2_train_model/train_occupancy_model.py")
    except Exception as e:
        print(f"[API] Model load error: {e}")

    # Auto-connect serial
    print(f"[API] Connecting to {DEFAULT_COM_PORT} ...")
    start_serial(DEFAULT_COM_PORT, DEFAULT_BAUD)

    yield

    stop_serial()
    print("[API] Shutdown")

# ─────────────────────────────────────────────────────────────────────────────
# APP + CORS
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AIoT Occupancy API - Serial Mode",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────
class SensorReading(BaseModel):
    distance_mm: float

class ComConnectRequest(BaseModel):
    port: str = DEFAULT_COM_PORT
    baud: int = DEFAULT_BAUD

# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status":        "ok",
        "models_ready":  inference is not None,
        "serial":        serial_status,
        "history_count": len(history),
    }


@app.get("/com/ports")
def list_available_ports():
    """Call this to find which COM port your STM32 is on."""
    ports = serial.tools.list_ports.comports()
    return {
        "ports": [
            {"device": p.device, "description": p.description, "hwid": p.hwid}
            for p in ports
        ]
    }


@app.post("/com/connect")
def com_connect(req: ComConnectRequest):
    """Switch to a different COM port without restarting the server."""
    start_serial(req.port, req.baud)
    time.sleep(1.2)
    return {"status": "connecting", "port": req.port, "baud": req.baud,
            "serial": serial_status}


@app.post("/com/disconnect")
def com_disconnect():
    stop_serial()
    return {"status": "disconnected"}


@app.post("/predict")
def predict(reading: SensorReading):
    """Manual test — send a distance value and get prediction back."""
    if inference is None:
        raise HTTPException(status_code=503, detail="Models not loaded. Run training first.")
    result = inference.predict(reading.distance_mm)
    result["timestamp"] = datetime.utcnow().isoformat()
    history.append(result)
    broadcast(result)   # also push to SSE stream
    return result


@app.get("/history")
def get_history(limit: int = 60):
    items = list(history)
    return {"readings": items[-limit:], "total": len(history)}


@app.delete("/history")
def clear_history():
    history.clear()
    serial_status["readings_count"] = 0
    return {"status": "cleared"}


@app.get("/stream")
async def stream():
    """
    Server-Sent Events endpoint.
    React subscribes once and receives every new reading automatically.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    sse_clients.append(q)

    async def event_generator():
        # Send serial status immediately on connect
        yield f"data: {json.dumps({'type':'connected','serial':serial_status})}\n\n"
        try:
            while True:
                data = await q.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            if q in sse_clients:
                sse_clients.remove(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
