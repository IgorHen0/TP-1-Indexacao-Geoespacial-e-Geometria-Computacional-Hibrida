"""
Testes unitários e de integração para validar as estruturas de dados e algoritmos do TP1:
- Codificação/decodificação Geohash (8 níveis Base32) e busca de 8 células adjacentes.
- Janela adaptativa de cobertura Geohash (`get_covering_cells_for_radius`).
- Árvore Trie Compacta (Radix Tree) com divisão de arestas e busca por prefixo O(m + k).
- Filtragem geométrica (Haversine) e ausência de falsos negativos na borda de células.
- Simulador de frota (`FleetSimulator`) com qualquer valor de N (ex.: 150) e snapping viário.
- Geocodificação predial exata (`ExactAddressGeocoder`) para endereços de Belo Horizonte.
"""

import random
from src.core.geohash import (
    encode_geohash,
    decode_bbox,
    decode_center,
    get_neighbors,
    get_covering_cells_for_radius,
    choose_prefix_precision_for_radius,
)
from src.core.radix_trie import CompactTrie
from src.core.geometry import haversine_distance_km, filter_couriers_by_radius
from src.simulation.fleet_generator import FleetSimulator
from src.simulation.geocoder import ExactAddressGeocoder


def test_geohash_encoding_and_decoding():
    # Praça Sete de Setembro, Belo Horizonte (-19.9191, -43.9386)
    lat, lon = -19.9191, -43.9386
    gh = encode_geohash(lat, lon, precision=8)
    assert len(gh) == 8
    assert gh.startswith("7h2y")

    # O ponto original deve estar contido dentro da caixa delimitadora decodificada
    lat_min, lat_max, lon_min, lon_max = decode_bbox(gh)
    assert lat_min <= lat <= lat_max
    assert lon_min <= lon <= lon_max


def test_geohash_neighbors_count_and_boundary_coverage():
    # Prefixo de nível 5 na região central de BH
    prefix = encode_geohash(-19.9191, -43.9386, precision=5)
    cells = get_neighbors(prefix)
    assert len(cells) == 9
    assert cells[0] == prefix
    assert len(set(cells)) == 9


def test_compact_trie_insert_split_and_search():
    trie = CompactTrie()

    items = [
        ("6gkzq91a", {"id": 1, "name": "A"}),
        ("6gkzq91b", {"id": 2, "name": "B"}),
        ("6gkzq800", {"id": 3, "name": "C"}),
        ("6gkz1111", {"id": 4, "name": "D"}),
        ("6gkx0000", {"id": 5, "name": "E"}),
    ]
    for gh, item in items:
        trie.insert(gh, item)

    assert trie.total_items == 5
    # Em uma Trie Compacta, o número de nós deve ser muito menor que 5 * 8 = 40
    assert trie.total_nodes < 12

    # Busca por prefixo que termina no meio de uma aresta compactada ("6gkzq9")
    res_q9 = trie.search_prefix("6gkzq9")
    assert {r["id"] for r in res_q9} == {1, 2}

    # Busca por prefixo "6gkzq"
    res_q = trie.search_prefix("6gkzq")
    assert {r["id"] for r in res_q} == {1, 2, 3}

    # Busca por prefixo inexistente
    assert trie.search_prefix("6gkzz") == []


