"""
STEP 1B - Collect VL53L0X dataset via WiFi (HTTP)
===================================================
Board: B-L4S5I-IOT01A running the wifi_sender firmware (see 5_stm32_firmware/)
The board exposes:  GET http://<board-ip>/sensor
  Returns JSON:     {"distance_mm": 423}

Usage:
    python collect_wifi.py --ip 192.168.1.42 --samples 500
    python collect_wifi.py --ip 192.168.1.42 --samples 500 --label

Output:
    dataset.csv   columns: timestamp_ms, distance_mm, occupancy_count
"""

import requests
import pandas as pd
import time
import argparse
import sys
import os

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "dataset.csv")
TIMEOUT_S   = 3
POLL_INTERVAL_S = 1.0   # match STM32 sampling rate (~1 Hz)


def ping_board(ip: str) -> bool:
    try:
        r = requests.get(f"http://{ip}/health", timeout=TIMEOUT_S)
        return r.status_code == 200
    except Exception:
        return False


def collect(ip: str, n_samples: int, label_mode: bool):
    base_url = f"http://{ip}/sensor"

    print(f"\n[CONNECT] Checking board at {ip} ...")
    if not ping_board(ip):
        print(f"[WARN] /health not responding. Trying /sensor directly ...")

    print(f"[OK] Starting collection of {n_samples} samples from {base_url}\n")

    rows          = []
    t_start       = time.time()
    collected     = 0
    errors        = 0
    label         = -1
    session_count = 0

    if label_mode:
        print("LABEL MODE: You will be asked for the occupancy count (0-3)")
        print("  0 = empty room    1 = 1 person    2 = 2 people    3 = 3+ people")
        label = int(input("\nOccupancy count for THIS session (0/1/2/3): ").strip())

    while collected < n_samples:
        loop_start = time.time()
        try:
            resp = requests.get(base_url, timeout=TIMEOUT_S)
            data = resp.json()
            dist = float(data.get("distance_mm", data.get("distance", -1)))
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"\n[ERROR] {e}")
            time.sleep(0.5)
            continue

        if not (30 <= dist <= 2000):
            continue

        t_ms = int((time.time() - t_start) * 1000)
        rows.append({
            "timestamp_ms":    t_ms,
            "distance_mm":     round(dist, 1),
            "occupancy_count": label
        })
        collected     += 1
        session_count += 1

        pct = collected / n_samples * 100
        bar = "#" * int(pct / 2)
        print(f"\r  [{bar:<50}] {collected}/{n_samples}  dist={dist:.0f}mm  label={label}  ",
              end="", flush=True)

        if label_mode and session_count >= 100 and collected < n_samples:
            print(f"\n\n[PAUSE] Change room state, then enter new occupancy count.")
            label = int(input("New occupancy count (0/1/2/3): ").strip())
            session_count = 0

        # Throttle to ~1 Hz
        elapsed = time.time() - loop_start
        if elapsed < POLL_INTERVAL_S:
            time.sleep(POLL_INTERVAL_S - elapsed)

    print(f"\n\n[DONE] Collected {collected} samples, {errors} errors.")

    df = pd.DataFrame(rows)
    if os.path.exists(OUTPUT_FILE):
        existing = pd.read_csv(OUTPUT_FILE)
        df = pd.concat([existing, df], ignore_index=True)
        print(f"[APPEND] Total rows now: {len(df)}")
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"[SAVE] {OUTPUT_FILE}")
    print(df.tail(5).to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect VL53L0X data via WiFi")
    parser.add_argument("--ip",      type=str, required=True,
                        help="Board IP address, e.g. 192.168.1.42")
    parser.add_argument("--samples", type=int, default=500)
    parser.add_argument("--label",   action="store_true",
                        help="Interactive label mode")
    args = parser.parse_args()
    collect(args.ip, args.samples, args.label)
