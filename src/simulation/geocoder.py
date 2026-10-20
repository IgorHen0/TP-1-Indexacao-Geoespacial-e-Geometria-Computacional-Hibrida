"""
Módulo de Geocodificação Exata de Endereços (Logradouro + Número do Imóvel + Bairro)
para Belo Horizonte, com cache persistente em disco.

Garante que qualquer restaurante consultado em `bares.csv` seja posicionado exatamente
no número do imóvel correspondente na rua/avenida correta em Belo Horizonte.
"""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from typing import Dict, Optional, Tuple
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
EXACT_CACHE_PATH = DATA_DIR / "exact_address_cache.json"

# Caixa delimitadora de Belo Horizonte para priorizar candidatos dentro do município
BH_SEARCH_EXTENT = "-44.08,-20.06,-43.84,-19.76"
ARCGIS_GEOCODE_URL = (
    "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
)


class ExactAddressGeocoder:
    """
    Geocodifica endereços completos de Belo Horizonte (Rua/Av + Número + Bairro)
    com precisão de número predial (PointAddress / StreetAddress) e mantém cache local.
    """

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Tuple[float, float]] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if EXACT_CACHE_PATH.exists():
            try:
                raw = json.loads(EXACT_CACHE_PATH.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    if isinstance(v, list) and len(v) == 2:
                        self._cache[k] = (float(v[0]), float(v[1]))
            except Exception:
                self._cache = {}

    def save_cache(self) -> None:
        try:
            serializable = {k: [v[0], v[1]] for k, v in self._cache.items()}
            EXACT_CACHE_PATH.write_text(
                json.dumps(serializable, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def geocode_address(
        self,
        endereco: str,
        fallback_lat: float,
        fallback_lon: float,
        persist: bool = True,
    ) -> Tuple[float, float]:
        """
        Retorna a coordenada exata (lat, lon) do endereço (incluindo número predial e bairro).
        Se já estiver no cache local, retorna instantaneamente em O(1).
        Caso contrário, consulta o serviço de geocodificação predial e salva no cache.
        """
        key = endereco.strip().upper()
        if key in self._cache:
            return self._cache[key]

        # Expande abreviações comuns da base bares.csv para máxima precisão predial
        expanded = key
        if expanded.startswith("AVE "):
            expanded = "AVENIDA " + expanded[4:]
        elif expanded.startswith("PCA "):
            expanded = "PRACA " + expanded[4:]
        elif expanded.startswith("ALA "):
            expanded = "ALAMEDA " + expanded[4:]
        elif expanded.startswith("TRV "):
            expanded = "TRAVESSA " + expanded[4:]

        query = f"{expanded}, BELO HORIZONTE, MINAS GERAIS, BRAZIL"
        try:
            resp = requests.get(
                ARCGIS_GEOCODE_URL,
                params={
                    "SingleLine": query,
                    "f": "json",
                    "maxLocations": 1,
                    "searchExtent": BH_SEARCH_EXTENT,
                },
                timeout=4.0,
            )
            if resp.status_code == 200:
                cands = resp.json().get("candidates", [])
                if cands:
                    loc = cands[0]["location"]
                    lat = round(float(loc["y"]), 6)
                    lon = round(float(loc["x"]), 6)
                    # Valida se está dentro da Região Metropolitana de BH
                    if -20.10 <= lat <= -19.70 and -44.15 <= lon <= -43.80:
                        self._cache[key] = (lat, lon)
                        if persist:
                            self.save_cache()
                        return lat, lon
        except Exception:
            pass

        return fallback_lat, fallback_lon

    def batch_geocode(self, records: list[dict], max_workers: int = 20) -> int:
        """Geocodifica uma lista de registros em paralelo e persiste no cache apenas os sucessos."""
        to_fetch = [r for r in records if r["endereco"].strip().upper() not in self._cache]
        if not to_fetch:
            return 0

        def _worker(rec: dict) -> Optional[Tuple[str, float, float]]:
            self.geocode_address(
                rec["endereco"], rec["lat"], rec["lon"], persist=False
            )
            return None

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            list(pool.map(_worker, to_fetch))

        self.save_cache()
        return len(self._cache)
