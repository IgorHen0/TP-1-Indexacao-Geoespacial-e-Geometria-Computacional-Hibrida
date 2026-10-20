"""
Script de Pré-processamento Geográfico e Georreferenciamento (Belo Horizonte).

Este módulo:
1. Baixa a malha viária transitável ('drive') de Belo Horizonte via `osmnx` (OpenStreetMap).
2. Extrai os pontos de vias transitáveis (nós e pontos intermediários das arestas) e os
   salva em `data/bh_road_points.parquet` para permitir o *snapping* viário instantâneo.
3. Indexa os nomes dos logradouros das ruas de Belo Horizonte presentes no OSM e realiza
   o cruzamento com os registros de `bares.csv` (normalizando nomes de ruas, números e bairros),
   gerando o arquivo `data/restaurantes_georref.parquet` com coordenadas reais sobre a malha viária.
"""

from __future__ import annotations
import os
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import osmnx as ox
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_CSV_PATH = PROJECT_ROOT / "bares.csv"
ROAD_POINTS_PATH = DATA_DIR / "bh_road_points.parquet"
RESTAURANTS_PATH = DATA_DIR / "restaurantes_georref.parquet"


def normalize_text(text: str) -> str:
    """Remove acentos, caracteres especiais e converte para maiúsculas."""
    if not isinstance(text, str):
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_str = ascii_str.upper().strip()
    ascii_str = re.sub(r"[^A-Z0-9\s]", " ", ascii_str)
    ascii_str = re.sub(r"\s+", " ", ascii_str).strip()
    return ascii_str


def strip_street_prefix(name_norm: str) -> str:
    """Remove prefixos de tipo de logradouro (RUA, AVENIDA, PRACA, etc.) para facilitar o matching."""
    prefixes = (
        "AVENIDA ", "AVE ", "AV ", "RUA ", "PRACA ", "PCA ", "ALAMEDA ", "ALA ",
        "ESTRADA ", "EST ", "RODOVIA ", "ROD ", "TRAVESSA ", "TRV ", "BECO ", "BEC ",
        "VIADUTO ", "VIA ", "LARGO ", "LRG "
    )
    for p in prefixes:
        if name_norm.startswith(p):
            return name_norm[len(p):].strip()
    return name_norm


def _download_bh_graph():
    """Tenta baixar o grafo viário de BH usando espelhos oficiais da Overpass API."""
    overpass_endpoints = [
        "https://overpass.private.coffee/api",
        "https://maps.mail.ru/osm/tools/overpass/api",
        "https://overpass-api.de/api",
    ]
    ox.settings.requests_timeout = 180
    ox.settings.use_cache = True

    last_err = None
    for endpoint in overpass_endpoints:
        try:
            print(f"      Consultando endpoint Overpass: {endpoint} ...")
            ox.settings.overpass_url = endpoint
            return ox.graph_from_place(
                "Belo Horizonte, Minas Gerais, Brazil",
                network_type="drive",
                simplify=True,
            )
        except Exception as exc:
            print(f"      [Aviso] Falha em {endpoint}: {exc}. Tentando próximo espelho...")
            last_err = exc
    raise RuntimeError(f"Não foi possível baixar o grafo do OSM: {last_err}")


