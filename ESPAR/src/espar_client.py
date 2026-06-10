import socket
import time

class EsparClient:
    """Zarządza połączeniem TCP z anteną ESPAR."""
    
    def __init__(self, host: str = "153.19.49.102", port: int = 8893, timeout: int = 10):
        self.host = host
        self.port = port
        self.timeout = timeout

    def connect_and_start(self) -> socket.socket | None:
        """Nawiązuje połączenie TCP z serwerem ESPAR i wysyła komendę 'start'."""
        print(f"\nŁączenie z {self.host}:{self.port}...")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
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
