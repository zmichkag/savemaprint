import socket
import time
import threading
import requests
import logging
from typing import List, Dict

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("MarkDrive")

# --- КОНФИГУРАЦИЯ ---
# 1. Сервер управления (_connect.BRAIN)
BRAIN_IP = "192.168.35.100"
BRAIN_PORT = 8080
BRAIN_USER = "admin"
BRAIN_PASS = "admin"

# 2. Настройки маркировки (Железо)
BIZERBA_TCP_PORT = 5001
PLU_NUMBER = "12345"
VAR_DM = "GT05"  # Переменная для Честного Знака
VAR_SEQ = "GV50"  # Переменная для Индекса (Sequence)


# ==========================================
# БЛОК 1: КЛИЕНТ REST API (CONTROL PLANE)
# ==========================================
class ConnectBrainClient:
    def __init__(self, ip, port, user, password):
        self.base_url = f"http://{ip}:{port}/api/v1"
        self.session = requests.Session()
        self.session.auth = (user, password)
        self.session.headers.update({"Accept": "application/json"})

    def get_scales_ips(self) -> List[Dict[str, str]]:
        """Получает список устройств и фильтрует только весы (GLP/GLM-I)"""
        endpoint = f"{self.base_url}/devices"
        active_scales = []

        try:
            logger.info(f"Запрос конфигурации линии от {endpoint}...")
            response = self.session.get(endpoint, timeout=5.0)
            response.raise_for_status()

            data = response.json()
            devices = data if isinstance(data, list) else data.get("devices", [])

            for dev in devices:
                dev_type = dev.get("deviceType")
                # 19 = GLP (ручные), 35 = GLM-I (автомат)
                if dev_type in [19, 35]:
                    ip = dev.get("ipAddress") or dev.get("connection", {}).get("ipAddress")
                    if ip:
                        active_scales.append({
                            "name": dev.get("name", "Unknown Scale"),
                            "type": dev_type,
                            "ip": ip
                        })
            return active_scales

        except Exception as e:
            logger.error(f"Сбой связи с _connect.BRAIN: {e}")
            return []


# ==========================================
# БЛОК 2: ДРАЙВЕР ОБОРУДОВАНИЯ (DATA PLANE)
# ==========================================
class BizerbaIndustrialDriver:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        self.is_connected = False
        self.weight_telegrams = []

    def connect(self):
        try:
            self.sock.connect((self.ip, self.port))
            self.is_connected = True
            threading.Thread(target=self._listen, daemon=True).start()
            return True
        except Exception as e:
            logger.error(f"Ошибка TCP подключения к {self.ip}:{self.port} -> {e}")
            return False

    def disconnect(self):
        self.is_connected = False
        self.sock.close()

    def _send(self, cmd_header, cmd_payload=""):
        if not self.is_connected:
            return False

        full_command = f"A!{cmd_header}\r\n"
        if cmd_payload:
            full_command += f"{cmd_payload}\r\n"

        try:
            self.sock.sendall(full_command.encode('ascii'))
            time.sleep(0.05)  # Пауза для стабильности прошивки Bizerba
            return True
        except Exception as e:
            self.is_connected = False
            logger.error(f"Срыв отправки данных на весы: {e}")
            return False

    def _listen(self):
        buffer = ""
        while self.is_connected:
            try:
                data = self.sock.recv(1024).decode(errors='ignore')
                if data:
                    buffer += data
                    while "\r\n" in buffer:
                        line, buffer = buffer.split("\r\n", 1)
                        if "PD00" in line and VAR_SEQ in line:
                            self.weight_telegrams.append(line)
            except socket.timeout:
                continue
            except Exception:
                break

    # --- Команды ---
    def load_plu(self, plu_number):
        return self._send("GL19", plu_number)

    def set_text_variable(self, field_name, value):
        return self._send(f"LV01|{field_name}|LX02", value)

    def push_code_to_buffer(self, seq_id, datamatrix):
        header = f"LV01|{VAR_DM}|{VAR_SEQ}|LX02"
        payload = f"{datamatrix}|{seq_id}"
        return self._send(header, payload)

    def pop_weights(self):
        res = list(self.weight_telegrams)
        self.weight_telegrams.clear()
        return res


# ==========================================
# БЛОК 3: БОЕВОЙ ОРКЕСТРАТОР (MAIN)
# ==========================================
def main():
    logger.info("=== Запуск MarkDrive Edge Agent ===")

    # 1. Запрашиваем топологию у сервера
    brain_client = ConnectBrainClient(BRAIN_IP, BRAIN_PORT, BRAIN_USER, BRAIN_PASS)
    scales = brain_client.get_scales_ips()

    if not scales:
        logger.warning("Весы не найдены или сервер недоступен. Завершение работы.")
        # Для ручного теста без сервера можно раскомментировать строку ниже:
        # scales = [{"name": "Test GLP", "ip": "192.168.35.161", "type": 19}]
        return

    # Берем первые найденные весы (для примера)
    target_scale = scales[0]
    logger.info(f"Выбрано оборудование: {target_scale['name']} [IP: {target_scale['ip']}]")

    # 2. Подключаемся к железу напрямую
    driver = BizerbaIndustrialDriver(target_scale['ip'], BIZERBA_TCP_PORT)
    if not driver.connect():
        return

    logger.info("TCP соединение установлено.")

    # 3. Инициализация задания (PLU и статика)
    logger.info(f"Загрузка артикула {PLU_NUMBER}...")
    driver.load_plu(PLU_NUMBER)
    driver.set_text_variable("GT01", "ПАРТИЯ: A2.C1")

    # 4. Загрузка пула кодов ЧЗ (Эмуляция получения из 1С/БД)
    codes_from_db = [
        {"seq": "1001", "dm": "010461234567890121abc12345!91EE06"},
        {"seq": "1002", "dm": "010461234567890121abc12346!91EE06"},
        {"seq": "1003", "dm": "010461234567890121abc12347!91EE06"}
    ]

    logger.info(f"Отправка {len(codes_from_db)} кодов в буфер весов...")
    for item in codes_from_db:
        if driver.push_code_to_buffer(item["seq"], item["dm"]):
            logger.info(f" -> Код {item['seq']} загружен")
        else:
            logger.error(f" -> Ошибка загрузки кода {item['seq']}")

    # 5. Цикл мониторинга производственной линии
    logger.info("=== Линия готова. Ожидание взвешивания... ===")
    try:
        while True:
            weights = driver.pop_weights()
            for w in weights:
                logger.info(f"[*] СИГНАЛ ОТ ВЕСОВ: {w}")
                # Здесь будет логика: разобрать строку, найти Вес и Индекс,
                # обновить статус кода в локальной БД.
            time.sleep(0.5)  # Опрашиваем локальную очередь каждые полсекунды

    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C).")
    finally:
        driver.disconnect()
        logger.info("Соединение закрыто. Агент остановлен.")


if __name__ == "__main__":
    main()