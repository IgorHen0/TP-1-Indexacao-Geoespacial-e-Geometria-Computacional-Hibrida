"""
Aplicação Principal Web Interativa (Dash + Dash-Leaflet + Bootstrap).

Permite:
- Geração sintética de N entregadores em Belo Horizonte seguindo distribuição Normal
  centrada nos restaurantes da base (`bares.csv`) + projeção para a malha viária do OSM.
- Busca e seleção de restaurante (por nome fantasia, razão social, endereço ou bairro).
- Ajuste dinâmico do raio de atendimento R (km) e visualização opcional das 9 células
  da grade Geohash consultadas (central + 8 adjacentes).
- Mapa interativo com pinos em destaque (vermelhos) para entregadores dentro do raio,
  pinos sem destaque (cinzas) para entregadores descartados e pino especial para o restaurante.
- Tabela descritiva ordenada por distância contendo ID, Geohash (8 níveis), coordenadas,
  distância (km) e estimativa de tempo de chegada (ETA em minutos), além de métricas de runtime.
"""

from __future__ import annotations
import time
from typing import Any, Dict, List, Tuple

import dash
from dash import Dash, Input, Output, State, callback, dash_table, dcc, html
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from src.core.geohash import (
    choose_prefix_precision_for_radius,
    decode_bbox,
    encode_geohash,
    get_neighbors,
)
from src.core.geometry import filter_couriers_by_radius, haversine_distance_km, estimate_eta_minutes
from src.simulation.fleet_generator import FleetSimulator
from src.simulation.geocoder import ExactAddressGeocoder

# Inicializa o geocodificador de precisão predial (com cache local) e o simulador
exact_geocoder = ExactAddressGeocoder()
simulator = FleetSimulator()
simulator.generate_fleet(num_couriers=500, std_dev_deg=0.0045, seed=42)

# Prepara opções de restaurantes para o componente de busca
RESTAURANTS_RECORDS = simulator.restaurants_df.to_dict("records")
RESTAURANTS_BY_ID: Dict[int, Dict[str, Any]] = {int(r["id"]): r for r in RESTAURANTS_RECORDS}

DROPDOWN_OPTIONS = [
    {
        "label": f"{r['nome_exibicao']} — {r['bairro']} ({r['endereco']})",
        "value": int(r["id"]),
    }
    for r in RESTAURANTS_RECORDS[:2500]
]
DEFAULT_RESTAURANT_ID = DROPDOWN_OPTIONS[0]["value"] if DROPDOWN_OPTIONS else None


def _build_geohash_cell_polygons(prefixes: List[str], center_prefix: str) -> List[Any]:
    """Cria polígonos Dash-Leaflet para exibir a célula central e as 8 células adjacentes."""
    polygons = []
    for p in prefixes:
        lat_min, lat_max, lon_min, lon_max = decode_bbox(p)
        positions = [
            [lat_min, lon_min],
            [lat_max, lon_min],
            [lat_max, lon_max],
            [lat_min, lon_max],
        ]
        is_center = p == center_prefix
        polygons.append(
            dl.Polygon(
                positions=positions,
                color="#2563eb" if is_center else "#64748b",
                weight=2 if is_center else 1,
                dashArray="4, 4" if not is_center else None,
                fillColor="#3b82f6" if is_center else "#94a3b8",
                fillOpacity=0.08 if is_center else 0.03,
                children=[
                    dl.Tooltip(
                        f"Célula Geohash {'Central' if is_center else 'Adjacente'}: {p}"
                    )
                ],
            )
        )
    return polygons


