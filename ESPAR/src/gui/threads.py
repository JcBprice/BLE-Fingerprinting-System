"""
threads.py — Wątki tła dla interfejsu wizualizacji ESPAR.

Klasa LiveThread realizuje:
    - Połączenie TCP z anteną ESPAR (klasa EsparClient)
    - Odbiór strumienia ramek BLE (telnet_reader.py)
    - Uruchamianie algorytmu WkNN w oknie czasowym (wknn.py)
    - Emitowanie sygnałów ze współrzędnymi pozycji na żywo do głównego wątku GUI
"""

import time
from PyQt6.QtCore import QThread, pyqtSignal

from espar_client import EsparClient
from telnet_reader import get_espar_stream
from wknn import load_radio_map, wknn_estimate
from validate import load_optimal_k
from config import VALID_CHARS


class LiveThread(QThread):
    """Łączy się z anteną ESPAR, zbiera ramki i szacuje pozycję przy użyciu WkNN."""

    position = pyqtSignal(float, float, int, float)  # (x_est, y_est, beacon_id, confidence)
    status_msg = pyqtSignal(str)
    frame_received = pyqtSignal(int, int, float)     # (beacon_id, char_int, rssi)

    WINDOW_SEC = 7.0
    BEACON_ID  = 28
    BLE_CHANNEL = None

    def __init__(self, parent=None, host="153.19.49.102", port=None, timeout=10):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calibrate_mode = False

    def run(self):
        is_calib = self.calibrate_mode

        radio_map = None
        if not is_calib:
            radio_map = load_radio_map(filter_session=True)
            if not radio_map:
                self.status_msg.emit('Brak punktów kalibracyjnych dla aktywnej sesji!')
                return

        k = load_optimal_k(default=3)
        client = EsparClient(host=self.host, port=self.port, timeout=self.timeout)
        self.status_msg.emit(f'Łączenie z {client.host}:{client.port}…' + (f' (K={k})' if not is_calib else ''))

        sock = client.connect_and_start()
        if sock is None:
            self.status_msg.emit(f'Nie można połączyć z {client.host}:{client.port}')
            return

        sock.settimeout(None)

        if is_calib:
            self.status_msg.emit('Połączono — zbieranie danych kalibracyjnych…')
        else:
            self.status_msg.emit(f'Połączono — zbieram dane (okno {self.WINDOW_SEC}s, K={k})…')

        try:
            window_data = {}
            window_start = time.time()

            for frame in get_espar_stream(sock):
                if self.isInterruptionRequested():
                    break

                if not is_calib and self.BLE_CHANNEL is not None and frame['ble_channel'] != self.BLE_CHANNEL:
                    continue
                if frame['espar_char_int'] not in VALID_CHARS:
                    continue

                if not is_calib:
                    if frame['beacon_num'] != self.BEACON_ID:
                        continue

                bid = frame['beacon_num']
                char_key = str(frame['espar_char_int'])
                rssi = frame['rssi_dbm']

                # Emituj surowy pakiet
                self.frame_received.emit(bid, frame['espar_char_int'], float(rssi))

                if not is_calib:
                    b_data = window_data.setdefault(bid, {})
                    b_data.setdefault(char_key, []).append(rssi)

                    # Koniec okna czasowego -> oblicz pozycję
                    elapsed = time.time() - window_start
                    if elapsed >= self.WINDOW_SEC:
                        result = wknn_estimate(window_data, radio_map,
                                               k=k, beacon_id=self.BEACON_ID)
                        if result is not None:
                            x_est, y_est, conf = result
                            self.position.emit(x_est, y_est, self.BEACON_ID, conf)
                            self.status_msg.emit(
                                f'Pozycja: X={x_est:.2f}m  Y={y_est:.2f}m  '
                                f'Pewność: {int(conf*100)}%  (K={k})'
                            )
                        else:
                            self.status_msg.emit('Za mało danych w oknie — czekam…')

                        window_data.clear()
                        window_start = time.time()
        except Exception as e:
            self.status_msg.emit(f'Błąd strumienia: {e}')
        finally:
            client.stop_and_close(sock)
            self.status_msg.emit('Rozłączono z serwerem ESPAR')
