"""Klient TCP do połączenia ze sprzętową anteną ESPAR."""

import json
import os
import socket
import time


class EsparClient:
    def __init__(self, host: str = "153.19.49.102", port: int = None, timeout: int = 10):
        self.host = host
        self.timeout = timeout
        self.config_path = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "espar_config.json")
        )
        self.port = port if port is not None else self.load_port_from_config(8895)

    def load_port_from_config(self, default_port: int) -> int:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return int(json.load(f).get("port", default_port))
            except Exception:
                pass
        return default_port

    def save_port_to_config(self, port: int) -> None:
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            cfg = {}
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)

            cfg["port"] = port
            cfg["host"] = self.host
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            print(f"[!] Błąd zapisu konfiguracji: {e}")

    # Czyści bufor odbiorczy gniazda w trybie nieblokującym ze starych lub zbędnych pakietów powitalnych.
    @staticmethod
    def _drain(sock: socket.socket) -> bytes:
        sock.setblocking(False)
        data = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        except Exception:
            pass
        sock.setblocking(True)
        return data

    # Łączy się przez gniazdo TCP, wysyła polecenia inicjalizacji (char_mode 0, start) i zwraca aktywne połączenie.
    def connect_and_start(self) -> socket.socket | None:
        print(f"\nŁączenie z {self.host}:{self.port}...")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            time.sleep(0.15)
            self._drain(s)

            s.sendall(b"\r\n")
            time.sleep(0.2)
            self._drain(s)

            s.sendall(b"char_mode 0\r\n")
            time.sleep(0.25)
            self._drain(s)

            s.sendall(b"start\r\n")
            time.sleep(0.3)

            print("Połączono. Odbieranie danych...\n")
            return s
        except (ConnectionRefusedError, socket.timeout):
            print(f"[!] Problem z połączeniem do {self.host}:{self.port}")
        except Exception as e:
            print(f"[!] Błąd sieci: {e}")
        return None

    # Wysyła komendę 'stop' do anteny ESPAR i bezpiecznie zamyka gniazdo sieciowe.
    def stop_and_close(self, sock: socket.socket | None) -> None:
        if sock is None:
            return
        try:
            print("\nZatrzymuję transmisję...")
            sock.sendall(b"stop\r\n")
            time.sleep(0.3)
            self._drain(sock)
            sock.close()
        except Exception:
            pass
