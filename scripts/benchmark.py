"""
Script de Avaliação Experimental (Benchmark de Tempo de Resposta e Escalabilidade).

Executa consultas automatizadas para diferentes tamanhos de frota (N = 100 a 10.000)
e diferentes raios de atendimento (R = 0.5 km a 5.0 km), registrando:
- Tempo de geração da frota (Distribuição Normal + Snapping Viário + Inserção na Trie Compacta).
- Número de nós na Trie Compacta vs. Trie comum não compacta.
- Tempo de busca por prefixo nas 9 células Geohash O(m + k).
- Tempo de filtragem geométrica (Haversine).
- Tempo total de consulta (runtime) e comparação com busca linear exaustiva.
"""

from __future__ import annotations
import time
import pandas as pd

from src.core.geohash import (
    choose_prefix_precision_for_radius,
    encode_geohash,
    get_neighbors,
)
from src.core.geometry import filter_couriers_by_radius, haversine_distance_km
from src.simulation.fleet_generator import FleetSimulator


def run_benchmarks() -> None:
    sim = FleetSimulator()
    sample_restaurants = sim.restaurants_df.head(20).to_dict("records")

    fleet_sizes = [100, 500, 1000, 2500, 5000, 10000]
    radii_km = [1.0, 2.0, 3.0]

    rows = []
    print("=" * 85)
    print("BENCHMARK EXPERIMENTAL - INDEXAÇÃO GEOESPACIAL (GEOHASH + TRIE COMPACTA)")
    print("=" * 85)

    for n in fleet_sizes:
        _, gen_ms = sim.generate_fleet(num_couriers=n, std_dev_deg=0.0045, seed=42)
        trie_nodes = sim.trie.total_nodes

        for r_km in radii_km:
            trie_times = []
            filter_times = []
            total_times = []
            brute_times = []
            cand_counts = []
            inside_counts = []

            p_level = choose_prefix_precision_for_radius(r_km)

            for rest in sample_restaurants:
                rlat, rlon = float(rest["lat"]), float(rest["lon"])

                # 1. Busca Híbrida (Trie Compacta + Filtro Geométrico)
                t0 = time.perf_counter()
                r_gh = encode_geohash(rlat, rlon, precision=p_level)
                prefixes = get_neighbors(r_gh)
                candidates = sim.trie.search_multiple_prefixes(prefixes)
                t1 = time.perf_counter()
                inside, _ = filter_couriers_by_radius(rlat, rlon, candidates, r_km)
                t2 = time.perf_counter()

                # 2. Busca Linear Exaustiva (Baseline sem indexação)
                tb0 = time.perf_counter()
                _brute = [
                    c for c in sim.couriers
                    if haversine_distance_km(rlat, rlon, c["lat"], c["lon"]) <= r_km
                ]
                tb1 = time.perf_counter()

                trie_times.append((t1 - t0) * 1000.0)
                filter_times.append((t2 - t1) * 1000.0)
                total_times.append((t2 - t0) * 1000.0)
                brute_times.append((tb1 - tb0) * 1000.0)
                cand_counts.append(len(candidates))
                inside_counts.append(len(inside))

            avg_trie = sum(trie_times) / len(trie_times)
            avg_filt = sum(filter_times) / len(filter_times)
            avg_tot = sum(total_times) / len(total_times)
            avg_brute = sum(brute_times) / len(brute_times)
            avg_cand = sum(cand_counts) / len(cand_counts)
            avg_in = sum(inside_counts) / len(inside_counts)
            speedup = avg_brute / avg_tot if avg_tot > 0 else 1.0

            rows.append({
                "N_Frota": n,
                "Raio_km": r_km,
                "Nivel_Prefixo": p_level,
                "Nos_Trie_Compacta": trie_nodes,
                "Geracao_Frota_ms": round(gen_ms, 2),
                "Candidatos_k_Medio": round(avg_cand, 1),
                "Filtrados_Raio_Medio": round(avg_in, 1),
                "Tempo_Trie_ms": round(avg_trie, 4),
                "Tempo_Filtro_ms": round(avg_filt, 4),
                "Tempo_Total_Hibrido_ms": round(avg_tot, 4),
                "Tempo_Busca_Linear_ms": round(avg_brute, 4),
                "Speedup_vs_Linear": round(speedup, 2),
            })

            print(
                f"N={n:5d} | R={r_km:.1f}km | Nós Trie={trie_nodes:4d} | "
                f"Cand(k)={avg_cand:5.1f} | Filtrados={avg_in:4.1f} | "
                f"Runtime Híbrido={avg_tot:.4f} ms (Trie={avg_trie:.4f} ms) vs Linear={avg_brute:.4f} ms "
                f"[{speedup:.1f}x mais rápido]"
            )

    df_res = pd.DataFrame(rows)
    out_csv = sim.restaurants_df_path = "data/benchmark_results.csv"
    df_res.to_csv(out_csv, index=False)
    print("=" * 85)
    print(f"Resultados experimentais salvos em: {out_csv}")


if __name__ == "__main__":
    run_benchmarks()