def create_app() -> Dash:
    app = Dash(
        __name__,
        external_stylesheets=[dbc.themes.FLATLY, dbc.icons.BOOTSTRAP],
        title="TP1 - Monitoramento Geoespacial Híbrido (Geohash + Trie Compacta)",
    )

    # Barra Superior (Navbar)
    navbar = dbc.Navbar(
        dbc.Container(
            [
                html.Div(
                    [
                        html.I(className="bi bi-geo-alt-fill text-danger me-2 fs-4"),
                        dbc.NavbarBrand(
                            "GeoFleet BH — Indexação Geoespacial (Geohash + Trie Compacta) & Geometria Computacional",
                            className="fw-bold text-white",
                        ),
                    ],
                    className="d-flex align-items-center",
                ),
                dbc.Badge(
                    "Belo Horizonte • OpenStreetMap + bares.csv",
                    color="light",
                    text_color="dark",
                    className="px-3 py-2",
                ),
            ],
            fluid=True,
        ),
        color="primary",
        dark=True,
        className="mb-3 shadow-sm",
    )

    # Painel Lateral de Controles
    sidebar = dbc.Card(
        dbc.CardBody(
            [
                html.H5(
                    [html.I(className="bi bi-sliders me-2"), "1. Simulador de Frota"],
                    className="card-title fw-bold text-primary mb-3",
                ),
                dbc.Label("Quantidade de Entregadores (N):", className="fw-semibold small"),
                dbc.InputGroup(
                    [
                        dbc.Input(
                            id="input-num-couriers",
                            type="number",
                            min=1,
                            max=20000,
                            step=1,
                            value=500,
                            debounce=True,
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-arrow-repeat me-1"), "Gerar Entregadores"],
                            id="btn-generate-fleet",
                            color="danger",
                            className="fw-semibold",
                        ),
                    ],
                    className="mb-2",
                ),
                dbc.Label(
                    "Dispersão da Demanda (σ normal em metros):",
                    className="fw-semibold small mt-1",
                ),
                dcc.Slider(
                    id="slider-std-dev",
                    min=200,
                    max=1200,
                    step=100,
                    value=500,
                    marks={200: "200m", 500: "500m", 800: "800m", 1200: "1.2km"},
                    tooltip={"placement": "bottom", "always_visible": False},
                ),
                html.Small(
                    "Distribuição normal centrada nos restaurantes + projeção (snapping) na malha viária do OSM.",
                    className="text-muted d-block mt-1 mb-3",
                ),
                html.Hr(),
                html.H5(
                    [html.I(className="bi bi-shop me-2"), "2. Consulta de Restaurante"],
                    className="card-title fw-bold text-primary mb-3",
                ),
                dbc.Label(
                    "Buscar Restaurante / Bar (Nome, Endereço ou Bairro):",
                    className="fw-semibold small",
                ),
                dcc.Dropdown(
                    id="dropdown-restaurant",
                    options=DROPDOWN_OPTIONS,
                    value=DEFAULT_RESTAURANT_ID,
                    placeholder="Digite o nome do restaurante, rua ou bairro...",
                    clearable=False,
                    className="mb-3",
                ),
                dbc.Label(
                    id="label-radius-value",
                    children="Raio de Atendimento (R): 2.0 km",
                    className="fw-semibold small",
                ),
                dcc.Slider(
                    id="slider-radius-km",
                    min=0.3,
                    max=5.0,
                    step=0.1,
                    value=2.0,
                    marks={0.5: "0.5km", 1.0: "1km", 2.0: "2km", 3.0: "3km", 4.0: "4km", 5.0: "5km"},
                    tooltip={"placement": "bottom", "always_visible": False},
                ),
                dbc.Checklist(
                    options=[
                        {
                            "label": " Exibir grade das 9 células Geohash (Central + 8 Adjacentes)",
                            "value": "show_grid",
                        },
                        {
                            "label": " Exibir entregadores descartados (pinos cinzas)",
                            "value": "show_discarded",
                        },
                    ],
                    value=["show_grid", "show_discarded"],
                    id="checklist-map-layers",
                    switch=True,
                    className="mt-3 small",
                ),
                html.Hr(),
                html.Div(id="restaurant-details-box", className="small"),
            ]
        ),
        className="shadow-sm border-0 h-100",
    )

    # Cards de Métricas Resumo
    metrics_row = dbc.Row(
        [
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div("Frota Total Indexada (Trie)", className="text-muted small fw-semibold"),
                            html.H4(id="metric-total-fleet", className="fw-bold text-primary mb-0"),
                            html.Small(id="metric-trie-nodes", className="text-muted"),
                        ],
                        className="py-2 px-3",
                    ),
                    className="shadow-sm border-0",
                ),
                md=3,
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div("Candidatos na Trie (9 Células)", className="text-muted small fw-semibold"),
                            html.H4(id="metric-trie-candidates", className="fw-bold text-info mb-0"),
                            html.Small(id="metric-geohash-prefix", className="text-muted"),
                        ],
                        className="py-2 px-3",
                    ),
                    className="shadow-sm border-0",
                ),
                md=3,
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div("Dentro do Raio (Destaque)", className="text-muted small fw-semibold"),
                            html.H4(id="metric-filtered-count", className="fw-bold text-danger mb-0"),
                            html.Small(id="metric-closest-eta", className="text-muted"),
                        ],
                        className="py-2 px-3",
                    ),
                    className="shadow-sm border-0",
                ),
                md=3,
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div("Tempo de Resposta (Runtime)", className="text-muted small fw-semibold"),
                            html.H4(id="metric-query-runtime", className="fw-bold text-success mb-0"),
                            html.Small(id="metric-runtime-breakdown", className="text-muted"),
                        ],
                        className="py-2 px-3",
                    ),
                    className="shadow-sm border-0",
                ),
                md=3,
            ),
        ],
        className="g-2 mb-3",
    )

    # Mapa Interativo (Dash-Leaflet)
    map_card = dbc.Card(
        dbc.CardBody(
            [
                dl.Map(
                    id="bh-map",
                    center=[-19.9191, -43.9386],
                    zoom=14,
                    style={"width": "100%", "height": "470px", "borderRadius": "8px"},
                    children=[
                        dl.TileLayer(
                            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                        ),
                        dl.LayerGroup(id="map-grid-layer"),
                        dl.LayerGroup(id="map-discarded-layer"),
                        dl.LayerGroup(id="map-filtered-layer"),
                        dl.LayerGroup(id="map-restaurant-layer"),
                    ],
                ),
                html.Div(
                    [
                        html.Span(
                            [html.Span("● ", style={"color": "#dc2626", "fontWeight": "bold"}), "Entregador Dentro do Raio (Filtrado)"],
                            className="me-4 small",
                        ),
                        html.Span(
                            [html.Span("● ", style={"color": "#64748b", "fontWeight": "bold"}), "Entregador Fora do Raio (Descartado)"],
                            className="me-4 small",
                        ),
                        html.Span(
                            [html.Span("★ ", style={"color": "#2563eb", "fontWeight": "bold"}), "Restaurante Consultado"],
                            className="me-4 small",
                        ),
                        html.Span(
                            [html.Span("▢ ", style={"color": "#2563eb", "fontWeight": "bold"}), "Células Geohash (Central + 8 Adjacentes)"],
                            className="small",
                        ),
                    ],
                    className="mt-2 d-flex flex-wrap align-items-center justify-content-center text-muted",
                ),
            ],
            className="p-2",
        ),
        className="shadow-sm border-0 mb-3",
    )

    # Tabela Descritiva de Entregadores Filtrados
    table_card = dbc.Card(
        dbc.CardBody(
            [
                html.Div(
                    [
                        html.H6(
                            [
                                html.I(className="bi bi-table me-2"),
                                "Entregadores Disponíveis no Raio de Atendimento (Ordenados por Distância / ETA)",
                            ],
                            className="fw-bold text-primary mb-0",
                        ),
                        html.Small(id="table-summary-subtitle", className="text-muted"),
                    ],
                    className="d-flex justify-content-between align-items-center mb-2",
                ),
                dash_table.DataTable(
                    id="couriers-table",
                    columns=[
                        {"name": "ID Entregador", "id": "id"},
                        {"name": "Geohash (8 níveis)", "id": "geohash"},
                        {"name": "Latitude", "id": "lat"},
                        {"name": "Longitude", "id": "lon"},
                        {"name": "Distância (km)", "id": "distance_km"},
                        {"name": "Tempo Estimado - ETA (min)", "id": "eta_min"},
                    ],
                    data=[],
                    page_size=8,
                    sort_action="native",
                    style_table={"overflowX": "auto"},
                    style_header={
                        "backgroundColor": "#f1f5f9",
                        "fontWeight": "bold",
                        "color": "#1e293b",
                        "border": "1px solid #e2e8f0",
                    },
                    style_cell={
                        "textAlign": "center",
                        "padding": "8px",
                        "fontFamily": "Inter, system-ui, sans-serif",
                        "fontSize": "13px",
                        "border": "1px solid #f1f5f9",
                    },
                    style_data_conditional=[
                        {
                            "if": {"row_index": 0},
                            "backgroundColor": "#fef2f2",
                            "fontWeight": "bold",
                        }
                    ],
                ),
            ],
            className="p-3",
        ),
        className="shadow-sm border-0",
    )

    app.layout = html.Div(
        [
            dcc.Store(id="store-fleet-version", data=1),
            navbar,
            dbc.Container(
                dbc.Row(
                    [
                        dbc.Col(sidebar, lg=4, className="mb-3"),
                        dbc.Col([metrics_row, map_card, table_card], lg=8),
                    ]
                ),
                fluid=True,
            ),
        ],
        style={"backgroundColor": "#f8fafc", "minHeight": "100vh"},
    )

    @app.callback(
        Output("store-fleet-version", "data"),
        [
            Input("btn-generate-fleet", "n_clicks"),
            Input("input-num-couriers", "value"),
            Input("slider-std-dev", "value"),
        ],
        State("store-fleet-version", "data"),
        prevent_initial_call=True,
    )
    def handle_generate_fleet(n_clicks: int, num_couriers: int, std_meters: float, current_ver: int) -> int:
        if num_couriers is None or int(num_couriers) < 1:
            return dash.no_update
        n_val = max(1, min(20000, int(num_couriers)))
        # 1 grau de latitude/longitude em BH equivale a ~111.1 km
        std_deg = float(std_meters or 500.0) / 111111.0
        simulator.generate_fleet(num_couriers=n_val, std_dev_deg=std_deg, seed=None)
        return (current_ver or 0) + 1

    @app.callback(
        Output("label-radius-value", "children"),
        Input("slider-radius-km", "value"),
    )
    def update_radius_label(radius_km: float) -> str:
        return f"Raio de Atendimento (R): {float(radius_km):.1f} km"

    @app.callback(
        [
            Output("map-grid-layer", "children"),
            Output("map-discarded-layer", "children"),
            Output("map-filtered-layer", "children"),
            Output("map-restaurant-layer", "children"),
            Output("bh-map", "center"),
            Output("couriers-table", "data"),
            Output("metric-total-fleet", "children"),
            Output("metric-trie-nodes", "children"),
            Output("metric-trie-candidates", "children"),
            Output("metric-geohash-prefix", "children"),
            Output("metric-filtered-count", "children"),
            Output("metric-closest-eta", "children"),
            Output("metric-query-runtime", "children"),
            Output("metric-runtime-breakdown", "children"),
            Output("restaurant-details-box", "children"),
            Output("table-summary-subtitle", "children"),
        ],
        [
            Input("dropdown-restaurant", "value"),
            Input("slider-radius-km", "value"),
            Input("checklist-map-layers", "value"),
            Input("store-fleet-version", "data"),
        ],
    )
    def handle_spatial_query(
        rest_id: int,
        radius_km: float,
        layer_flags: List[str],
        _fleet_version: int,
    ):
        rest = RESTAURANTS_BY_ID.get(int(rest_id), RESTAURANTS_RECORDS[0])
        rest_lat, rest_lon = exact_geocoder.geocode_address(
            rest["endereco"], float(rest["lat"]), float(rest["lon"])
        )
        rest["lat"] = rest_lat
        rest["lon"] = rest_lon
        radius_val = float(radius_km or 2.0)

        # --- FASE 1: Indexação e Busca por Prefixo na Trie Compacta (com 8 células adjacentes) ---
        t_start = time.perf_counter()
        rest_geohash_8 = encode_geohash(rest_lat, rest_lon, precision=8)
        prefix_level = choose_prefix_precision_for_radius(radius_val)
        center_prefix = rest_geohash_8[:prefix_level]
        neighbor_prefixes = get_neighbors(center_prefix)

        candidates = simulator.trie.search_multiple_prefixes(neighbor_prefixes)
        t_trie_end = time.perf_counter()

        # --- FASE 2: Filtragem Geométrica Exata (Fórmula de Haversine) ---
        filtered_inside, _ = filter_couriers_by_radius(
            rest_lat, rest_lon, candidates, radius_val
        )
        t_filter_end = time.perf_counter()

        trie_time_ms = (t_trie_end - t_start) * 1000.0
        filter_time_ms = (t_filter_end - t_trie_end) * 1000.0
        total_query_ms = (t_filter_end - t_start) * 1000.0

        inside_ids = {c["id"] for c in filtered_inside}

        # Camada 1: Grade Geohash (célula central + 8 adjacentes)
        grid_children = (
            _build_geohash_cell_polygons(neighbor_prefixes, center_prefix)
            if "show_grid" in (layer_flags or [])
            else []
        )

        # Camada 2: Entregadores descartados (Pinos Cinzas sem destaque)
        discarded_children = []
        if "show_discarded" in (layer_flags or []):
            # Limita a plotagem visual a até 1500 pinos cinzas para manter fluidez no navegador
            discarded_list = [c for c in simulator.couriers if c["id"] not in inside_ids][:1500]
            for c in discarded_list:
                discarded_children.append(
                    dl.CircleMarker(
                        center=[c["lat"], c["lon"]],
                        radius=5,
                        color="#64748b",
                        fillColor="#94a3b8",
                        fillOpacity=0.65,
                        weight=1,
                        children=[
                            dl.Tooltip(
                                f"{c['id']} (Fora do raio) | Geohash: {c['geohash']}"
                            )
                        ],
                    )
                )

        # Camada 3: Entregadores Filtrados em Destaque (Pinos Vermelhos)
        filtered_children = []
        for c in filtered_inside:
            filtered_children.append(
                dl.CircleMarker(
                    center=[c["lat"], c["lon"]],
                    radius=8,
                    color="#991b1b",
                    fillColor="#ef4444",
                    fillOpacity=0.95,
                    weight=2,
                    children=[
                        dl.Tooltip(
                            f"🔥 {c['id']} | Dist: {c['distance_km']:.2f} km | ETA: {c['eta_min']:.1f} min | Geohash: {c['geohash']}"
                        ),
                        dl.Popup(
                            html.Div(
                                [
                                    html.Strong(f"Entregador {c['id']}"),
                                    html.Br(),
                                    f"Geohash (8 níveis): {c['geohash']}",
                                    html.Br(),
                                    f"Coordenadas: ({c['lat']:.5f}, {c['lon']:.5f})",
                                    html.Br(),
                                    f"Distância: {c['distance_km']:.3f} km",
                                    html.Br(),
                                    f"ETA Estimado: {c['eta_min']:.1f} min",
                                ]
                            )
                        ),
                    ],
                )
            )

        # Camada 4: Restaurante e Círculo do Raio de Atendimento
        restaurant_children = [
            dl.Circle(
                center=[rest_lat, rest_lon],
                radius=radius_val * 1000.0,
                color="#dc2626",
                weight=2,
                fillColor="#ef4444",
                fillOpacity=0.10,
            ),
            dl.Marker(
                position=[rest_lat, rest_lon],
                children=[
                    dl.Tooltip(
                        f"🍽️ {rest['nome_exibicao']} (Geohash: {rest_geohash_8})",
                        permanent=False,
                    ),
                    dl.Popup(
                        html.Div(
                            [
                                html.Strong(rest["nome_exibicao"]),
                                html.Br(),
                                html.Span(rest["endereco"]),
                                html.Br(),
                                html.Small(f"Geohash: {rest_geohash_8}"),
                            ]
                        )
                    ),
                ],
            ),
        ]

        # Métricas e Detalhes
        total_fleet_str = f"{simulator.trie.total_items:,}".replace(",", ".")
        trie_nodes_str = f"{simulator.trie.total_nodes:,} nós na Trie Compacta".replace(",", ".")
        candidates_str = f"{len(candidates):,}".replace(",", ".")
        prefix_info_str = f"Prefixo Nível {prefix_level}: '{center_prefix}' (+8 adj)"
        filtered_count_str = f"{len(filtered_inside):,}".replace(",", ".")

        if filtered_inside:
            closest = filtered_inside[0]
            avg_dist = sum(c["distance_km"] for c in filtered_inside) / len(filtered_inside)
            closest_eta_str = f"Mais próximo: {closest['distance_km']:.2f} km ({closest['eta_min']:.1f} min)"
            subtitle_str = (
                f"Exibindo {len(filtered_inside)} entregadores encontrados | "
                f"Distância média: {avg_dist:.2f} km | "
                f"Menor ETA: {closest['eta_min']:.1f} min ({closest['id']})"
            )
        else:
            closest_eta_str = "Nenhum entregador no raio"
            subtitle_str = "Nenhum entregador disponível dentro do raio selecionado."

        runtime_str = f"{total_query_ms:.3f} ms"
        breakdown_str = f"Trie: {trie_time_ms:.3f} ms | Filtro: {filter_time_ms:.3f} ms"

        details_box = dbc.Alert(
            [
                html.Div(html.Strong(rest["nome_exibicao"]), className="mb-1"),
                html.Div([html.I(className="bi bi-pin-map me-1"), rest["endereco"]]),
                html.Div([html.I(className="bi bi-tag me-1"), rest["categoria"]], className="text-muted mt-1"),
                html.Hr(className="my-2"),
                html.Div(
                    [
                        html.Strong("Geohash (8 níveis): "),
                        html.Code(rest_geohash_8),
                    ]
                ),
                html.Div(
                    [
                        html.Strong("Células buscadas (9): "),
                        html.Code(", ".join(neighbor_prefixes)),
                    ],
                    className="mt-1",
                ),
                html.Div(
                    f"Tempo geração da frota ({simulator.trie.total_items} entreg.): {simulator.last_generation_time_ms:.1f} ms",
                    className="text-muted mt-2",
                ),
            ],
            color="light",
            className="border mb-0 p-2",
        )

        return (
            grid_children,
            discarded_children,
            filtered_children,
            restaurant_children,
            [rest_lat, rest_lon],
            filtered_inside,
            total_fleet_str,
            trie_nodes_str,
            candidates_str,
            prefix_info_str,
            filtered_count_str,
            closest_eta_str,
            runtime_str,
            breakdown_str,
            details_box,
            subtitle_str,
        )

    return app


if __name__ == "__main__":
    app_instance = create_app()
    app_instance.run(host="0.0.0.0", port=8050, debug=False)