def build_bh_road_network_and_restaurants(max_restaurants: int = 4000) -> None:
    """
    Baixa o grafo viário de Belo Horizonte via OSMnx, extrai os pontos das vias
    para snapping e georreferencia os restaurantes do `bares.csv`.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] Baixando grafo da malha viária de Belo Horizonte via OSMnx...")
    G = _download_bh_graph()
    nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)

    print(f"      Grafo carregado: {len(nodes_gdf)} nós e {len(edges_gdf)} segmentos de rua.")

    # 1. Extrair pontos densos das vias para Snapping Viário (nós + pontos médios das arestas)
    road_lats: List[float] = nodes_gdf["y"].astype(float).tolist()
    road_lons: List[float] = nodes_gdf["x"].astype(float).tolist()
    road_names: List[str] = [""] * len(road_lats)

    # Indexar segmentos por nome de rua normalizado (sem prefixo RUA/AVE)
    street_coords_map: Dict[str, List[Tuple[float, float]]] = {}

    print("[2/4] Processando geometrias das vias e indexando logradouros...")
    for _, row in edges_gdf.iterrows():
        raw_name = row.get("name", None)
        if isinstance(raw_name, list):
            names = [str(n) for n in raw_name if n]
        elif isinstance(raw_name, str):
            names = [raw_name]
        else:
            names = []

        geom = row.get("geometry", None)
        if geom is not None:
            coords = list(geom.coords)
            # Ponto médio do segmento
            mid_lon, mid_lat = coords[len(coords) // 2]
            road_lats.append(float(mid_lat))
            road_lons.append(float(mid_lon))
            road_names.append(names[0] if names else "")

            # Amostrar pontos do segmento para o mapa de logradouros
            sample_pts = [(float(lat), float(lon)) for lon, lat in coords]
        else:
            continue

        for nm in names:
            norm_full = normalize_text(nm)
            norm_core = strip_street_prefix(norm_full)
            if len(norm_core) >= 3:
                street_coords_map.setdefault(norm_core, []).extend(sample_pts)
                street_coords_map.setdefault(norm_full, []).extend(sample_pts)

    road_df = pd.DataFrame({
        "lat": np.array(road_lats, dtype=np.float32),
        "lon": np.array(road_lons, dtype=np.float32),
    }).drop_duplicates()

    road_df.to_parquet(ROAD_POINTS_PATH, index=False)
    print(f"      Salvo cache de {len(road_df)} pontos viários em: {ROAD_POINTS_PATH}")

    # 2. Ler bares.csv e cruzar com os logradouros da malha viária de BH
    print("[3/4] Lendo bares.csv e georreferenciando restaurantes na malha de BH...")
    df_bares = pd.read_csv(RAW_CSV_PATH)

    # Priorizar registros que possuem NOME_FANTASIA preenchido para melhor experiência na interface
    df_bares["FANTASIA_CLEAN"] = df_bares["NOME_FANTASIA"].fillna("").astype(str).str.strip()
    df_bares["NOME_CLEAN"] = df_bares["NOME"].fillna("").astype(str).str.strip()
    df_bares["DISPLAY_NAME"] = np.where(
        df_bares["FANTASIA_CLEAN"] != "",
        df_bares["FANTASIA_CLEAN"],
        df_bares["NOME_CLEAN"],
    )

    # Ordena priorizando os que têm Nome Fantasia
    df_bares["HAS_FANTASIA"] = df_bares["FANTASIA_CLEAN"] != ""
    df_bares = df_bares.sort_values(by=["HAS_FANTASIA", "_id"], ascending=[False, True])

    rng = np.random.default_rng(42)
    matched_records = []

    for _, row in df_bares.iterrows():
        logr_raw = str(row.get("NOME_LOGRADOURO", ""))
        logr_norm = strip_street_prefix(normalize_text(logr_raw))
        if not logr_norm or logr_norm not in street_coords_map:
            continue

        pts = street_coords_map[logr_norm]
        # Usa o número do imóvel para escolher deterministicamente uma posição ao longo da via
        num_str = str(row.get("NUMERO_IMOVEL", "0"))
        num_digits = re.sub(r"\D", "", num_str)
        num_val = int(num_digits) if num_digits else 0
        idx = (num_val * 7 + int(row["_id"])) % len(pts)
        base_lat, base_lon = pts[idx]

        # Se houver mais de um ponto na via, interpola levemente entre dois pontos consecutivos da mesma rua
        if len(pts) > 1:
            idx2 = (idx + 1) % len(pts)
            frac = ((int(row["_id"]) % 100) / 100.0) * 0.5
            lat = base_lat * (1.0 - frac) + pts[idx2][0] * frac
            lon = base_lon * (1.0 - frac) + pts[idx2][1] * frac
        else:
            lat, lon = base_lat, base_lon

        desc_logr = str(row.get("DESC_LOGRADOURO", "")).strip()
        bairro = str(row.get("NOME_BAIRRO", "")).strip()
        endereco = f"{desc_logr} {logr_raw.strip()}, {num_str} - {bairro}"

        matched_records.append({
            "id": int(row["_id"]),
            "nome_exibicao": str(row["DISPLAY_NAME"]),
            "razao_social": str(row["NOME_CLEAN"]),
            "nome_fantasia": str(row["FANTASIA_CLEAN"]),
            "categoria": str(row.get("DESCRICAO_CNAE_PRINCIPAL", "")).strip(),
            "endereco": endereco,
            "bairro": bairro,
            "lat": round(float(lat), 6),
            "lon": round(float(lon), 6),
        })

        if len(matched_records) >= max_restaurants:
            break

    df_rest = pd.DataFrame(matched_records)
    df_rest.to_parquet(RESTAURANTS_PATH, index=False)
    print(f"[4/4] Georreferenciamento concluído! {len(df_rest)} restaurantes salvos em: {RESTAURANTS_PATH}")


if __name__ == "__main__":
    build_bh_road_network_and_restaurants()
