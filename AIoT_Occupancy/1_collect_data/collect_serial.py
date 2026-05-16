"""
STEP 1A - Collect VL53L0X dataset via USB Serial (UART)
==========================================================
Board: B-L4S5I-IOT01A connected via USB (ST-Link / Virtual COM Port)
STM32 must print lines like:   DIST:423\r\n   (just the distance in mm)

Usage:
    python collect_serial.py --port COM3 --samples 1000
    python collect_serial.py --port /dev/ttyACM0 --samples 1000  (Linux/Mac)

Output:
    dataset.csv   with columns: timestamp_ms, distance_mm, occupancy_count
    (occupancy_count column is filled in MANUALLY after collection - see below)
"""

import serial
import serial.tools.list_ports
import pandas as pd
import time
import argparse
import sys
import os

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
BAUD_RATE   = 115200
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "dataset.csv")

# ─────────────────────────────────────────────────────────────────────────────
# HELPER: list available COM ports
# ─────────────────────────────────────────────────────────────────────────────
def list_ports():
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No serial ports found.")
    else:
        print("Available serial ports:")
        for p in ports:
            print(f"  {p.device}  -  {p.description}")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN COLLECTOR
# ─────────────────────────────────────────────────────────────────────────────
def collect(port: str, n_samples: int, label_mode: bool):
    """
    label_mode = True  → prompt user to type occupancy count (0-3) per session.
    label_mode = False → save with occupancy_count=-1 (label later in Excel/CSV).
    """
    print(f"\n[CONNECT] Opening {port} at {BAUD_RATE} baud ...")
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=2)
    except serial.SerialException as e:
        print(f"[ERROR] {e}")
        print("Run without arguments to list ports:  python collect_serial.py")
        sys.exit(1)

    time.sleep(2)   # allow STM32 to reset after serial connect
    ser.reset_input_buffer()
    print(f"[OK] Connected. Collecting {n_samples} samples ...\n")

    rows        = []
    t_start     = time.time()
    label       = -1
    session_count = 0

    if label_mode:
        print("LABEL MODE: You will be asked for the occupancy count (0-3)")
        print("  0 = empty room")
        print("  1 = 1 person in doorway")
        print("  2 = 2 people")
        print("  3 = 3+ people")
        print("Press ENTER to start first session ...\n")
        input()
        label = int(input("Occupancy count for THIS session (0/1/2/3): ").strip())

    collected = 0
    errors    = 0

    while collected < n_samples:
        try:
            raw = ser.readline().decode("utf-8", errors="ignore").strip()
        except Exception:
            errors += 1
            continue

        # Parse all formats: "Distance: 8.6 cm", "DIST:86", "86", "Distance: 86 mm"
        dist = None
        lo = raw.lower()
        try:
            if "distance" in lo and "cm" in lo:
                val = float(lo.split(":")[1].replace("cm","").strip().split()[0])
                dist = round(val * 10.0, 1)   # cm -> mm
            elif "distance" in lo and ":" in lo:
                val = float(raw.split(":")[1].replace("mm","").strip().split()[0])
                dist = float(val)
            elif lo.startswith("dist:"):
                dist = float(raw.split(":")[1].split()[0])
            else:
                stripped = raw.replace("mm","").replace("cm","").strip()
                if stripped.replace(".","").replace("-","").isdigit():
                    val = float(stripped)
                    dist = round(val * 10.0, 1) if val < 30 else val
        except Exception:
            pass

        if dist is None or not (30 <= dist <= 2000):
            continue

        t_ms = int((time.time() - t_start) * 1000)
        rows.append({
            "timestamp_ms":    t_ms,
            "distance_mm":     round(dist, 1),
            "occupancy_count": label
        })
        collected     += 1
        session_count += 1

        # Progress bar
        pct = collected / n_samples * 100
        bar = "#" * int(pct / 2)
        print(f"\r  [{bar:<50}] {collected}/{n_samples}  dist={dist:.0f}mm  label={label}  ",
              end="", flush=True)

        # In label mode, ask for new label every 100 samples
        if label_mode and session_count >= 100 and collected < n_samples:
            print(f"\n\n[PAUSE] 100 samples collected for label={label}")
            print("Change room state now, then enter new occupancy count.")
            label = int(input("New occupancy count (0/1/2/3): ").strip())
            session_count = 0

    ser.close()
    print(f"\n\n[DONE] Collected {collected} samples, {errors} parse errors.")

    # Save
    df = pd.DataFrame(rows)

    if os.path.exists(OUTPUT_FILE):
        existing = pd.read_csv(OUTPUT_FILE)
        df = pd.concat([existing, df], ignore_index=True)
        print(f"[APPEND] Added to existing {OUTPUT_FILE}  (total: {len(df)} rows)")
    else:
        print(f"[SAVE] Written to {OUTPUT_FILE}")

    df.to_csv(OUTPUT_FILE, index=False)

    print("\nDataset preview:")
    print(df.tail(10).to_string(index=False))

    if -1 in df["occupancy_count"].values:
        print("\n[NOTE] Some rows have occupancy_count=-1.")
        print("       Open dataset.csv in Excel and fill the column manually,")
        print("       then re-run training:  python ../2_train_model/train_occupancy_model.py dataset.csv")

# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect VL53L0X data via Serial")
    parser.add_argument("--port",    type=str, default=None,
                        help="COM port, e.g. COM3 or /dev/ttyACM0")
    parser.add_argument("--samples", type=int, default=500,
                        help="Number of samples to collect (default 500)")
    parser.add_argument("--label",   action="store_true",
                        help="Interactive label mode (ask occupancy count)")
    args = parser.parse_args()

    if args.port is None:
        list_ports()
        print("\nUsage example:  python collect_serial.py --port COM3 --samples 500 --label")
        sys.exit(0)

    collect(args.port, args.samples, args.label)
