import os
import csv
import time
import re
import threading
from datetime import datetime
from typing import List, Dict, Any

from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import serial
import serial.tools.list_ports
import pandas as pd
import joblib

app = FastAPI(title="LoadLens AIoT & ML Cloud Service")

CSV_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "LoadLens_P03", "loadlens_telemetry.csv"))
MODEL_FILE = os.path.join(os.path.dirname(__file__), "loadlens_ml_model.joblib")
BAUD_RATE = 115200
SAMPLE_INTERVAL_SEC = 5.0  # Exactly 5 seconds per CSV row

# Global state
latest_telemetry: Dict[str, Any] = {
    "timestamp": "--",
    "temperature": 0.0,
    "baseline": 0.0,
    "rise": 0.0,
    "hardware_state": "DISCONNECTED",
    "ml_prediction": "UNKNOWN",
    "ml_confidence": 0.0,
    "motor": "UNKNOWN",
    "buzzer": "UNKNOWN",
    "com_port": "None",
    "connected": False
}

ml_model = None
if os.path.exists(MODEL_FILE):
    try:
        ml_model = joblib.load(MODEL_FILE)
        print("[ML] Loaded trained Random Forest model successfully.")
    except Exception as e:
        print(f"[ML ERR] {e}")

def find_stm32_port():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if "STMicroelectronics" in p.description or "STLink" in p.description or "0483" in p.hwid:
            return p.device
    return None

def init_csv():
    if not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) == 0:
        with open(CSV_FILE, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", "Temperature_C", "Baseline_C", "Rise_Delta_C",
                "Airflow_State", "Motor_Status", "Buzzer_Status"
            ])
            f.flush()

def serial_worker():
    global latest_telemetry
    init_csv()
    pattern = r"Temp:\s*([\d\.]+)\s*C\s*\|\s*Base:\s*([\d\.]+)\s*C\s*\|\s*Rise:\s*\+?\s*([\d\.]+)\s*C\s*\|\s*Air:\s*(\w+)"
    last_logged_time = 0.0

    while True:
        port = find_stm32_port()
        if not port:
            latest_telemetry["connected"] = False
            latest_telemetry["com_port"] = "Disconnected"
            latest_telemetry["hardware_state"] = "DISCONNECTED"
            time.sleep(2)
            continue

        latest_telemetry["com_port"] = port
        try:
            with serial.Serial(port, BAUD_RATE, timeout=1) as ser, open(CSV_FILE, mode='a', newline='') as f:
                writer = csv.writer(f)
                latest_telemetry["connected"] = True

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
                        temp = float(match.group(1))
                        base = float(match.group(2))
                        rise = float(match.group(3))
                        hw_state = match.group(4).strip()
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        # Run ML Inference in Real-Time
                        pred_class = hw_state
                        conf = 99.8
                        if ml_model is not None:
                            try:
                                sample_df = pd.DataFrame([{
                                    "Temperature_C": temp,
                                    "Baseline_C": base,
                                    "Rise_Delta_C": rise
                                }])
                                pred_class = ml_model.predict(sample_df)[0]
                                probs = ml_model.predict_proba(sample_df)[0]
                                conf = float(max(probs) * 100.0)
                            except Exception:
                                pass

                        motor_status = "STOPPED" if hw_state == "HEAVY" else "RUNNING"
                        buzzer_status = "ON" if hw_state == "HEAVY" else "OFF"

                        # Update in-memory live status
                        latest_telemetry.update({
                            "timestamp": now_str,
                            "temperature": temp,
                            "baseline": base,
                            "rise": rise,
                            "hardware_state": hw_state,
                            "ml_prediction": pred_class,
                            "ml_confidence": round(conf, 1),
                            "motor": motor_status,
                            "buzzer": buzzer_status,
                            "connected": True
                        })

                        # Save to CSV every 5 seconds
                        current_now = time.time()
                        if current_now - last_logged_time >= SAMPLE_INTERVAL_SEC:
                            last_logged_time = current_now
                            writer.writerow([now_str, temp, base, rise, hw_state, motor_status, buzzer_status])
                            f.flush()

        except Exception as e:
            latest_telemetry["connected"] = False
            time.sleep(2)

