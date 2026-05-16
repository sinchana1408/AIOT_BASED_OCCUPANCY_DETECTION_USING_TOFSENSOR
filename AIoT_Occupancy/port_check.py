"""Quick script to find your STM32 board's COM port"""
import serial.tools.list_ports
ports = serial.tools.list_ports.comports()
print("\nAvailable COM ports:")
for p in ports:
    print(f"  {p.device:8s}  {p.description}")
    if any(x in p.description.lower() for x in ["stm","stlink","st-link","virtual"]):
        print(f"           ^^^ THIS IS LIKELY YOUR STM32 BOARD")
print()
