"""
Módulo de Geometria Computacional e Filtragem de Resultado Parcial (100% Autoral).

Implementa:
- Cálculo da distância ortodrômica (Fórmula de Haversine) em quilômetros.
- Estimativa do tempo de chegada (ETA) do entregador até o restaurante.
- Filtragem geométrica exata por raio de atendimento R (km).
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Tuple

EARTH_RADIUS_KM = 6371.0088

# Velocidade média urbana estimada em BH (km/h) e fator de tortuosidade viária
DEFAULT_AVG_SPEED_KMH = 28.0
DEFAULT_ROAD_DETOUR_FACTOR = 1.28


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcula a distância geodésica (Haversine) em quilômetros entre dois pontos
    geográficos expressos em graus decimais.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    sin_dphi = math.sin(d_phi / 2.0)
    sin_dlambda = math.sin(d_lambda / 2.0)

    a = sin_dphi * sin_dphi + math.cos(phi1) * math.cos(phi2) * sin_dlambda * sin_dlambda
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return EARTH_RADIUS_KM * c


def estimate_eta_minutes(
    distance_km: float,
    avg_speed_kmh: float = DEFAULT_AVG_SPEED_KMH,
    detour_factor: float = DEFAULT_ROAD_DETOUR_FACTOR,
) -> float:
    """
    Estima o tempo de deslocamento (em minutos) até o restaurante a partir da
    distância em linha reta (aplicando fator de tortuosidade viária e velocidade média).
    Inclui um tempo mínimo de reação/partida de 1.0 minuto.
    """
    if distance_km <= 0.0:
        return 1.0
    effective_road_km = distance_km * detour_factor
    travel_minutes = (effective_road_km / avg_speed_kmh) * 60.0
    return round(max(1.0, travel_minutes), 1)


def filter_couriers_by_radius(
    rest_lat: float,
    rest_lon: float,
    candidate_couriers: List[Dict[str, Any]],
    radius_km: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Filtra os entregadores candidatos recuperados pela Trie que estejam dentro do
    raio de atendimento `radius_km` (em km) do restaurante.

    Retorna:
        Tupla (filtrados_dentro_do_raio, descartados_candidatos), onde
        `filtrados_dentro_do_raio` está ordenado pela distância crescente.
    """
    inside_radius: List[Dict[str, Any]] = []
    outside_radius: List[Dict[str, Any]] = []

    seen_ids = set()
    for courier in candidate_couriers:
        cid = courier["id"]
        if cid in seen_ids:
            continue
        seen_ids.add(cid)

        dist = haversine_distance_km(rest_lat, rest_lon, courier["lat"], courier["lon"])
        eta = estimate_eta_minutes(dist)

        enriched = {
            **courier,
            "distance_km": round(dist, 3),
            "eta_min": eta,
        }

        if dist <= radius_km:
            inside_radius.append(enriched)
        else:
            outside_radius.append(enriched)

    inside_radius.sort(key=lambda c: c["distance_km"])
    return inside_radius, outside_radius
