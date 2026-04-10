from fastapi import FastAPI, APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from typing import List, Dict
import uvicorn

# Импортируем твоих "зверей"
from drivers.savema import SavemaIndustrialDriver
from drivers.bizerba import BizerbaIndustrialDriver

app = FastAPI(title="MarkDrive Orchestrator v0.2", version="0.2")

# Глобальный пул активных драйверов Bizerba (чтобы сокеты не закрывались)
active_bizerbas: Dict[str, BizerbaIndustrialDriver] = {}

# ==========================================
# РОУТЕР SAVEMA (/savema)
# ==========================================
savema_router = APIRouter(prefix="/savema", tags=["Savema"])


@savema_router.get("/health")
async def savema_health(ip: str):
    printer = SavemaIndustrialDriver(ip, 9100)
    return {"status": printer.get_status()}


@savema_router.post("/setjob")
async def savema_setjob(ip: str, template: str):
    printer = SavemaIndustrialDriver(ip, 9100)
    res = printer.load_template(template)
    return {"ip": ip, "res": res}

# ==========================================
# РОУТЕР BIZERBA (/bizerba)
# ==========================================
bizerba_router = APIRouter(prefix="/bizerba", tags=["Bizerba"])

# Настройки для BRAIN
BRAIN_CONFIG = {"ip": "192.168.35.100", "port": 8080, "user": "admin", "pass": "admin"}


@bizerba_router.get("/list_scales")
async def list_scales():
    """Получаем список весов из _connect.BRAIN"""
    client = ConnectBrainClient(BRAIN_CONFIG["ip"], BRAIN_CONFIG["port"], BRAIN_CONFIG["user"], BRAIN_CONFIG["pass"])
    scales = client.get_scales_ips()
    return {"scales": scales}


@bizerba_router.post("/start_session")
async def bizerba_start(ip: str, plu: str, codes: List[str] = Query(None)):
    """Инициализация весов: коннект, PLU и загрузка пачки кодов"""
    if ip not in active_bizerbas:
        active_bizerbas[ip] = BizerbaIndustrialDriver(ip, 5001)
        if not active_bizerbas[ip].connect():
            raise HTTPException(status_code=500, detail="Cant connect to Bizerba")

    driver = active_bizerbas[ip]
    driver.load_plu(plu)

    # Если передали коды - заливаем в буфер
    if codes:
        for i, code in enumerate(codes):
            driver.push_code_to_buffer(str(1000 + i), code)

    return {"status": "session_started", "ip": ip, "plu": plu, "buffer_count": len(codes or [])}


@bizerba_router.get("/weights")
async def get_weights(ip: str):
    """Забираем накопленные веса из драйвера"""
    if ip not in active_bizerbas:
        return {"error": "No active session"}
    return {"telegrams": active_bizerbas[ip].pop_weights()}


# ==========================================
# МИНИ-ИНТЕРФЕЙС (DASHBOARD)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
    <html>
        <head>
            <title>MarkDrive Dashboard</title>
            <style>
                body { font-family: sans-serif; padding: 20px; background: #f4f4f4; }
                .card { background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 20px; }
                h2 { color: #333; }
                input, button { padding: 10px; margin: 5px; }
                button { background: #007bff; color: white; border: none; cursor: pointer; }
            </style>
        </head>
        <body>
            <h1>MarkDrive Orchestrator v0.2</h1>

            <div class="card">
                <h2>Управление SAVEMA</h2>
                IP: <input id="s_ip" value="192.168.35.161">
                Job: <input id="s_job" value="CZDM.rox">
                <button onclick="fetch('/savema/setjob?ip='+document.getElementById('s_ip').value+'&template='+document.getElementById('s_job').value, {method:'POST'})">Загрузить шаблон</button>
            </div>

            <div class="card">
                <h2>Управление BIZERBA</h2>
                IP: <input id="b_ip" value="192.168.35.162">
                PLU: <input id="b_plu" value="12345">
                <button onclick="startBizerba()">Запустить линию</button>
                <div id="b_status"></div>
            </div>

            <script>
                async def startBizerba() {
                    const ip = document.getElementById('b_ip').value;
                    const plu = document.getElementById('b_plu').value;
                    await fetch(`/bizerba/start_session?ip=${ip}&plu=${plu}`, {method:'POST'});
                    alert('Сессия Bizerba запущена!');
                }
            </script>
        </body>
    </html>
    """


# Подключаем роутеры
app.include_router(savema_router)
app.include_router(bizerba_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)