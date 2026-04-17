import socket
import time

# --- НАСТРОЙКИ ---
PRINTER_IP = "192.168.35.163"
PRINTER_PORT = 9100
TEMPLATE_NAME = "CZDM"  # Имя шаблона в памяти принтера (без расширения, зависит от настройки)
QUEUE_FIELD = "code"  # Имя поля (BM) для штрихкода/DataMatrix


class ValentinIndustrialDriver:
    # Управляющие символы ASCII по твоему стандарту
    SOH = b'\x01'
    STX = b'\x02'
    ETX = b'\x03'
    ETB = b'\x17'

    def __init__(self, ip, port=9100):
        self.ip = ip
        self.port = port

    def _send(self, command: str, data: str = "", expect_response: bool = True):
        """Низкоуровневая отправка команды CVPL с обрамлением"""
        cmd_b = command.encode('ascii')

        # Экранирование
        data_b = b""
        if data:
            data_b = str(data).encode('ascii', errors='ignore')
            for char in [self.SOH, self.STX, self.ETX, self.ETB]:
                data_b = data_b.replace(char, b'')

        # Формирование кадра.
        # Оборачиваем данные в STX/ETX (как вы просили),
        # но ВЕСЬ кадр обязательно закрываем ETB (как требует мануал принтера)
        frame = self.SOH + cmd_b
        if data_b:
            frame += self.STX + data_b + self.ETX
        frame += self.ETB

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3.0)  # 3 секунды для TCP в локалке более чем достаточно
                s.connect((self.ip, self.port))
                s.sendall(frame)

                if expect_response:
                    response = s.recv(1024)
                    return response
                return b"OK"
        except Exception as e:
            return f"ERR_CONN: {e}".encode()  # Возвращаем байты для совместимости
    # --- Слой команд управления ---

    def print_direct_no_flash(self, article_text, barcode_data):
        """
        Печать без использования файлов на флешке.
        Формируем геометрию (AM) и данные (BM) на лету.
        """
        # 1. Задаем физику этикетки (например, 50x50 мм)
        # FCCL - длина, FCCO - смещение/ширина
        setup_commands = [
            ("FCCL--r", "0005000-"),
            ("FCCO--", "0005000")
        ]

        # 2. Описываем ГЕОМЕТРИЮ (Mask Sets)
        # AM[индекс]Y;X;Тип;Шрифт;Размер...
        # Индексы 1 и 2 - это просто "слоты" в оперативной памяти принтера
        layout_commands = [
            # Текст: Y=10мм, X=10мм, Шрифт №1
            ("AM[1]", "1000;1000;0;1;0;2;1;1;0"),
            # DataMatrix: Y=25мм, X=10мм, Тип 52 (DataMatrix)
            ("AM[2]", "2500;1000;0;52;0;0;0;0;0;0;7")
        ]

        # 3. Заполняем ДАННЫМИ (Text Sets)
        data_commands = [
            ("BM[1]", article_text),
            ("BM[2]", barcode_data)
        ]

        # 4. Команды тиража и старта
        print_commands = [
            ("FBBA--r", "00001---"),
            ("FBC", "---r--------")
        ]

        # Собираем всё в один поток и отправляем
        full_batch = setup_commands + layout_commands + data_commands + print_commands

        # Используем наш метод из первой версии для отправки пачкой
        for cmd, data in full_batch:
            self._send(cmd, data, expect_response=False)

        return "DIRECT_PRINT_OK"

    def print_batch(self, ean_value, cz_codes):
        """
        Печать пачки: один EAN и список разных DataMatrix.
        Без использования флешки (Stateless).
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10.0)
                s.connect((self.ip, self.port))

                # --- 1. НАСТРОЙКА ХОЛСТА (Размеры из твоего дампа) ---
                self._send(s, "FCCO--r0008000-")  # Ширина 80мм
                self._send(s, "FCCL--r0005500-")  # Высота 55мм
                self._send(s, "FCCM--r00200---")  # Зазор 2мм

                # --- 2. ОБЪЯВЛЕНИЕ ПОЛЕЙ (Геометрия) ---
                # Поле 1: EAN13. Координаты из дампа. Тип 7 (EAN13).
                # y;x;phantom;type;rot;height;mult;hrp;check;ratio
                self._send(s, 'AM[1]5406;3085;0;7;0;1500;0;1;1;1')
                self._send(s, 'AC[1]NAME="EAN13"')

                # Поле 2: DataMatrix (Честный Знак). Координаты из дампа. Тип 52.
                # y;x;phantom;type;rot;dot_size;...
                self._send(s, 'AM[2]5197;7758;0;52;0;70;0;0;9;6;7')
                self._send(s, 'AC[2]NAME="CZ_BARCODE"')

                # --- 3. ЦИКЛ ПЕЧАТИ ---
                print(f"[*] Запуск печати очереди из {len(cz_codes)} шт.")
                for i, code in enumerate(cz_codes):
                    # Заполняем данными по именам, которые дали в AC
                    self._send(s, f"BV[EAN13]{ean_value}")
                    self._send(s, f"BV[CZ_BARCODE]{code}")

                    # Тираж 1 шт и команда ПЕЧАТЬ
                    self._send(s, "FBBA--r00001")
                    self._send(s, "FBC---r")

                    # Небольшая пауза для стабильности сетевого стека принтера
                    time.sleep(0.01)

                return "SUCCESS"

        except Exception as e:
            return f"CONNECTION_ERROR: {e}"

    def get_file_list(self, drive="A:"):
        """Запрос списка файлов на диске принтера"""
        # Команда FMG: O=0 (без ошибок), P=диск
        # Ответ придет в виде списка имен, разделенных SOH/ETB
        resp = self._send("FMG0--r", drive, expect_response=True)
        return resp.decode(errors='ignore')

    def load_template(self, template_name):
        """Загрузка конкретного шаблона из памяти принтера (CF карты)"""
        # Команда FMB---r{имя_файла}
        res = self._send("FMB---r", template_name, expect_response=False)
        return res.decode(errors='ignore') if isinstance(res, bytes) else res

    def set_text_variable(self, field_name, value):
        """Установка статических полей (Text01, Text02 и т.д.)"""
        # Команда BV[{field_name}]{value}
        cmd = f"BV[{field_name}]"
        res = self._send(cmd, value, expect_response=False)
        return res.decode(errors='ignore') if isinstance(res, bytes) else res

    def append_queue(self, field_name, codes_list):
        """
        Заливка пачки кодов в очередь.
        Поскольку Valentin не имеет единой команды "загрузить массив",
        мы шлем пакет в одном TCP-соединении: [Переменная] -> [Печать 1 шт]
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((self.ip, self.port))

                for code in codes_list:
                    # 1. Записываем код ЧЗ в переменную
                    cmd_b = f"BV[{field_name}]".encode('ascii')
                    data_b = code.encode('ascii', errors='ignore')
                    frame_var = self.SOH + cmd_b + self.STX + data_b + self.ETX
                    s.sendall(frame_var)

                    # 2. Задаем тираж (1 шт) FBBA--r00001---
                    s.sendall(self.SOH + b"FBBA--r" + self.STX + b"00001---" + self.ETX)

                    # 3. Добавляем в очередь на печать (FBC)
                    s.sendall(self.SOH + b"FBC" + self.ETX)

                return "OK_QUEUED"
        except Exception as e:
            return f"ERR_CONN: {e}"

    def clear_queue(self, field_name=""):
        """Очистка очереди/сброс активных заданий"""
        # Команда FGA- отменяет задания в буфере
        res = self._send("FGA", "-", expect_response=False)
        return res.decode(errors='ignore') if isinstance(res, bytes) else res

    def start_print(self):
        """Для CVPL печать стартует автоматически при команде FBC из append_queue"""
        return "OK"

    def stop_print(self):
        """Остановка/пауза принтера"""
        # Команда FX ставит принтер на паузу
        res = self._send("FX", expect_response=False)
        return res.decode(errors='ignore') if isinstance(res, bytes) else res

    def get_status(self):
        """Запрос и расшифровка байта статуса CVPL"""
        resp = self._send("S", expect_response=True)

        if resp.startswith(b"ERR_CONN"):
            return resp.decode(errors='ignore')

        if len(resp) >= 3 and resp[0:1] == self.SOH:
            byte1 = resp[1]

            if byte1 & 0x02: return "ERROR_RIBBON_OUT"
            if byte1 & 0x04: return "ERROR_PAPER_OUT"
            if byte1 & 0x08: return "ERROR_CUTTER"
            if byte1 & 0x20: return "PRINTING"
            return "READY"


        return f"UNKNOWN_RAW: {resp.hex()}"

    def get_capacity(self, field_name=""):
        """Количество оставшихся этикеток в очереди"""
        # SZA - запрос текущего счетчика и остатка
        resp = self._send("SZA", expect_response=True)
        return resp.decode(errors='ignore') if isinstance(resp, bytes) else resp

    def get_ribbon_remaining(self):
        """Остаток риббона в метрах (работает, если включен ribbon saver/measuring)"""
        resp = self._send("SM", expect_response=True)
        return resp.decode(errors='ignore') if isinstance(resp, bytes) else resp

    def get_total_prints(self):
        """Общий пробег (счетчик километров)"""
        # SL - статус работы (включает пробег печатающей головки)
        resp = self._send("SL", expect_response=True)
        return resp.decode(errors='ignore') if isinstance(resp, bytes) else resp

    def get_firmware(self):
        """Версия прошивки"""
        # YX - Firmware version
        resp = self._send("YX", expect_response=True)
        return resp.decode(errors='ignore') if isinstance(resp, bytes) else resp

    def start_print(self, endless=True):
        """
        Запуск непрерывной печати (режим ожидания датчика).
        Для Valentin это: Установка тиража 0 + команда FBC.
        """
        # Устанавливаем тираж.
        # '00000---' - бесконечно (endless) в CVPL.
        # Если принтер печатает только одну и останавливается, попробуй '99999---'.
        qty_str = "00000---" if endless else "00001---"
        self._send("FBBA--r", qty_str, expect_response=False)

        # Запускаем режим печати (аналог Auto у Savema)
        # Параметр '---r--------' - это стандартный старт без сортировки
        return self._send("FBC", "---r--------", expect_response=False)

    def set_continuous_mode(self, on=True):
        """
        Специфический режим 'Continuous Printing' (FCSDFA).
        Используется, если нужно, чтобы вал/риббон не останавливались между этикетками
        (для очень высоких скоростей).
        """
        val = "1-------" if on else "0-------"
        return self._send("FCSDFA r", val, expect_response=False)


# --- БОЕВАЯ ЛОГИКА (Тест драйвера) ---

if __name__ == "__main__":
    printer = ValentinIndustrialDriver(PRINTER_IP, PRINTER_PORT)

    status = printer.get_status()
    print(f"[*] Проверка принтера Valentin... {status}")

    if "ERROR" in status:
        print("[!] Требуется вмешательство оператора. Остановка.")
        exit()

    # 1. Загружаем нужный шаблон
    print(f"[*] Загрузка шаблона {TEMPLATE_NAME}...")
    printer.load_template(TEMPLATE_NAME)

    # 2. Устанавливаем статику (партия, сроки)
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

    print("[*] Сброс старой очереди...")
    printer.clear_queue()

    print(f"[*] Заливка {len(codes_from_1c)} кодов в очередь...")
    res = printer.append_queue(QUEUE_FIELD, codes_from_1c)

    if "OK" in res:
        print("[+] Коды успешно загружены. Принтер ждет сигнал датчика.")
    else:
        print(f"[-] ОШИБКА загрузки: {res}")

    # 5. Мониторинг
    cap = printer.get_capacity()
    print(f"[*] Ответ по счетчику принтера: {cap}")