def test_hybrid_search_no_boundary_false_negatives():
    """
    Garante que a busca híbrida (Trie com 9 células adjacentes + filtro Haversine)
    encontra 100% dos mesmos entregadores que uma busca exaustiva (força bruta)
    mesmo quando o restaurante está exatamente sobre a borda de uma célula Geohash.
    """
    rng = random.Random(42)
    trie = CompactTrie()

    # Posiciona o restaurante bem na borda de uma célula Geohash de nível 5
    base_prefix = encode_geohash(-19.92, -43.94, precision=5)
    lat_min, lat_max, lon_min, lon_max = decode_bbox(base_prefix)
    rest_lat = lat_min + 0.00005  # Quase na linha divisória sul
    rest_lon = lon_max - 0.00005  # Quase na linha divisória leste

    couriers = []
    for i in range(500):
        c_lat = rest_lat + rng.uniform(-0.04, 0.04)
        c_lon = rest_lon + rng.uniform(-0.04, 0.04)
        gh = encode_geohash(c_lat, c_lon, precision=8)
        c_obj = {"id": i, "lat": c_lat, "lon": c_lon, "geohash": gh}
        couriers.append(c_obj)
        trie.insert(gh, c_obj)

    for radius_km in [0.4, 1.5, 2.0, 3.5]:
        p_level = choose_prefix_precision_for_radius(radius_km)
        rest_prefix = encode_geohash(rest_lat, rest_lon, precision=p_level)
        neighbor_prefixes = get_neighbors(rest_prefix)

        candidates = trie.search_multiple_prefixes(neighbor_prefixes)
        filtered_hybrid, _ = filter_couriers_by_radius(rest_lat, rest_lon, candidates, radius_km)
        hybrid_ids = {c["id"] for c in filtered_hybrid}

        # Busca exaustiva (força bruta) para comparação
        brute_force_ids = {
            c["id"]
            for c in couriers
            if haversine_distance_km(rest_lat, rest_lon, c["lat"], c["lon"]) <= radius_km
        }

        assert hybrid_ids == brute_force_ids, f"Diferença encontrada para raio {radius_km} km!"

        # Também valida get_covering_cells_for_radius
        _, _, cov_prefixes = get_covering_cells_for_radius(rest_lat, rest_lon, radius_km)
        cov_candidates = trie.search_multiple_prefixes(cov_prefixes)
        cov_filtered, _ = filter_couriers_by_radius(rest_lat, rest_lon, cov_candidates, radius_km)
        assert {c["id"] for c in cov_filtered} == brute_force_ids


def test_fleet_simulator_arbitrary_counts_and_reset():
    """
    Valida que o simulador descarta a frota anterior e gera exatamente N entregadores
    para qualquer número inteiro (ex.: 150, 75), indexando todos na Trie Compacta.
    """
    sim = FleetSimulator()

    couriers_150, _ = sim.generate_fleet(num_couriers=150, std_dev_deg=0.0045, seed=10)
    assert len(couriers_150) == 150
    assert sim.trie.total_items == 150

    couriers_75, _ = sim.generate_fleet(num_couriers=75, std_dev_deg=0.0045, seed=20)
    assert len(couriers_75) == 75
    assert sim.trie.total_items == 75


def test_exact_address_geocoder_house_numbers():
    """
    Valida que o ExactAddressGeocoder retorna as coordenadas prediais corretas para os
    endereços de Belo Horizonte verificados nos testes visuais (erro1, erro2, erro3).
    """
    geocoder = ExactAddressGeocoder()

    # 1. RUA PADRE PEDRO PINTO, 1500 - VENDA NOVA
    lat1, lon1 = geocoder.geocode_address("RUA PADRE PEDRO PINTO, 1500 - VENDA NOVA", -19.9, -43.9)
    assert haversine_distance_km(lat1, lon1, -19.814675, -43.954390) < 0.15

    # 2. RUA ITORORO, 801 - PADRE EUSTAQUIO
    lat2, lon2 = geocoder.geocode_address("RUA ITORORO, 801 - PADRE EUSTAQUIO", -19.9, -43.9)
    assert haversine_distance_km(lat2, lon2, -19.917004, -43.977273) < 0.15

    # 3. AVE PRESIDENTE ANTONIO CARLOS, 6627 - CAMPUS UFMG
    lat3, lon3 = geocoder.geocode_address("AVE PRESIDENTE ANTONIO CARLOS, 6627 - CAMPUS UFMG", -19.9, -43.9)
    assert haversine_distance_km(lat3, lon3, -19.863193, -43.958818) < 0.15
