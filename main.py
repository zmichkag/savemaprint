from fastapi import FastAPI, APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from typing import List, Dict
from pydantic import BaseModel
import uvicorn

#Импорт драйверов
from drivers.savema import SavemaIndustrialDriver
from drivers.bizerba import BizerbaBRAIN2Driver
from drivers.videojet import VideojetIndustrialDriver

#инициализация rest aip
app = FastAPI(title="Universal Industrial Printer Driver API v0.4", version="0.4")

# глобальный пул для бицербы - держим тут все соединения
active_bizerbas: Dict[str, BizerbaBRAIN2Driver] = {}

# модель для бицерб - не работает, кажется нужно повышать вверсию брейна для нормальной работы
class PluChangeRequest(BaseModel):
    scale_name: str
    plu_number: str

# это чтоб фастапи понимал какой у нас формат json
class PrintJobField(BaseModel):
    name: str
    text: str

class PrintJobRequest(BaseModel):
    ip: str
    template: str
    fields: List[PrintJobField]

# ==========================================
# Тут начинается роутер савема, корень запроса из (/savema)
# ==========================================
savema_router = APIRouter(prefix="/savema", tags=["Savema"])


@savema_router.get("/health") #заводим точку входа
async def savema_health(ip: str): #создаем функцию и передаем параметры для работы
    printer = SavemaIndustrialDriver(ip, 9100) #запускаем класс драйвера, порт всегда один, IP передаем в запросе
    return {"status": printer.get_status()} #выполняем функцию из класса драйвера (savema.py)

#дальше все одинково:  создаем точку, просим выполнить команды драйвера.

@savema_router.get("/settemplate")
async def savema_setjob(ip: str, template: str):
    """Дергает шаблон по названию """
    printer = SavemaIndustrialDriver(ip, 9100)
    res = printer.load_template(template)
    return {"ip": ip, "res": res}

@savema_router.get("/stop")
async def savema_stop(ip: str):
    """Стопает печать"""
    printer = SavemaIndustrialDriver(ip, 9100)
    res = printer.stop_print()
    return {"ip": ip, "res": res}

@savema_router.get("/start")
async def savema_start(ip: str):
    """Стартует печать"""
    printer = SavemaIndustrialDriver(ip, 9100)
    res = printer.start_print()
    return {"ip": ip, "res": res}

@savema_router.get("/status")
async def savema_status(ip: str):
    """Статус принтера"""
    printer = SavemaIndustrialDriver(ip, 9100)
    res = printer.get_status()
    return {"ip": ip, "res": res}

@savema_router.post("/setfield")
async def savema_setfield(ip: str, field: str, text: str):
    """Установка статических полей (Text01, Text02 и т.д.)"""
    printer = SavemaIndustrialDriver(ip, 9100)
    res = printer.set_text_variable(field, text)
    return {"ip": ip, "res": res}

@savema_router.post("/runjob")
async def savema_runjob(job: PrintJobRequest):
    """
    Комплексная загрузка параметров.
    Принимает JSON с IP, названием шаблона и списком полей для замены.
    Проверка статуса -> Смена шаблона -> Замена полей -> Старт.
    """
    printer = SavemaIndustrialDriver(job.ip, 9100)

    try:
        # Просим статус
        status = printer.get_status()

        # Если статус не ок шлем в лес
        if status.upper() != "READY":
            return {
                "status": "error",
                "message": f"Принтер не готов к смене печати. Status: {status}",
                "ip": job.ip
            }

        # Меняем шаблон
        template_res = printer.load_template(job.template)

        # Меняем текст в полях
        updated_fields = []
        for f in job.fields:
            res = printer.set_text_variable(f.name, f.text)
            updated_fields.append({"field": f.name, "result": res})

        # Запускаем печать
        start_res = printer.start_print()

        return {
            "status": "success",
            "ip": job.ip,
            "template": job.template,
            "template_load_result": template_res,
            "fields_processed": updated_fields,
            "start_result": start_res
        }

    except Exception as e:
        # тут ошибки
        raise HTTPException(status_code=500, detail=f"Connection error: {str(e)}")

