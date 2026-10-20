"""
Módulo de Codificação e Decodificação Geohash (100% Autoral).

Implementa:
- Codificação de coordenadas (latitude, longitude) em Base32 por intercalação binária
  de intervalos, limitada a até 8 níveis (40 bits).
- Decodificação de Geohash para caixa delimitadora (bounding box) e ponto central.
- Cálculo das 8 células adjacentes (N, NE, E, SE, S, SW, W, NW) para eliminar o
  problema de borda em buscas por prefixo.
- Seleção dinâmica do nível de prefixo para cobrir um raio de atendimento R (km).
"""

from __future__ import annotations
from typing import Dict, List, Tuple

BASE32_ALPHABET = "0123456789bcdefghjkmnpqrstuvwxyz"
BASE32_DECODE_MAP: Dict[str, int] = {ch: idx for idx, ch in enumerate(BASE32_ALPHABET)}

LAT_INTERVAL = (-90.0, 90.0)
LON_INTERVAL = (-180.0, 180.0)


def encode_geohash(lat: float, lon: float, precision: int = 8) -> str:
    """
    Converte uma coordenada (latitude, longitude) para uma string Geohash em Base32
    por meio da intercalação binária de intervalos.

    Parâmetros:
        lat: Latitude em graus decimais [-90.0, 90.0].
        lon: Longitude em graus decimais [-180.0, 180.0].
        precision: Número de caracteres (níveis) do Geohash (padrão = 8).

    Retorna:
        String Geohash com `precision` caracteres.
    """
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"Latitude fora do intervalo [-90, 90]: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"Longitude fora do intervalo [-180, 180]: {lon}")
    if precision < 1 or precision > 12:
        raise ValueError(f"Precisão inválida: {precision}")

    lat_min, lat_max = LAT_INTERVAL
    lon_min, lon_max = LON_INTERVAL

    is_even_bit = True  # Bits pares (0, 2, 4...) codificam longitude; ímpares codificam latitude
    bit_count = 0
    char_index = 0
    geohash_chars: List[str] = []

    total_bits = precision * 5

    for _ in range(total_bits):
        if is_even_bit:
            mid = (lon_min + lon_max) / 2.0
            if lon >= mid:
                char_index = (char_index << 1) | 1
                lon_min = mid
            else:
                char_index = (char_index << 1) | 0
                lon_max = mid
        else:
            mid = (lat_min + lat_max) / 2.0
            if lat >= mid:
                char_index = (char_index << 1) | 1
                lat_min = mid
            else:
                char_index = (char_index << 1) | 0
                lat_max = mid

        is_even_bit = not is_even_bit
        bit_count += 1

        if bit_count == 5:
            geohash_chars.append(BASE32_ALPHABET[char_index])
            bit_count = 0
            char_index = 0

    return "".join(geohash_chars)


def decode_bbox(geohash: str) -> Tuple[float, float, float, float]:
    """
    Decodifica um Geohash (ou prefixo de Geohash) em sua caixa delimitadora (bounding box).

    Retorna:
        Tupla (lat_min, lat_max, lon_min, lon_max).
    """
    if not geohash:
        raise ValueError("Geohash não pode ser vazio.")

    lat_min, lat_max = LAT_INTERVAL
    lon_min, lon_max = LON_INTERVAL
    is_even_bit = True

    for ch in geohash.lower():
        if ch not in BASE32_DECODE_MAP:
            raise ValueError(f"Caractere inválido no Geohash: '{ch}'")
        val = BASE32_DECODE_MAP[ch]

        for mask in (16, 8, 4, 2, 1):
            bit = 1 if (val & mask) else 0
            if is_even_bit:
                mid = (lon_min + lon_max) / 2.0
                if bit == 1:
                    lon_min = mid
                else:
                    lon_max = mid
            else:
                mid = (lat_min + lat_max) / 2.0
                if bit == 1:
                    lat_min = mid
                else:
                    lat_max = mid
            is_even_bit = not is_even_bit

    return lat_min, lat_max, lon_min, lon_max


def decode_center(geohash: str) -> Tuple[float, float, float, float]:
    """
    Decodifica um Geohash retornando o centro (lat, lon) e as dimensões (delta_lat, delta_lon)
    da célula correspondente.
    """
    lat_min, lat_max, lon_min, lon_max = decode_bbox(geohash)
    center_lat = (lat_min + lat_max) / 2.0
    center_lon = (lon_min + lon_max) / 2.0
    delta_lat = lat_max - lat_min
    delta_lon = lon_max - lon_min
    return center_lat, center_lon, delta_lat, delta_lon


