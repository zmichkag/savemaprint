import socket
import time

# --- НАСТРОЙКИ ---
PRINTER_IP = "192.168.35.23"
PRINTER_PORT = 3002  # Стандартный порт Text Comms для Videojet
TEMPLATE_NAME = "CZDM"  # Имя шаблона на принтере (без .ciff)
QUEUE_FIELD = "DM_Mark"  # Имя переменной штрихкода в шаблоне


class VideojetIndustrialDriver:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port

    def _send(self, cmd_body):
        """ Непосредственно отправка одной команды (разовая сессия) """
        full_command = f"{cmd_body}\r"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((self.ip, self.port))

                # Рекомендация Videojet: пустой \r перед командой сбрасывает мусор в буфере
                s.sendall(b"\r")
                s.sendall(full_command.encode('ascii'))

                response = s.recv(1024).decode('ascii', errors='ignore').strip()
                return response
        except Exception as e:
            return f"ERR_CONN: {e}"

    # --- Слой управления ---

    def load_template(self, template_name):
        """Загрузка конкретного шаблона из памяти принтера"""
        # SLA - Select Job with Allocation/Fields
        return self._send(f"SLA|{template_name}|")

    def set_text_variable(self, field_name, value):
        """Установка статических полей (без аллокации печати)"""
        # JDA - Job Data Update
        return self._send(f"JDA|{field_name}={value}|")

    def append_queue(self, field_name, codes_list):
        """Заливка пачки кодов в очередь (Continuous Session)"""
        # У Videojet нет команды SPLAMQ для заливки пачки одним текстом.
        # Поэтому мы открываем сокет 1 раз и пулеметом шлем команды JDI|1|...
        # Это обеспечивает максимальную скорость без оверхеда на TCP handshake.
        success_count = 0
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10.0)
                s.connect((self.ip, self.port))
                s.sendall(b"\r")

                for code in codes_list:
                    # JDI|1|... означает: добавить 1 оттиск (аллокация) с такими-то данными
                    cmd = f"JDI|1|{field_name}={code}|\r"
                    s.sendall(cmd.encode('ascii'))

                    response = s.recv(1024).decode('ascii', errors='ignore').strip()
                    # При успешной постановке в очередь JDI возвращает ID задания (число), а не ACK
                    if response.isdigit():
                        success_count += 1
                    elif response == "NACK" or response == "ERR":
                        print(f"[-] Ошибка отправки кода {code}: {response}")

            return f"OK: {success_count}/{len(codes_list)}"
        except Exception as e:
            return f"ERR_BATCH: {e}"

    def clear_queue(self):
        """Очистка очереди"""
        # CQI без параметров очищает все неактивные элементы очереди
        return self._send("CQI|")

    def start_print(self):
        """Активация режима печати по датчику (перевод в Running)"""
        # SST|3| - Set State 3 (Running)
        return self._send("SST|3|")

    def stop_print(self):
        """Остановка печати (перевод в Offline)"""
        # SST|4| - Set State 4 (Offline)
        return self._send("SST|4|")

    def get_status(self):
        """Запрашивает статус и расшифровывает его согласно протоколу Zipher"""
        raw_response = self._send("GST")

        # Словари для расшифровки согласно спецификации [cite: 3916, 3950]
        overall_map = {
            "0": "Shut down",
            "1": "Starting up",
            "2": "Shutting down",
            "3": "Running",
            "4": "Offline"
        }

        error_map = {
            "0": "No errors",
            "1": "Warnings present",
            "2": "Faults present"
        }

        if raw_response.startswith("STS|"):
            parts = raw_response.split('|')
            # Проверяем, что пришло достаточно данных [cite: 3944]
            if len(parts) >= 6:
                return {
                    "raw": raw_response,
                    "parsed": {
                        "state_code": parts[1],
                        "state_desc": overall_map.get(parts[1], "Unknown"),
                        "error_code": parts[2],
                        "error_desc": error_map.get(parts[2], "Unknown"),
                        "current_job": parts[3],
                        "batch_count": parts[4],
                        "total_count": parts[5]
                    }
                }

        return {"raw": raw_response, "parsed": None, "error": "Invalid response format"}

    def get_capacity(self):
        """Размер текущей очереди принтера"""
        # QLN возвращает QLN|<size>|<status>| (где status 3 = очередь полная)
        return self._send("QLN")

    def clear_faults(self):
        """Квитирование (сброс) ошибок"""
        # Команда CAF (Clear All Faults)
        return self._send("CAF")

    def get_ribbon_remaining(self):
        """Остаток риббона"""
        # В Zipher Text Comms нет явной команды для % риббона на 6330.
        # Принтер просто выдаст errorstate=2 (Fault) в статусе GST, когда риббон порвется/кончится.
        return "N/A_FOR_TTO"

    def get_total_prints(self):
        """Общий счетчик оттисков, пробег принтера"""
        # GPC возвращает PCS|<success prints>|<fail prints>|<missed prints>|<remaining prints>|
        return self._send("GPC")

    def get_firmware(self):
        """Версия протокола / прошивки"""
        # VER возвращает VER|<версия>|<кодировка>|
        return self._send("VER")


# --- БОЕВАЯ ЛОГИКА (Проверка связи и минимальный тест) ---

if __name__ == "__main__":
    printer = VideojetIndustrialDriver(PRINTER_IP, PRINTER_PORT)

    print(f"[*] Проверка принтера (Протокол)... {printer.get_firmware()}")
    print(f"[*] Статус принтера... {printer.get_status()}")

    # Загружаем шаблон
    print(f"[*] Загрузка шаблона {TEMPLATE_NAME}...")
    res_load = printer.load_template(TEMPLATE_NAME)
    print(f"    Ответ: {res_load}")

    # Настраиваем статические строчки (если они есть в шаблоне)
    print("[*] Настройка текстовых полей...")
    printer.set_text_variable("Text01", "A2.C1.L7")
    printer.set_text_variable("Text02", "09.04.2026")

    # Пачка кодов (заметь, вставил байт FNC1 - \x1D, он нужен для валидного Честного Знака)
    codes_from_1c = [
        "010461234567890121abc12345\x1D91EE06\x1D92abc1",
        "010461234567890121abc12345\x1D91EE06\x1D92abc2",
        "010461234567890121abc12345\x1D91EE06\x1D92abc3"
    ]

    print("[*] Очистка очереди принтера...")
    printer.clear_queue()

    print(f"[*] Заливка {len(codes_from_1c)} кодов в очередь...")
    res = printer.append_queue(QUEUE_FIELD, codes_from_1c)

    if "OK" in res:
        print(f"[+] Коды успешно загружены. Результат: {res}")
        print("[!] ВНИМАНИЕ: Запуск печати (перевод в Running)")
        printer.start_print()
    else:
        print(f"[-] ОШИБКА загрузки: {res}")

    # Смотрим длину очереди
    cap = printer.get_capacity()
    print(f"[*] Текущая очередь принтера: {cap}")