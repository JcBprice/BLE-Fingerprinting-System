import socket
import time
import os
import json

class EsparClient:
    """Zarządza połączeniem TCP z anteną ESPAR."""
    
    def __init__(self, host: str = "153.19.49.102", port: int = None, timeout: int = 10):
        self.host = host
        self.timeout = timeout
        
        # Domyślny port
        default_port = 8894
        
        # Ścieżka do pliku konfiguracyjnego w folderze data
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.normpath(os.path.join(self.script_dir, "..", "data", "espar_config.json"))
        
        if port is not None:
            self.port = port
        else:
            self.port = self.load_port_from_config(default_port)

    def load_port_from_config(self, default_port: int) -> int:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    return int(cfg.get("port", default_port))
            except Exception:
                pass
        return default_port

    def save_port_to_config(self, port: int) -> None:
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            cfg = {}
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                except Exception:
                    pass
            cfg["port"] = port
            cfg["host"] = self.host
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[!] Błąd zapisu konfiguracji portu: {e}")

    def connect_and_start(self) -> socket.socket | None:
        """Nawiązuje połączenie TCP z serwerem ESPAR i wysyła komendę 'start'."""
        print(f"\nŁączenie z {self.host}:{self.port}...")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            # Wyłącz algorytm Nagle'a dla natychmiastowej transmisji ramek bez opóźnień buforowania
            try:
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass
            s.sendall(b"\r\n")
            time.sleep(0.5)
            s.sendall(b"start\r\n")
            print("Połączono. Odbieranie danych...\n")
            return s
        except ConnectionRefusedError:
            print(f"[!] Odmowa połączenia z {self.host}:{self.port}.")
        except socket.timeout:
            print(f"[!] Timeout podczas łączenia z {self.host}:{self.port}.")
        except Exception as e:
            print(f"[!] Błąd sieci: {e}")
        return None

    def stop_and_close(self, sock: socket.socket | None) -> None:
        """Wysyła 'stop' i zamyka gniazdo TCP."""
        if sock is None:
            return
        try:
            print("\nZatrzymuję transmisję...")
            sock.sendall(b"stop\r\n")
            time.sleep(0.5)
        except Exception:
            pass
        sock.close()
