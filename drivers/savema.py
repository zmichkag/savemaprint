import socket
import time

# --- НАСТРОЙКИ переделал, но оставил, вдруг что-то в константу превратится ---
PRINTER_IP = "192.168.35.161"
PRINTER_PORT = 9100
TEMPLATE_NAME = "CZDM.rox"  # Имя файла на принтере
QUEUE_FIELD = "code"  # Поле-источник для ЧЗ


class SavemaIndustrialDriver:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port

    def _send(self, cmd_body):
        """ непосредственно отправка """
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

    # --- Слой управлния ---

    def load_template(self, template_name):
        """Загрузка конкретного шаблона из памяти принтера"""
        return self._send(f"SPLLTF{{{template_name}}}")

    def set_text_variable(self, field_name, value):
        """Установка статических полей"""
        # SPMCTV - Change Text Value
        return self._send(f"SPMCTV{{{field_name}~gt~{value}}}")

    def append_queue(self, field_name, codes_list):
        """Заливка пачки кодов в очередь"""
        processed_codes = [c.replace("<", "&lt;").replace(">", "&gt;") for c in codes_list]
        data_str = "\n".join(processed_codes)
        # SPLAMQ - Append Multi Queue, нуджна прошивка 3,18, без нее не работает
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
        # Остаток риббона в процентах
        return self._send("SPGGRR")

    def get_total_prints(self):
        # Общий счетчик оттисков, пробег принтера
        return self._send("SPGGTP")

    def get_firmware(self):
        # Версия прошивки
        return self._send("SPGGFW")


# --- БОЕВАЯ ЛОГИКА на прошивке 3,18 это нужно будет в оркестратор переложить ---

if __name__ == "__main__":
    printer = SavemaIndustrialDriver(PRINTER_IP, PRINTER_PORT)

    print(f"[*] Проверка принтера... {printer.get_status()}")

    # Загружаем шаблон с ЧЗ
    print(f"[*] Загрузка шаблона {TEMPLATE_NAME}...")
    printer.load_template(TEMPLATE_NAME)

    # настраиваем строчки
    print("[*] Настройка текстовых полей...")
    printer.set_text_variable("Text01", "A2.C1.L7")
    printer.set_text_variable("Text02", "09.04.2026")
    printer.set_text_variable("Text03", "08.07.2026")

    """
    типа получили коды (по хорошему из нужно в SQLite складывать (или писать сразу из 1С), 
    а оркестратор берет по Х-штук (нужно смотреть на месте, чтоб и принтер вывозил и пачки слать не по 100шт, 
    скорость работы 55уп/мин, я думаю от 200 кодов за раз нужно пробовать), шлет в очередь, асинхронно проверяет
    остаток, докладывает по мере расходования и пишет в базу: напечатано\нет    
    """
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
        print("[!] ВНИМАНИЕ: Запуск печати")
        printer.start_print()
    else:
        print(f"[-] ОШИБКА загрузки: {res}")

    # смотрим очередь
    cap = printer.get_capacity(QUEUE_FIELD)
    print(f"[*] Текущая очередь принтера: {cap}")
