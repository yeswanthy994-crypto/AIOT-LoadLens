import serial
import serial.tools.list_ports
import csv
import time
from datetime import datetime
import os
import re

# Destination CSV in LoadLens_P03
CSV_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "LoadLens_P03", "loadlens_telemetry.csv"))
BAUD_RATE = 115200
SAMPLE_INTERVAL_SEC = 5.0  # Exactly log once every 5 seconds

def find_stm32_port():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if "STMicroelectronics" in p.description or "STLink" in p.description or "0483" in p.hwid:
            return p.device
    return None

def init_csv():
    file_exists = os.path.isfile(CSV_FILE)
    if not file_exists or os.path.getsize(CSV_FILE) == 0:
        with open(CSV_FILE, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", 
                "Temperature_C", 
                "Baseline_C", 
                "Rise_Delta_C", 
                "Airflow_State", 
                "Motor_Status", 
                "Buzzer_Status"
            ])
            f.flush()
        print(f"[OK] Initialized CSV at: {CSV_FILE}")

def main():
    print("=" * 65)
    print(" LoadLens P03: 5-Second Interval Telemetry Logger")
    print(f" Target CSV: {CSV_FILE}")
    print(f" Logging Rate: Exactly once every {SAMPLE_INTERVAL_SEC} seconds")
    print("=" * 65)

    init_csv()

    # Regex pattern matching STM32 UART printf output
    pattern = r"Temp:\s*([\d\.]+)\s*C\s*\|\s*Base:\s*([\d\.]+)\s*C\s*\|\s*Rise:\s*\+?\s*([\d\.]+)\s*C\s*\|\s*Air:\s*(\w+)"

    last_logged_time = 0.0

    while True:
        port = find_stm32_port()
        if not port:
            print("[INFO] Waiting for STM32 board connection...")
            time.sleep(2)
            continue

        print(f"[CONNECTING] Found STM32 on {port}. Opening stream...")
        try:
            with serial.Serial(port, BAUD_RATE, timeout=1) as ser, open(CSV_FILE, mode='a', newline='') as f:
                writer = csv.writer(f)
                print(f"[CONNECTED] Streaming from {port} -> Logging every {SAMPLE_INTERVAL_SEC}s to CSV!\n")

                while True:
                    raw_bytes = ser.readline()
                    if not raw_bytes:
                        continue

                    try:
                        line = raw_bytes.decode('utf-8', errors='ignore')
                    except Exception:
                        continue

                    match = re.search(pattern, line)
                    if match:
                        current_now = time.time()
                        # Enforce 5-second sampling interval
                        if current_now - last_logged_time >= SAMPLE_INTERVAL_SEC:
                            last_logged_time = current_now
                            temp = float(match.group(1))
                            base = float(match.group(2))
                            rise = float(match.group(3))
                            state = match.group(4).strip()

                            motor_status = "STOPPED" if state == "HEAVY" else "RUNNING"
                            buzzer_status = "ON" if state == "HEAVY" else "OFF"
                            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                            writer.writerow([now_str, temp, base, rise, state, motor_status, buzzer_status])
                            f.flush()
                            print(f"[{now_str}] [5s LOG] -> Temp: {temp:4.1f} °C | State: {state:7s} | Motor: {motor_status:7s} | Buzzer: {buzzer_status}")
                    else:
                        clean = line.strip()
                        if clean and ("LoadLens" in clean or "Baseline" in clean or "Calibrating" in clean):
                            print(f"[STM32 INFO]: {clean}")

        except serial.SerialException as se:
            print(f"[DISCONNECTED] Port {port} closed or busy ({se}). Re-scanning in 2s...")
            time.sleep(2)
        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
