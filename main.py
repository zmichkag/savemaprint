from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict
import uvicorn

# Импортируем твой драйвер (предположим, он в файле driver.py)


app = FastAPI(title="MarkDrive Industrial API", version="0.1")


# --- МОДЕЛИ ДАННЫХ (Твои стандарты) ---

class PrintJob(BaseModel):
    printer_ip: str
    template_name: str
    static_fields: Dict[str, str]  # {"Text01": "Молоко", ...}
    codes: List[str]  # Список кодов ЧЗ


# --- ИНИЦИАЛИЗАЦИЯ (В будущем тут будет пул принтеров) ---

@app.get("/health")
async def health_check(ip: str):
    """Проверка доступности принтера"""
    # printer = SavemaIndustrialDriver(ip, 9100)
    # status = printer.get_status()
    return {"status": "online", "printer_response": "~SPGRES{SPPSTA:WAITING}^"}


@app.post("/print/job")
async def create_print_job(job: PrintJob):
    """Прием задания на печать и заливка в очередь"""
    # 1. Создаем драйвер
    # printer = SavemaIndustrialDriver(job.printer_ip, 9100)

    # 2. Логика загрузки (наш прошлый скрипт)
    print(f"Загружаем шаблон: {job.template_name}")
    # printer.load_template(job.template_name)

    print("Обновляем статические поля...")
    # for f, v in job.static_fields.items():
    #     printer.set_text_variable(f, v)

    print(f"Заливаем {len(job.codes)} кодов в очередь...")
    # res = printer.append_queue("code", job.codes)

    # if "OK" in res:
    #    printer.start_print()
    #    return {"success": True, "message": "Job started", "count": len(job.codes)}

    # Пока вернем заглушку для тестов
    return {
        "success": True,
        "message": f"Задание для {job.printer_ip} принято",
        "processed_codes": len(job.codes)
    }


@app.get("/print/queue")
async def get_queue(ip: str, field: str = "code"):
    """Проверка остатка кодов в принтере"""
    # printer = SavemaIndustrialDriver(ip, 9100)
    # capacity = printer.get_capacity(field)
    return {"ip": ip, "remaining": 42}  # Тут будет реальный ответ от SPLGMQ


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)