from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict
import uvicorn
from drivers.savema import SavemaIndustrialDriver


app = FastAPI(title="SAVEMA 1C Driver Industrial API", version="0.1")


# --- МОДЕЛИ ДАННЫХ ---

class PrintJob(BaseModel):
    printer_ip: str
    template_name: str
    static_fields: Dict[str, str]  # {"Text01": "Молоко", ...}
    codes: List[str]  # Список кодов ЧЗ


# --- возможно тут будет пул принтеров) ---

@app.get("/health")
async def health_check(ip: str):
    """Проверка доступности принтера"""
    printer = SavemaIndustrialDriver(ip, 9100)
    status = printer.get_status()
    return {status}


@app.post("/setjob")
async def load_template(ip: str, template: str):
    """
    Меняет шаблон.
    Вызов: http://127.0.0.1:8000/print/setjob?ip=192.168.35.161&template=CZDM.rox
    """
    print(f"[*] Инициализация принтера: {ip}")
    print(f"[*] Команда на загрузку шаблона: {template}")

    # Инициализируем драйвер
    printer = SavemaIndustrialDriver(ip, 9100)

    # Выполняем команду
    res = printer.load_template(template)


    return {
        "status": "command_sent",
        "target_ip": ip,
        "template": template,
        "printer_response": res
    }


@app.post("/setfield")
async def set_printer_fields(ip: str, field1: str, field2: str, field3: str):
    """
      Меняет поля.

      """

    # 1. Инициализируем драйвер
    printer = SavemaIndustrialDriver(ip, 9100)

    # 2. Устанавливаем значения

    res1 = printer.set_text_variable("Text01", field1)
    res2 = printer.set_text_variable("Text02", field2)
    res3 = printer.set_text_variable("Text03", field3)

    # 3. Собираем ответы в один список
    responses = [res1, res2, res3]

    # 4. Проверяем
    if any("ERR_CONN" in r for r in responses):
        return {
            "status": "error",
            "message": "Принтер недоступен",
            "details": responses
        }

    # 5. Возвращаем красивый JSON
    return {
        "status": "success",
        "ip": ip,
        "applied_fields": {
            "Text01": field1,
            "Text02": field2,
            "Text03": field3
        },
        "printer_raw_responses": responses
    }

# @app.post("/print/setjob")
# async def create_print_job(job: PrintJob):
#     """Прием задания на печать и заливка в очередь"""
#     # 1. Создаем драйвер
#     # printer = SavemaIndustrialDriver(job.printer_ip, 9100)
#
#     # 2. Логика загрузки (наш прошлый скрипт)
#     print(f"Загружаем шаблон: {job.template_name}")
#     # printer.load_template(job.template_name)
#
#     print("Обновляем статические поля...")
#     # for f, v in job.static_fields.items():
#     #     printer.set_text_variable(f, v)
#
#     print(f"Заливаем {len(job.codes)} кодов в очередь...")
#     # res = printer.append_queue("code", job.codes)
#
#     # if "OK" in res:
#     #    printer.start_print()
#     #    return {"success": True, "message": "Job started", "count": len(job.codes)}
#
#     # Пока вернем заглушку для тестов
#     return {
#         "success": True,
#         "message": f"Задание для {job.printer_ip} принято",
#         "processed_codes": len(job.codes)
#     }


@app.get("/printer/telemetry")
async def get_printer_telemetry(ip: str):
    """
      Смотрим состояние
      """
    printer = SavemaIndustrialDriver(ip, 9100)

    # Собираем чтотам да как с принтером
    status = printer.get_full_status()
    ribbon = printer.get_ribbon_remaining()
    count = printer.get_total_prints()
    queue = printer.get_capacity("code")  # Наша очередь ЧЗ

    return {
        "ip": ip,
        "is_online": "ERR_CONN" not in status,
        "status": status,
        "ribbon_left": ribbon,
        "total_prints": count,
        "queue_load": queue
    }

@app.get("/printer/stop")
async def stop_print(ip: str):
    """
      стопаем печать
      """
    printer = SavemaIndustrialDriver(ip, 9100)


    res = printer.stop_print()

    print(f"[DEBUG] Ответ от принтера: {res}")  # Увидишь, что реально ответила железка

    return {
        "ip": ip,
        "answer": res
    }

@app.get("/print/queue")
async def get_queue(ip: str, field: str = "code"):
    """Проверка остатка кодов в принтере"""
    # printer = SavemaIndustrialDriver(ip, 9100)
    # capacity = printer.get_capacity(field)
    return {"ip": ip, "remaining": 42}  # Тут будет реальный ответ от SPLGMQ


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)