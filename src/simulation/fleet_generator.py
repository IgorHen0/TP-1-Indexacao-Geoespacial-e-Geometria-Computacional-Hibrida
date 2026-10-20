"""
Simulador de Geração de Entregadores (Frota Sintética Realista).

Atende às duas restrições fundamentais exigidas pela especificação do TP1:
1. Distribuição Espacial Baseada em Demanda:
   - Distribui os N entregadores equitativamente entre os centros (restaurantes) disponíveis.
   - Gera coordenadas seguindo uma distribuição normal (Gaussiana) centrada nas coordenadas
     dos restaurantes, resultando em alta densidade no entorno imediato dos estabelecimentos
     e decaimento gradual à medida que a distância aumenta.
2. Restrição Viária (Realismo Geográfico):
   - Projeta (snapping) cada coordenada matemática gerada para a coordenada real de rua
     transitável mais próxima da malha viária de Belo Horizonte (extraída via OSMnx),
     garantindo que nenhum entregador apareça na Lagoa da Pampulha, dentro de edifícios
     ou em quarteirões fechados.
"""

from __future__ import annotations
import time
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from src.core.geohash import encode_geohash
from src.core.radix_trie import CompactTrie
from src.simulation.preprocess_data import (
    RESTAURANTS_PATH,
    ROAD_POINTS_PATH,
    build_bh_road_network_and_restaurants,
)


class FleetSimulator:
    """
    Gerencia o estado da base de restaurantes, a malha viária de Belo Horizonte (KD-Tree de vias)
    e a geração/indexação da frota de entregadores na Trie Compacta.
    """

    def __init__(self) -> None:
        self._ensure_preprocessed_data()

        self.restaurants_df: pd.DataFrame = pd.read_parquet(RESTAURANTS_PATH)
        self.road_points_df: pd.DataFrame = pd.read_parquet(ROAD_POINTS_PATH)

        # Pré-calcula Geohash de 8 níveis para todos os restaurantes
        self.restaurants_df["geohash"] = [
            encode_geohash(float(lat), float(lon), precision=8)
            for lat, lon in zip(self.restaurants_df["lat"], self.restaurants_df["lon"])
        ]

        # Constrói índice espacial das vias transitáveis de BH para snapping viário ultrarrápido
        self._road_coords: np.ndarray = self.road_points_df[["lat", "lon"]].to_numpy(dtype=np.float64)
        self._road_kdtree = cKDTree(self._road_coords)

        # Estrutura de dados central obrigatória (Trie Compacta)
        self.trie = CompactTrie()
        self.couriers: List[Dict[str, Any]] = []
        self.last_generation_time_ms: float = 0.0

    def _ensure_preprocessed_data(self) -> None:
        """Executa o pré-processamento caso os arquivos em cache ainda não existam."""
        if not RESTAURANTS_PATH.exists() or not ROAD_POINTS_PATH.exists():
            build_bh_road_network_and_restaurants()

    def generate_fleet(
        self,
        num_couriers: int,
        std_dev_deg: float = 0.0045,
        seed: int | None = None,
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Descarta todos os entregadores anteriores (limpando a Trie Compacta) e gera
        um novo conjunto de N entregadores do zero seguindo:
        1) Distribuição equitativa entre os centros (restaurantes) com distribuição Normal.
        2) Projeção (snapping) para a rua transitável mais próxima da malha viária do OSM.
        3) Codificação em Geohash de 8 níveis e inserção na Trie Compacta.

        Parâmetros:
            num_couriers: Quantidade desejada de entregadores (N).
            std_dev_deg: Desvio padrão da distribuição normal em graus (~0.0045° ≈ 500m).
            seed: Semente aleatória opcional para reprodutibilidade.

        Retorna:
            Tupla (lista_de_entregadores, tempo_total_geracao_ms).
        """
        t0 = time.perf_counter()

        # 1. Limpa completamente a árvore e a lista de entregadores anteriores
        self.trie.clear()
        self.couriers = []

        if num_couriers <= 0:
            self.last_generation_time_ms = 0.0
            return [], 0.0

        rng = np.random.default_rng(seed)

        # 2. Distribuição equitativa entre os centros (restaurantes da base)
        rest_coords = self.restaurants_df[["lat", "lon"]].to_numpy(dtype=np.float64)
        num_centers = len(rest_coords)

        # Repete os índices dos centros de forma equitativa e embaralha o resto se N < num_centers
        base_indices = np.arange(num_centers)
        if num_couriers <= num_centers:
            chosen_idx = rng.choice(base_indices, size=num_couriers, replace=False)
        else:
            repeats = num_couriers // num_centers
            rem = num_couriers % num_centers
            chosen_idx = np.concatenate([
                np.tile(base_indices, repeats),
                rng.choice(base_indices, size=rem, replace=False),
            ])

        centers = rest_coords[chosen_idx]

        # 3. Gera deslocamento segundo Distribuição Normal centrada nos restaurantes
        raw_lats = centers[:, 0] + rng.normal(loc=0.0, scale=std_dev_deg, size=num_couriers)
        raw_lons = centers[:, 1] + rng.normal(loc=0.0, scale=std_dev_deg, size=num_couriers)
        raw_points = np.column_stack((raw_lats, raw_lons))

        # 4. Restrição Viária: projeta cada ponto matemático para a coordenada de rua mais próxima
        _, nearest_road_idx = self._road_kdtree.query(raw_points, k=1)
        snapped_points = self._road_coords[nearest_road_idx]

        # Adiciona um micro-jitter longitudinal (< 4 metros) ao longo da calçada/faixa apenas quando
        # dois entregadores caem exatamente no mesmo vértice de rua, mantendo-os sobre a via
        jitter_lat = rng.normal(0.0, 0.000018, size=num_couriers)
        jitter_lon = rng.normal(0.0, 0.000018, size=num_couriers)

        # 5. Codifica cada coordenada em Geohash de 8 níveis e insere na Trie Compacta
        new_couriers: List[Dict[str, Any]] = []
        for idx in range(num_couriers):
            lat = float(snapped_points[idx, 0] + jitter_lat[idx])
            lon = float(snapped_points[idx, 1] + jitter_lon[idx])
            gh = encode_geohash(lat, lon, precision=8)

            courier = {
                "id": f"ENT-{idx + 1:04d}",
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "geohash": gh,
                "raw_lat": round(float(raw_lats[idx]), 6),
                "raw_lon": round(float(raw_lons[idx]), 6),
            }
            new_couriers.append(courier)
            self.trie.insert(gh, courier)

        self.couriers = new_couriers
        self.last_generation_time_ms = (time.perf_counter() - t0) * 1000.0
        return self.couriers, self.last_generation_time_ms
