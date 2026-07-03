"""
fingerprint.py — Logika przetwarzania odcisków radiowych (fingerprint).

Klasa Fingerprint enkapsuluje:
    - Uśrednianie surowych pomiarów RSSI per kierunek anteny
    - Normalizację min-max do zakresu [0, 1]
    - Eksport do formatu słownikowego (JSON-compatible)

Eliminuje powtórzony kod w map_viewer.py (_save_test_point, _save_and_exit,
_save_grid_point), gdzie identyczne bloki uśredniania i normalizacji
były kopiowane 3 razy.
"""

from config import VALID_CHARS


class Fingerprint:
    """Reprezentuje odcisk radiowy z jednego punktu pomiarowego."""

    def __init__(self, raw_rssi: dict, target_packets: int = 100):
        """
        Args:
            raw_rssi:       Surowe dane RSSI zebrane z anteny.
                            Format: {char_int_or_str: [rssi_val, ...]}
            target_packets: Maksymalna liczba pakietów do uśrednienia per kierunek.
        """
        self.raw = raw_rssi
        self.target_packets = target_packets

    def compute_avg(self) -> dict:
        """Oblicza średnie RSSI per kierunek, przycinając do target_packets.

        Returns:
            Słownik {str(char_int): avg_rssi_dBm}.
        """
        avg = {}
        for ch, values in self.raw.items():
            if not values:
                continue
            trimmed = values[:self.target_packets]
            avg[str(ch)] = round(sum(trimmed) / len(trimmed), 2)

        return avg

    @staticmethod
    def compute_norm(avg: dict) -> dict:
        """Normalizacja min-max wektora RSSI do zakresu [0.0, 1.0].

        Args:
            avg: Słownik {str(char_int): avg_rssi_dBm}.

        Returns:
            Słownik {str(char_int): wartość_znormalizowana}.
        """
        if not avg:
            return {}
        vals = list(avg.values())
        mn, mx = min(vals), max(vals)
        if mx == mn:
            return {k: 0.0 for k in avg}
        return {k: round((v - mn) / (mx - mn), 4) for k, v in avg.items()}

    def to_dict(self) -> dict:
        """Eksportuje przetworzony fingerprint do formatu JSON.

        Returns:
            Słownik {"avg": {...}, "norm": {...}}.
        """
        avg = self.compute_avg()
        norm = self.compute_norm(avg)
        return {"avg": avg, "norm": norm}


def process_multi_beacon(rssi_accum: dict, target_bids: list[str],
                         target_packets: int = 100) -> dict:
    """Przetwarza zebrane dane RSSI dla wielu beaconów.

    Convenience wrapper — używany w map_viewer.py zamiast 3 powtórzonych
    bloków kodu (save_and_exit, save_test_point, save_grid_point).

    Args:
        rssi_accum:     Akumulator danych z LiveThread.
                        Format: {bid_str: {char_int: [rssi, ...]}}
        target_bids:    Lista ID beaconów do przetworzenia (jako stringi).
        target_packets: Limit pakietów per kierunek.

    Returns:
        Słownik {bid_str: {"avg": {...}, "norm": {...}}}.
    """
    result = {}
    for bid_str in target_bids:
        chars_data = rssi_accum.get(bid_str, {})
        if not chars_data:
            continue

        fp = Fingerprint(chars_data, target_packets)
        fp_dict = fp.to_dict()

        # Filtruj beacony bez żadnych danych
        has_real_data = len(fp_dict["avg"]) > 0
        if has_real_data:
            result[bid_str] = fp_dict

    return result
