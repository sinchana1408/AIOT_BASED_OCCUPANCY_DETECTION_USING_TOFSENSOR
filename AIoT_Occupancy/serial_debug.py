"""
serial_debug.py  —  Run to see EXACTLY what STM32 is printing.
STOP the API server first, then:   python serial_debug.py
"""
import serial, serial.tools.list_ports, time

PORT = "COM4"
BAUD = 115200

print("\n=== Available ports ===")
for p in serial.tools.list_ports.comports():
    print(f"  {p.device}  -  {p.description}")

print(f"\n=== Connecting to {PORT} at {BAUD} ===")
print("Press Ctrl+C to stop\n")

try:
    ser = serial.Serial(PORT, BAUD, timeout=2)
    time.sleep(1.5)
    ser.reset_input_buffer()
    print("--- RAW OUTPUT (copy and paste below) ---")
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line:
            print(f"  {repr(line)}")
except serial.SerialException as e:
    print(f"ERROR: {e}")
    print("Stop the API server first (it holds COM4).")
except KeyboardInterrupt:
    print("\nStopped.")