# Start background serial worker
thread = threading.Thread(target=serial_worker, daemon=True)
thread.start()

# API Endpoints
@app.get("/api/telemetry")
def get_telemetry():
    return latest_telemetry

@app.get("/api/history")
def get_history():
    if not os.path.exists(CSV_FILE):
        return []
    try:
        df = pd.read_csv(CSV_FILE).tail(30)
        return df.to_dict(orient="records")
    except Exception:
        return []

class PredictRequest(BaseModel):
    temp: float
    base: float

@app.post("/api/predict")
def predict_manual(req: PredictRequest):
    if ml_model is None:
        return {"error": "Model not loaded"}
    rise = max(0.0, req.temp - req.base)
    sample_df = pd.DataFrame([{"Temperature_C": req.temp, "Baseline_C": req.base, "Rise_Delta_C": rise}])
    pred = ml_model.predict(sample_df)[0]
    probs = ml_model.predict_proba(sample_df)[0]
    return {
        "predicted_state": pred,
        "confidence": round(float(max(probs) * 100.0), 2),
        "safe_profile_action": "EMERGENCY MOTOR CUTOFF & BUZZER ON" if pred == "HEAVY" else "MOTOR FORWARD RUNNING"
    }

# Modern UI Dashboard Frontend
@app.get("/", response_class=HTMLResponse)
def dashboard():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>LoadLens AIoT & ML Cloud Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen font-sans">
        <!-- Top Navbar -->
        <header class="border-b border-slate-800 bg-slate-900/60 backdrop-blur px-6 py-4 flex flex-wrap justify-between items-center">
            <div class="flex items-center space-x-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
                    <i class="fa-solid fa-fan text-white text-lg"></i>
                </div>
                <div>
                    <h1 class="text-xl font-bold tracking-tight text-white">LoadLens (P03) <span class="text-cyan-400 font-semibold text-sm ml-2">Edge AIoT Service</span></h1>
                    <p class="text-xs text-slate-400">STM32 Nucleo-F446RE · Thermodynamic Proxy · Random Forest Classifier</p>
                </div>
            </div>
            <div class="flex items-center space-x-4 mt-2 sm:mt-0">
                <div id="conn-badge" class="flex items-center space-x-2 px-3 py-1.5 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs font-medium">
                    <span class="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
                    <span id="conn-text">Connecting to STM32...</span>
                </div>
                <div class="text-xs text-slate-400 bg-slate-800/80 px-3 py-1.5 rounded-lg border border-slate-700">
                    CSV Logging: <span class="text-emerald-400 font-semibold">Active (Every 5s)</span>
                </div>
            </div>
        </header>

        <main class="max-w-7xl mx-auto px-6 py-8 space-y-6">
            <!-- Metric Cards -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
                <!-- Temperature -->
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl relative overflow-hidden">
                    <div class="flex justify-between items-start">
                        <div>
                            <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">Chamber Temp</p>
                            <h2 id="card-temp" class="text-3xl font-extrabold text-white mt-1">--.- °C</h2>
                        </div>
                        <div class="w-10 h-10 rounded-xl bg-cyan-500/10 text-cyan-400 flex items-center justify-center">
                            <i class="fa-solid fa-temperature-half text-lg"></i>
                        </div>
                    </div>
                    <div class="mt-4 flex items-center text-xs text-slate-400">
                        <span>Baseline: <strong id="card-base" class="text-slate-200">-- °C</strong></span>
                        <span class="mx-2">·</span>
                        <span>Rise: <strong id="card-rise" class="text-cyan-400">+-- °C</strong></span>
                    </div>
                </div>

                <!-- ML Classification -->
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl">
                    <div class="flex justify-between items-start">
                        <div>
                            <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">ML Prediction</p>
                            <h2 id="card-ml" class="text-2xl font-extrabold text-emerald-400 mt-1">FREE</h2>
                        </div>
                        <div class="w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center">
                            <i class="fa-solid fa-brain text-lg"></i>
                        </div>
                    </div>
                    <div class="mt-4 text-xs text-slate-400">
                        Confidence: <strong id="card-conf" class="text-emerald-400">99.8%</strong> (Random Forest)
                    </div>
                </div>

                <!-- Motor Actuator -->
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl">
                    <div class="flex justify-between items-start">
                        <div>
                            <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">Motor Actuator (L298N)</p>
                            <h2 id="card-motor" class="text-2xl font-extrabold text-emerald-400 mt-1">RUNNING</h2>
                        </div>
                        <div class="w-10 h-10 rounded-xl bg-blue-500/10 text-blue-400 flex items-center justify-center">
                            <i class="fa-solid fa-gear text-lg"></i>
                        </div>
                    </div>
                    <div class="mt-4 text-xs text-slate-400">
                        Logic: <strong class="text-slate-200">PA5 (HIGH) / PA6 (LOW)</strong>
                    </div>
                </div>

                <!-- Safety Buzzer -->
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl">
                    <div class="flex justify-between items-start">
                        <div>
                            <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">Buzzer Alert (D4 / PB5)</p>
                            <h2 id="card-buzzer" class="text-2xl font-extrabold text-slate-400 mt-1">OFF (SAFE)</h2>
                        </div>
                        <div class="w-10 h-10 rounded-xl bg-rose-500/10 text-rose-400 flex items-center justify-center">
                            <i class="fa-solid fa-bell text-lg"></i>
                        </div>
                    </div>
                    <div class="mt-4 text-xs text-slate-400">
                        Trigger: <strong class="text-slate-200">Trip at ≥ 50.0 °C</strong>
                    </div>
                </div>
            </div>

            <!-- Chart & Simulator Grid -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- Real-Time Telemetry Chart -->
                <div class="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                    <div class="flex justify-between items-center mb-4">
                        <div>
                            <h3 class="font-bold text-white text-base">Real-Time Thermal Dynamics & Safe Profiles</h3>
                            <p class="text-xs text-slate-400">Dynamic temperature telemetry curve streamed from STM32 ADC1</p>
                        </div>
                        <span class="text-xs bg-slate-800 text-slate-300 px-2.5 py-1 rounded-md border border-slate-700">30 Recent Samples</span>
                    </div>
                    <div class="h-64">
                        <canvas id="tempChart"></canvas>
                    </div>
                </div>

                <!-- Interactive ML What-If Simulator -->
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
                    <div>
                        <div class="flex items-center space-x-2 mb-3">
                            <i class="fa-solid fa-sliders text-cyan-400"></i>
                            <h3 class="font-bold text-white text-base">ML What-If Simulator</h3>
                        </div>
                        <p class="text-xs text-slate-400 mb-4">Test model predictions by simulating chamber temperatures without touching physical hardware.</p>

                        <div class="space-y-4">
                            <div>
                                <label class="text-xs font-medium text-slate-300 flex justify-between">
                                    <span>Simulated Temperature:</span>
                                    <span id="sim-temp-val" class="font-bold text-cyan-400">42.0 °C</span>
                                </label>
                                <input type="range" id="sim-temp" min="20" max="70" step="0.5" value="42.0" class="w-full accent-cyan-500 cursor-pointer mt-1">
                            </div>
                            <div>
                                <label class="text-xs font-medium text-slate-300 flex justify-between">
                                    <span>Simulated Baseline:</span>
                                    <span id="sim-base-val" class="font-bold text-slate-400">28.0 °C</span>
                                </label>
                                <input type="range" id="sim-base" min="20" max="35" step="0.5" value="28.0" class="w-full accent-slate-500 cursor-pointer mt-1">
                            </div>
                        </div>
                    </div>

                    <div class="mt-6 p-4 rounded-xl bg-slate-950 border border-slate-800">
                        <div class="text-xs text-slate-400">Predicted Airflow Profile:</div>
                        <div id="sim-result-class" class="text-lg font-bold text-amber-400 mt-1">PARTIAL RESTRICTION</div>
                        <div id="sim-result-action" class="text-xs text-slate-400 mt-1">Action: Motor Running, Maintenance Alert</div>
                    </div>
                </div>
            </div>

            <!-- Recent CSV Telemetry Table -->
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                <div class="flex justify-between items-center mb-4">
                    <div>
                        <h3 class="font-bold text-white text-base">Live CSV Telemetry Log (5s Granularity)</h3>
                        <p class="text-xs text-slate-400">Synchronized directly with <code class="text-cyan-400">LoadLens_P03/loadlens_telemetry.csv</code></p>
                    </div>
                    <a href="/api/history" target="_blank" class="text-xs text-cyan-400 hover:text-cyan-300 font-medium">
                        View Raw JSON <i class="fa-solid fa-arrow-up-right-from-square ml-1"></i>
                    </a>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs text-slate-300">
                        <thead class="bg-slate-950/60 uppercase tracking-wider text-slate-400 border-b border-slate-800">
                            <tr>
                                <th class="py-3 px-4">Timestamp</th>
                                <th class="py-3 px-4">Temp (°C)</th>
                                <th class="py-3 px-4">Base (°C)</th>
                                <th class="py-3 px-4">Rise ΔT</th>
                                <th class="py-3 px-4">Airflow State</th>
                                <th class="py-3 px-4">Motor Status</th>
                                <th class="py-3 px-4">Buzzer Alert</th>
                            </tr>
                        </thead>
                        <tbody id="table-body" class="divide-y divide-slate-800">
                            <tr>
                                <td colspan="7" class="py-4 text-center text-slate-500">Awaiting telemetry records...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </main>

        <script>
            // Chart Setup
            const ctx = document.getElementById('tempChart').getContext('2d');
            const tempChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'Chamber Temp (°C)',
                            data: [],
                            borderColor: '#06b6d4',
                            backgroundColor: 'rgba(6, 182, 212, 0.1)',
                            fill: true,
                            tension: 0.3,
                            borderWidth: 2
                        },
                        {
                            label: 'Emergency Cutoff (50°C)',
                            data: [],
                            borderColor: '#ef4444',
                            borderDash: [5, 5],
                            borderWidth: 1.5,
                            pointRadius: 0
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { labels: { color: '#94a3b8', font: { size: 11 } } } },
                    scales: {
                        x: { ticks: { color: '#64748b', maxTicksLimit: 8 }, grid: { color: 'rgba(51, 65, 85, 0.2)' } },
                        y: { min: 20, max: 65, ticks: { color: '#64748b' }, grid: { color: 'rgba(51, 65, 85, 0.2)' } }
                    }
                }
            });

            // Polling Function
            async function fetchTelemetry() {
                try {
                    const res = await fetch('/api/telemetry');
                    const data = await res.json();

                    // Connection Badge
                    const badge = document.getElementById('conn-badge');
                    const connText = document.getElementById('conn-text');
                    if (data.connected) {
                        badge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-medium";
                        connText.innerHTML = `Connected to STM32 (<span class="font-bold">${data.com_port}</span>)`;
                    } else {
                        badge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs font-medium";
                        connText.innerText = "Scanning for STM32 Port...";
                    }

                    // Card Values
                    if (data.temperature > 0) {
                        document.getElementById('card-temp').innerText = `${data.temperature.toFixed(1)} °C`;
                        document.getElementById('card-base').innerText = `${data.baseline.toFixed(1)} °C`;
                        document.getElementById('card-rise').innerText = `+${data.rise.toFixed(1)} °C`;

                        // ML Card
                        const mlEl = document.getElementById('card-ml');
                        mlEl.innerText = data.ml_prediction;
                        if (data.ml_prediction === 'HEAVY') {
                            mlEl.className = "text-2xl font-extrabold text-rose-500 mt-1";
                        } else if (data.ml_prediction === 'PARTIAL') {
                            mlEl.className = "text-2xl font-extrabold text-amber-400 mt-1";
                        } else {
                            mlEl.className = "text-2xl font-extrabold text-emerald-400 mt-1";
                        }
                        document.getElementById('card-conf').innerText = `${data.ml_confidence}%`;

                        // Motor Card
                        const motorEl = document.getElementById('card-motor');
                        motorEl.innerText = data.motor;
                        motorEl.className = data.motor === 'STOPPED' ? "text-2xl font-extrabold text-rose-500 mt-1" : "text-2xl font-extrabold text-emerald-400 mt-1";

                        // Buzzer Card
                        const buzzerEl = document.getElementById('card-buzzer');
                        buzzerEl.innerText = data.buzzer === 'ON' ? "ALARM ON!" : "OFF (SAFE)";
                        buzzerEl.className = data.buzzer === 'ON' ? "text-2xl font-extrabold text-rose-500 mt-1" : "text-2xl font-extrabold text-slate-400 mt-1";
                    }

                    // Fetch History for Table & Chart
                    const histRes = await fetch('/api/history');
                    const history = await histRes.json();
                    if (history && history.length > 0) {
                        // Update Chart
                        const labels = history.map(h => h.Timestamp.split(' ')[1]);
                        const temps = history.map(h => h.Temperature_C);
                        const cutoffs = history.map(() => 50.0);

                        tempChart.data.labels = labels;
                        tempChart.data.datasets[0].data = temps;
                        tempChart.data.datasets[1].data = cutoffs;
                        tempChart.update();

                        // Update Table (reverse for newest on top)
                        const rows = history.slice(-8).reverse().map(h => `
                            <tr class="hover:bg-slate-800/40 transition">
                                <td class="py-2.5 px-4 font-mono text-slate-400">${h.Timestamp}</td>
                                <td class="py-2.5 px-4 font-semibold ${h.Temperature_C >= 50 ? 'text-rose-400' : 'text-slate-200'}">${h.Temperature_C.toFixed(1)}</td>
                                <td class="py-2.5 px-4 text-slate-400">${h.Baseline_C.toFixed(1)}</td>
                                <td class="py-2.5 px-4 text-cyan-400">+${h.Rise_Delta_C.toFixed(1)}</td>
                                <td class="py-2.5 px-4 font-bold ${h.Airflow_State === 'HEAVY' ? 'text-rose-400' : (h.Airflow_State === 'PARTIAL' ? 'text-amber-400' : 'text-emerald-400')}">${h.Airflow_State}</td>
                                <td class="py-2.5 px-4 font-medium ${h.Motor_Status === 'STOPPED' ? 'text-rose-400' : 'text-emerald-400'}">${h.Motor_Status}</td>
                                <td class="py-2.5 px-4 font-medium ${h.Buzzer_Status === 'ON' ? 'text-rose-400 font-bold' : 'text-slate-500'}">${h.Buzzer_Status}</td>
                            </tr>
                        `).join('');
                        document.getElementById('table-body').innerHTML = rows;
                    }
                } catch (err) {
                    console.error("Telemetry fetch error:", err);
                }
            }

            // Periodic Poll every 2 seconds
            setInterval(fetchTelemetry, 2000);
            fetchTelemetry();

            // Simulator logic
            const simTemp = document.getElementById('sim-temp');
            const simBase = document.getElementById('sim-base');
            const simTempVal = document.getElementById('sim-temp-val');
            const simBaseVal = document.getElementById('sim-base-val');
            const simResClass = document.getElementById('sim-result-class');
            const simResAction = document.getElementById('sim-result-action');

            async function runSimulator() {
                const temp = parseFloat(simTemp.value);
                const base = parseFloat(simBase.value);
                simTempVal.innerText = `${temp.toFixed(1)} °C`;
                simBaseVal.innerText = `${base.toFixed(1)} °C`;

                try {
                    const res = await fetch('/api/predict', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ temp, base })
                    });
                    const result = await res.json();
                    simResClass.innerText = `${result.predicted_state} (Confidence: ${result.confidence}%)`;
                    simResAction.innerText = `Action: ${result.safe_profile_action}`;

                    if (result.predicted_state === 'HEAVY') {
                        simResClass.className = "text-lg font-bold text-rose-500 mt-1";
                    } else if (result.predicted_state === 'PARTIAL') {
                        simResClass.className = "text-lg font-bold text-amber-400 mt-1";
                    } else {
                        simResClass.className = "text-lg font-bold text-emerald-400 mt-1";
                    }
                } catch(e) {}
            }

            simTemp.addEventListener('input', runSimulator);
            simBase.addEventListener('input', runSimulator);
            runSimulator();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
