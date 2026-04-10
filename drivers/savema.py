import socket
import time

# --- НАСТРОЙКИ ---
PRINTER_IP = "192.168.35.161"
PRINTER_PORT = 9100
TEMPLATE_NAME = "CZDM.rox"  # Имя файла на принтере
QUEUE_FIELD = "code"  # Поле-источник для Barcode01


class SavemaIndustrialDriver:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port

    def _send(self, cmd_body):
        """Низкоуровневая отправка команды"""
        full_command = f"~{cmd_body}^"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((self.ip, self.port))
                s.sendall(full_command.encode('ascii'))
                response = s.recv(1024).decode(errors='ignore')
                return response
        except Exception as e:
            return f"ERR_CONN: {e}"

    # --- Слой команд управления ---

    def load_template(self, template_name):
        """Загрузка конкретного шаблона из памяти принтера"""
        return self._send(f"SPLLTF{{{template_name}}}")

    def set_text_variable(self, field_name, value):
        """Установка статических полей (Text01, Text02 и т.д.)"""
        # SPMCTV - Change Text Value
        return self._send(f"SPMCTV{{{field_name}~gt~{value}}}")

    def append_queue(self, field_name, codes_list):
        """Заливка пачки кодов в очередь"""
        processed_codes = [c.replace("<", "&lt;").replace(">", "&gt;") for c in codes_list]
        data_str = "\n".join(processed_codes)
        # SPLAMQ - Append Multi Queue
        return self._send(f"SPLAMQ{{{field_name}~gt~{data_str}}}")

    def clear_queue(self, field_name):
        """Очистка очереди"""
        return self._send(f"SPLCMQ{{{field_name}}}")

    def start_print(self):
        """Активация режима печати по датчику"""
        return self._send("SPPSAP")

    def stop_print(self):
        """Остановка печати"""
        return self._send("SPPSTP")

    def get_status(self):
        """Статус принтера"""
        return self._send("SPPSTA")

    def get_capacity(self, field_name):
        """Остаток в очереди"""
        return self._send(f"SPLGMQ{{{field_name}}}")

    def get_ribbon_remaining(self):
        # SPGGRR - Остаток риббона в процентах
        return self._send("SPGGRR")

    def get_total_prints(self):
        # SPGGTP - Общий счетчик оттисков (пробег принтера)
        return self._send("SPGGTP")

    def get_firmware(self):
        # SPGGFW - Версия прошивки (проверим те самые 3.18)
        return self._send("SPGGFW")


# --- БОЕВАЯ ЛОГИКА (Тот самый "Оркестратор" в миниатюре) ---

if __name__ == "__main__":
    printer = SavemaIndustrialDriver(PRINTER_IP, PRINTER_PORT)

    print(f"[*] Проверка принтера... {printer.get_status()}")

    # 1. Загружаем нужный шаблон
    print(f"[*] Загрузка шаблона {TEMPLATE_NAME}...")
    printer.load_template(TEMPLATE_NAME)

    # 2. Устанавливаем статику (название, партия и т.д.)
    print("[*] Настройка текстовых полей...")
    printer.set_text_variable("Text01", "A2.C1.L7")
    printer.set_text_variable("Text02", "09.04.2026")
    printer.set_text_variable("Text03", "08.07.2026")


    # 3. Работаем с очередью кодов ЧЗ
    codes_from_1c = [
        "010461234567890121abc12345!91EE06!92abc1",
        "010461234567890121abc12345!91EE06!92abc2",
        "010461234567890121abc12345!91EE06!92abc3"
    ]

    print(f"[*] Очистка очереди {QUEUE_FIELD}...")
    printer.clear_queue(QUEUE_FIELD)

    print(f"[*] Заливка {len(codes_from_1c)} кодов в очередь...")
    res = printer.append_queue(QUEUE_FIELD, codes_from_1c)

    if "OK" in res:
        print("[+] Коды успешно загружены.")
        # 4. Включаем режим "Авто"
        print("[!] ВНИМАНИЕ: Запуск режима печати по датчику!")
        printer.start_print()
    else:
        print(f"[-] ОШИБКА загрузки: {res}")

    # 5. Мониторинг
    cap = printer.get_capacity(QUEUE_FIELD)
    print(f"[*] Текущая очередь принтера: {cap}")