# ==========================================
# Тут начинается роутер VideoJet, корень запроса из (/videojet)
# ==========================================

videojet_router = APIRouter(prefix="/videojet", tags=["videojet"])

@videojet_router.get("/status")
async def check_ver(ip: str):
    driver = VideojetIndustrialDriver(ip, 3002)
    res = driver.get_status()
    return (res)

@videojet_router.get("/capacity")
async def check_ver(ip: str):
    driver = VideojetIndustrialDriver(ip, 3002)
    res = driver.get_capacity()
    return (res)


# ==========================================
# РОУТЕР BIZERBA (/bizerba)
# ==========================================
bizerba_router = APIRouter(prefix="/bizerba", tags=["Bizerba"])

# Настройки для BRAIN
#BRAIN_CONFIG = {"ip": "brain2", "port": 2020, "user": "admin", "pass": "admin"}


@bizerba_router.post("/set_plu")
async def set_plu_endpoint(req: PluChangeRequest):
    """
    Эндпоинт для смены артикула (PLU) на указанных весах.
    """
    driver = BizerbaBRAIN2Driver(device_name=req.scale_name)

    # Пытаемся загрузить PLU
    success = driver.load_plu(req.plu_number)
    print(success)

    if success:
        return {
            "status": "ok",
            "message": f"Артикул {req.plu_number} успешно загружен на весы {req.scale_name}."
        }
    else:
        # Если сервер Bizerba вернул ошибку, отдаем 500
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка смены артикула {req.plu_number} на весах {req.scale_name}. Проверьте логи."
        )


@bizerba_router.get("/easysend")
async def easysend(scale_name: str, cmd_type: str, command: str, data: str = "0"):
    """
    простой поинт для отправки команд.
    - scale_name: Имя весов !!!TEST!!!
    - cmd_type: r - w
    - command: Сама команда
    - data: Значение ('0' для чтения)
    """
    driver = BizerbaBRAIN2Driver(device_name=scale_name)

    # Формируем префикс
    pfx = "A?" if cmd_type.lower() == 'r' else "A!"

    # cобираем сообщение
    message = f"{pfx}{command}"
    if data:
        message += f"|{data}"

    # Готовим параметры
    params = {
        "connectName": scale_name,
        "message": f"A?{command}|{data}" if data else f"A?{command}",
        "timeout": 2000
    }

    # шлем
    response = driver._send_get("SendMessage", params=params)

    return {
        "request": {
            "scale": scale_name,
            "generated_message": message
        },
        "response": response
    }


@bizerba_router.get("/query")
async def bizerba_query(scale_name: str, cmd_type: str, command: str, data: str = "0"):
    """
    Умный поинт: шлет команду и сразу читает по хендлу.
    /bizerba/query?scale_name=TEST&cmd_type=r&command=GL19&data=0
    """
    driver = BizerbaBRAIN2Driver(device_name=scale_name)

    # Выполняем двухэтапный запрос
    final_res = driver.ask_and_receive(cmd_type, command, data)

    # Извлекаем ответ из Response
    raw_response = final_res.get("Response", "")
    parsed_value = None

    if "|" in raw_response:
        parsed_value = raw_response.split("|")[-1]

    return {
        "scale": scale_name,
        "raw_response": raw_response,
        "value": parsed_value,
        "full_details": final_res
    }


# Словарь для хранения имен очередей, чтобы не создавать их каждый раз
active_queues: Dict[str, str] = {}


@bizerba_router.get("/monitor_line")
async def monitor_line(scale_name: str):
    """
    Эндпоинт для получения 'пачки' весов.
    При первом вызове создает очередь и ставит фильтр.
    """
    driver = BizerbaBRAIN2Driver(device_name=scale_name)

    # 1. Если для этих весов еще нет очереди — создаем
    if scale_name not in active_queues:
        q_name = driver.create_queue()
        if q_name:
            # Ставим фильтр на PV (данные упаковки/веса) [cite: 163, 170]
            driver.set_queue_filter(q_name, "PV")
            active_queues[scale_name] = q_name
            logger.info(f"Создана выделенная очередь для {scale_name}: {q_name}")
        else:
            raise HTTPException(status_code=500, detail="Не удалось создать очередь на сервере")

    # 2. Получаем пачку данных из очереди
    q_handle = active_queues[scale_name]
    packets = driver.receive_from_queue(q_handle)

    # 3. Парсим пачку (пример упрощенный)
    results = []
    for p in packets:
        # В телеграмме PV обычно вес идет в определенной позиции
        # Для теста просто отдаем сырую строку
        results.append({
            "raw": p,
            "timestamp": time.time()
        })

    return {
        "scale": scale_name,
        "queue": q_handle,
        "count": len(results),
        "data": results
    }

