"""Moduł przetwarzania odcisków radiowych (Fingerprint)."""

import statistics

from config import VALID_CHARS


class Fingerprint:
    """Reprezentuje pojedynczy odcisk radiowy, wyliczając mediany RSSI oraz znormalizowany wektor cech."""

    def __init__(self, raw_rssi: dict, target_packets: int = 100,
                 fill_missing: bool = False, fill_value: float = -95.0):
        self.raw = raw_rssi
        self.target_packets = target_packets
        self.fill_missing = fill_missing
        self.fill_value = fill_value

    # Oblicza medianę z próbek RSSI dla każdego sektora (brakujące sektory może zastąpić karą -95 dBm).
    def compute_avg(self) -> dict:
        avg = {}
        keys_to_process = VALID_CHARS if self.fill_missing else self.raw.keys()

        for ch in keys_to_process:
            values = self.raw.get(ch) or self.raw.get(str(ch)) or []
            if values:
                trimmed = values[:self.target_packets]
                avg[str(ch)] = round(float(statistics.median(trimmed)), 2)
            elif self.fill_missing:
                avg[str(ch)] = self.fill_value

        return avg

    # Normalizuje wartości RSSI metodą min-max do przedziału [0, 1] dla porównywania kształtu charakterystyki.
    @staticmethod
    def compute_norm(avg: dict) -> dict:
        if not avg:
            return {}

        vals = list(avg.values())
        mn = min(vals)
        mx = max(vals)

        if mx == mn:
            return {k: 0.0 for k in avg}

        return {k: round((v - mn) / (mx - mn), 4) for k, v in avg.items()}

    def to_dict(self) -> dict:
        avg = self.compute_avg()
        norm = self.compute_norm(avg)
        return {"avg": avg, "norm": norm}


# Agreguje zebrane próbki RSSI dla listy beaconów i generuje słownik fingerprintów.
def process_multi_beacon(rssi_accum: dict, target_bids: list[str],
                         target_packets: int = 100,
                         fill_missing: bool = False,
                         fill_value: float = -95.0) -> dict:
    result = {}
    for bid_str in target_bids:
        chars_data = rssi_accum.get(bid_str, {})
        if chars_data:
            fp = Fingerprint(chars_data, target_packets, fill_missing, fill_value)
            fp_dict = fp.to_dict()

            if len(fp_dict["avg"]) > 0:
                result[bid_str] = fp_dict

    return result