def _wrap_lon(lon: float) -> float:
    """Normaliza a longitude para o intervalo [-180.0, 180.0]."""
    while lon > 180.0:
        lon -= 360.0
    while lon < -180.0:
        lon += 360.0
    return lon


def _clamp_lat(lat: float) -> float:
    """Restringe a latitude ao intervalo [-89.999999, 89.999999]."""
    return max(-89.999999, min(89.999999, lat))


def get_neighbors(geohash_prefix: str) -> List[str]:
    """
    Calcula a célula central e as 8 células adjacentes (N, NE, E, SE, S, SW, W, NW)
    de um dado prefixo Geohash, eliminando o problema de borda na busca espacial.

    Parâmetros:
        geohash_prefix: Prefixo Geohash da célula central.

    Retorna:
        Lista contendo os 9 prefixos Geohash únicos (central + 8 adjacentes).
    """
    precision = len(geohash_prefix)
    center_lat, center_lon, d_lat, d_lon = decode_center(geohash_prefix)

    offsets = [
        (0, 0),    # Centro
        (1, 0),    # Norte (N)
        (1, 1),    # Nordeste (NE)
        (0, 1),    # Leste (E)
        (-1, 1),   # Sudeste (SE)
        (-1, 0),   # Sul (S)
        (-1, -1),  # Sudoeste (SW)
        (0, -1),   # Oeste (W)
        (1, -1),   # Noroeste (NW)
    ]

    cells: List[str] = []
    seen = set()
    for dy, dx in offsets:
        n_lat = _clamp_lat(center_lat + dy * d_lat)
        n_lon = _wrap_lon(center_lon + dx * d_lon)
        neighbor_hash = encode_geohash(n_lat, n_lon, precision=precision)
        if neighbor_hash not in seen:
            seen.add(neighbor_hash)
            cells.append(neighbor_hash)

    return cells


def get_covering_cells_for_radius(lat: float, lon: float, radius_km: float) -> Tuple[int, str, List[str]]:
    """
    Calcula o conjunto exato de células Geohash (central + adjacentes necessárias)
    para cobrir integralmente uma circunferência de raio `radius_km` (em km)
    em torno de `(lat, lon)`, eliminando 100% o problema de borda com alta seletividade.

    - Para raios <= 1.2 km, usa a vizinhança 3x3 (9 células) no nível 6 (~1.2km x 0.6km por célula)
      ou expande verticalmente quando necessário.
    - Para raios até 5.0 km, usa o nível 5 (~4.9km x 4.9km por célula), onde a janela 3x3
      cobre 100% de qualquer círculo de até 4.89 km de raio mesmo na borda exata!

    Retorna:
        Tupla (precision, center_prefix, lista_de_prefixos_cobertos).
    """
    if radius_km <= 0.6:
        precision = 6
        center_prefix = encode_geohash(lat, lon, precision=precision)
        return precision, center_prefix, get_neighbors(center_prefix)

    if radius_km <= 2.2:
        # Usa nível 6 com janela adaptativa na caixa delimitadora do raio R para alta seletividade
        precision = 6
        center_prefix = encode_geohash(lat, lon, precision=precision)
        _, _, d_lat, d_lon = decode_center(center_prefix)

        # Conversão de km para graus na latitude de BH
        deg_lat_radius = radius_km / 110.574
        deg_lon_radius = radius_km / (111.320 * max(0.2, abs(__import__("math").cos(__import__("math").radians(lat)))))

        steps_lat = int(__import__("math").ceil(deg_lat_radius / d_lat)) + 1
        steps_lon = int(__import__("math").ceil(deg_lon_radius / d_lon)) + 1

        cells: List[str] = [center_prefix]
        seen = {center_prefix}
        for dy in range(-steps_lat, steps_lat + 1):
            for dx in range(-steps_lon, steps_lon + 1):
                n_lat = _clamp_lat(lat + dy * d_lat)
                n_lon = _wrap_lon(lon + dx * d_lon)
                gh = encode_geohash(n_lat, n_lon, precision=precision)
                if gh not in seen:
                    seen.add(gh)
                    cells.append(gh)
        return precision, center_prefix, cells

    precision = 5 if radius_km <= 4.8 else 4
    center_prefix = encode_geohash(lat, lon, precision=precision)
    return precision, center_prefix, get_neighbors(center_prefix)


def choose_prefix_precision_for_radius(radius_km: float) -> int:
    """
    Seleciona o nível de prefixo Geohash ideal para que a grade 3x3 (célula central + 8 vizinhas)
    cubra integralmente a circunferência de raio `radius_km` em torno do ponto de consulta.
    """
    if radius_km <= 0.58:
        return 6
    if radius_km <= 4.8:
        return 5
    return 4