@bizerba_router.get("/dev_list")
async def bizerba_getlist():
    driver = BizerbaBRAIN2Driver()

    #список весов
    scales = driver.get_active_scales()

    print("\n--- Доступные весы на линии ---")
    for scale in scales:
        type_str = "GLM-I (Автомат)" if scale['type'] == 35 else "GLP (Ручные)"
        status_str = "🟢 Активны" if scale['is_active'] else "🔴 Отключены"

        print(f"[{scale['name']}] - {type_str} | {status_str}")

    print("-------------------------------\n")

# @bizerba_router.post("/start_session")
# async def bizerba_start(ip: str, plu: str, codes: List[str] = Query(None)):
#     """коннект, PLU и загрузка пачки кодов"""
#     if ip not in active_bizerbas:
#         active_bizerbas[ip] = BizerbaBRAIN2Driver(ip, 5001)
#         if not active_bizerbas[ip].connect():
#             raise HTTPException(status_code=500, detail="Cant connect to Bizerba")
#
#     driver = active_bizerbas[ip]
#     driver.load_plu(plu)
#
#     # Если передали коды - заливаем в буфер
#     if codes:
#         for i, code in enumerate(codes):
#             driver.push_code_to_buffer(str(1000 + i), code)
#
#     return {"status": "session_started", "ip": ip, "plu": plu, "buffer_count": len(codes or [])}
#
#
# @bizerba_router.get("/weights")
# async def get_weights(ip: str):
#     """Забираем накопленные веса из драйвера"""
#     if ip not in active_bizerbas:
#         return {"error": "No active session"}
#     return {"telegrams": active_bizerbas[ip].pop_weights()}


# ==========================================
# МИНИ-ИНТЕРФЕЙС (DASHBOARD)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
    <html>
        <head>
            <title>SAVEMA 1C Driver Industrial API Dashboard</title>
            <style>
                body { font-family: sans-serif; padding: 20px; background: #f4f4f4; }
                .card { background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 20px; }
                h2 { color: #333; }
                input, button { padding: 10px; margin: 5px; }
                button { background: #007bff; color: white; border: none; cursor: pointer; }
            </style>
        </head>
        <body>
            <h1>SAVEMA 1C Driver Industrial API
 v0.2</h1>

            # <div class="card">
            #     <h2>Управление SAVEMA</h2>
            #     IP: <input id="s_ip" value="192.168.35.161">
            #     Job: <input id="s_job" value="CZDM.rox">
            #     <button onclick="fetch('/savema/setjob?ip='+document.getElementById('s_ip').value+'&template='+document.getElementById('s_job').value, {method:'POST'})">Загрузить шаблон</button>
            # </div>
            # 
            # <div class="card">
            #     <h2>Управление BIZERBA</h2>
            #     IP: <input id="b_ip" value="192.168.35.162">
            #     PLU: <input id="b_plu" value="12345">
            #     <button onclick="startBizerba()">Запустить линию</button>
            #     <div id="b_status"></div>
            # </div>
            # 
            # <script>
            #     async def startBizerba() {
            #         const ip = document.getElementById('b_ip').value;
            #         const plu = document.getElementById('b_plu').value;
            #         await fetch(`/bizerba/start_session?ip=${ip}&plu=${plu}`, {method:'POST'});
            #         alert('Сессия Bizerba запущена!');
            #     }
            # </script>
        </body>
    </html>
    """


# Подключаем роутеры
app.include_router(savema_router)
app.include_router(bizerba_router)
app.include_router(videojet_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)