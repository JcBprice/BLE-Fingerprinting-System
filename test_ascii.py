import math
class Dummy:
    def _beacon_positions(self, base_x, base_y, tripod):
        angle_rad = math.radians(tripod["angle_deg"])
        pos = []
        for i, bid in enumerate(tripod["beacon_ids"]):
            bx = base_x + i * tripod["spacing_m"] * math.cos(angle_rad)
            by = base_y + i * tripod["spacing_m"] * math.sin(angle_rad)
            pos.append((bid, bx, by))
        return pos
    
    def _print_ascii_map(self, grid_points, tripod):
        all_positions = []
        for label, base_x, base_y in grid_points:
            if tripod:
                positions = self._beacon_positions(base_x, base_y, tripod)
                for bid, bx, by in positions:
                    all_positions.append((bx, by))
            else:
                all_positions.append((base_x, base_y))
        min_x = min(p[0] for p in all_positions)
        max_x = max(p[0] for p in all_positions)
        min_y = min(p[1] for p in all_positions)
        max_y = max(p[1] for p in all_positions)
        min_x = min(min_x, 0.0)
        max_x = max(max_x, 0.0)
        min_y = min(min_y, 0.0)
        max_y = max(max_y, 0.0)
        span_x = max_x - min_x
        span_y = max_y - min_y
        COLS = 40
        if span_x > 0:
            scale_x = COLS / span_x
        else:
            scale_x = 10.0
        ROWS = max(5, int(span_y * scale_x))
        if ROWS > 20:
            scale_y = 20 / span_y
            ROWS = 20
            if span_x > 0:
                COLS = max(5, int(span_x * scale_y))
            scale_x = scale_y
        if COLS > 60: COLS = 60
        if ROWS > 30: ROWS = 30
        grid = [[' ' for _ in range(COLS + 1)] for _ in range(ROWS + 1)]
        def to_grid(px, py):
            gx = int(round((px - min_x) * scale_x))
            gy = int(round((py - min_y) * scale_x))
            return gx, gy
        ox_g, oy_g = to_grid(0.0, 0.0)
        if 0 <= oy_g <= ROWS and 0 <= ox_g <= COLS:
            grid[oy_g][ox_g] = 'O'
        for px, py in all_positions:
            gx, gy = to_grid(px, py)
            if 0 <= gy <= ROWS and 0 <= gx <= COLS:
                grid[gy][gx] = 'x'
        print("    " + "-" * (COLS + 1))
        for row in grid:
            print("    |" + "".join(row) + "|")
        print("    " + "-" * (COLS + 1))

d = Dummy()
# Tripod pionowy (kat 90), rozpietosc 1m (3 beacony, co 0.5m)
tripod = {"n_beacons": 3, "beacon_ids": [1,2,3], "spacing_m": 0.5, "angle_deg": 90}
# korytarz dlugi na X=5m, start Y=0, X=0, krok 1m w X, w lewo
grid = []
for i in range(6):
    grid.append((f"p{i}", -i*1.0, -0.5))

d._print_ascii_map(grid, tripod)
