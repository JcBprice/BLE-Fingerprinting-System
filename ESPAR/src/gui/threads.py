"""Wątki tła dla interfejsu graficznego ESPAR (odbieranie ramek i estymacja WkNN na żywo)."""

from collections import deque
import time

from PyQt6.QtCore import QThread, pyqtSignal

from config import VALID_CHARS
from espar_client import EsparClient
from telnet_reader import get_espar_stream
from validate import load_optimal_k
from wknn import load_radio_map, wknn_estimate


class LiveThread(QThread):
    """Wątek tła odbierający strumień z gniazda TCP i estymujący pozycję algorytmem WkNN w oknie czasowym."""

    position = pyqtSignal(float, float, int, float)  # (x_est, y_est, beacon_id, confidence)
    status_msg = pyqtSignal(str)
    frame_received = pyqtSignal(int, int, float)     # (beacon_id, char_int, rssi)

    WINDOW_SEC = 7.0
    UPDATE_INTERVAL = 0.5  # odświeżanie estymacji pozycji w oknie przesuwnym [s]
    EMA_ALPHA = 0.35       # współczynnik wygładzania pozycji EMA zapobiegający skakaniu punktu
    MIN_DIRECTIONS = 4     # minimalna liczba kierunków w buforze do wyliczenia pozycji
    BEACON_ID = None
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
            self.status_msg.emit(f'Połączono — zbieram dane (okno przesuwne {self.WINDOW_SEC}s, K={k})…')

        try:
            # Bufor FIFO przechowujący pakiety z ostatnich sekund: {bid: {char_key: deque([(timestamp, rssi)])}}
            window_buffer = {}
            last_estimate_time = 0.0
            ema_positions = {}  # stan filtru wygładzającego EMA: {bid: (ema_x, ema_y)}

            for frame in get_espar_stream(sock):
                if self.isInterruptionRequested():
                    break

                if not is_calib and self.BLE_CHANNEL is not None and frame['ble_channel'] != self.BLE_CHANNEL:
                    continue
                if frame['espar_char_int'] not in VALID_CHARS:
                    continue

                if not is_calib:
                    if self.BEACON_ID is None:
                        self.BEACON_ID = frame['beacon_num']
                        self.status_msg.emit(f'Wykryto pierwszego beacona: #{self.BEACON_ID} — śledzenie w toku')
                    elif frame['beacon_num'] != self.BEACON_ID:
                        continue

                bid = frame['beacon_num']
                char_key = str(frame['espar_char_int'])
                rssi = frame['rssi_dbm']

                self.frame_received.emit(bid, frame['espar_char_int'], float(rssi))

                if not is_calib:
                    now = time.time()
                    cutoff = now - self.WINDOW_SEC

                    # Dodajemy pakiet do kolejki i usuwamy próbki starsze niż czas trwania okna
                    b_buf = window_buffer.setdefault(bid, {})
                    ch_deque = b_buf.setdefault(char_key, deque())
                    ch_deque.append((now, rssi))

                    for ch, q in list(b_buf.items()):
                        while q and q[0][0] < cutoff:
                            q.popleft()
                        if not q:
                            del b_buf[ch]

                    # Wyliczamy estymację pozycji w regularnych odstępach czasu
                    if now - last_estimate_time >= self.UPDATE_INTERVAL:
                        last_estimate_time = now

                        target_bid = self.BEACON_ID if self.BEACON_ID is not None else bid
                        target_b_buf = window_buffer.get(target_bid) or window_buffer.get(str(target_bid)) or {}
                        active_dirs = sum(1 for q in target_b_buf.values() if q)

                        if active_dirs < self.MIN_DIRECTIONS:
                            self.status_msg.emit(
                                f'Zbieranie kierunków anteny ({active_dirs}/{self.MIN_DIRECTIONS})…'
                            )
                            continue

                        window_data = {
                            b_id: {ch: [r for _, r in q] for ch, q in b_dict.items() if q}
                            for b_id, b_dict in window_buffer.items()
                        }

                        result = wknn_estimate(window_data, radio_map,
                                               k=k, beacon_id=self.BEACON_ID)
                        if result is not None:
                            x_raw, y_raw, conf = result

                            # Filtracja wykładnicza EMA tłumiąca gwałtowne skoki pozycji
                            if target_bid in ema_positions:
                                prev_x, prev_y = ema_positions[target_bid]
                                x_smooth = self.EMA_ALPHA * x_raw + (1.0 - self.EMA_ALPHA) * prev_x
                                y_smooth = self.EMA_ALPHA * y_raw + (1.0 - self.EMA_ALPHA) * prev_y
                            else:
                                x_smooth, y_smooth = x_raw, y_raw

                            ema_positions[target_bid] = (x_smooth, y_smooth)

                            x_out = round(x_smooth, 2)
                            y_out = round(y_smooth, 2)

                            self.position.emit(x_out, y_out, target_bid, conf)
                            self.status_msg.emit(
                                f'Pozycja: X={x_out:.2f}m  Y={y_out:.2f}m  '
                                f'Pewność: {int(conf*100)}%  (K={k})'
                            )
                        else:
                            self.status_msg.emit('Za mało danych w oknie — czekam…')
        except Exception as e:
            self.status_msg.emit(f'Błąd strumienia: {e}')
        finally:
            client.stop_and_close(sock)
            self.status_msg.emit('Rozłączono z serwerem ESPAR')
