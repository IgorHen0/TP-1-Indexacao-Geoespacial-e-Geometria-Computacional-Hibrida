# Trabalho Prático 1 — Indexação Geoespacial e Geometria Computacional Híbrida

Motor de busca e monitoramento geoespacial híbrido para visualização e consulta em tempo real de uma frota de entregadores operando em **Belo Horizonte (MG)**, integrando **codificação Geohash (8 níveis)**, **Árvore Trie Compacta (Radix Tree)** e **Geometria Computacional (Fórmula de Haversine)** sobre a malha viária real do **OpenStreetMap (`osmnx`)** e a base de estabelecimentos **`bares.csv`**.

---

## 1. Arquitetura e Componentes Obrigatórios

Toda a implementação das estruturas de dados e algoritmos centrais foi desenvolvida **100% de forma autoral** (sem uso de bibliotecas externas para Geohash ou Trie), localizada em `src/core/`:

1. **Codificação Geohash e Vizinhança (`src/core/geohash.py`)**:
   - Conversão de coordenadas `(latitude, longitude)` em strings Base32 de **8 níveis** (40 bits: 20 bits de longitude intercalados com 20 bits de latitude).
   - Decodificação para caixa delimitadora (*bounding box*) e cálculo das **8 células adjacentes** (`N, NE, E, SE, S, SW, W, NW`), eliminando o **problema de borda** antes da filtragem geométrica final.
2. **Árvore Trie Compacta / Radix Tree (`src/core/radix_trie.py`)**:
   - Compressão de caminhos unários em arestas rotuladas por substrings (`edge_label`), reduzindo drasticamente o consumo de memória e o número de nós internos.
   - Divisão automática de arestas (*edge split*) na inserção e busca por prefixo em tempo **$O(m + k)$**, onde $m$ é o comprimento do prefixo consultado e $k$ é o número de entregadores contidos na região/bairro.
3. **Filtragem Geométrica e Estimativa de ETA (`src/core/geometry.py`)**:
   - Cálculo exato da distância geodésica via **Fórmula de Haversine** (em km) para filtrar os candidatos retornados pela Trie dentro do raio de atendimento $R$ parametrizável.
   - Estimativa de tempo de chegada (**ETA** em minutos) considerando velocidade média urbana e fator de tortuosidade viária.
4. **Simulador de Frota com Demanda Normal, Geocodificação Predial e Restrição Viária (`src/simulation/`)**:
   - **Geocodificação Predial Exata (`src/simulation/geocoder.py`)**: Resolve o endereço completo dos restaurantes de `bares.csv` (logradouro + número exato do imóvel + bairro em Belo Horizonte) com cache persistente em `data/exact_address_cache.json`, garantindo que o pino do restaurante caia exatamente no número predial correto da via.
   - **Distribuição Espacial Baseada em Demanda (`src/simulation/fleet_generator.py`)**: Distribui os $N$ entregadores equitativamente entre os restaurantes georreferenciados da base `bares.csv` seguindo uma distribuição normal ($\mathcal{N}(\mu, \sigma^2)$), concentrando maior densidade no entorno imediato dos estabelecimentos.
   - **Restrição Viária (Snapping)**: Projeta cada ponto matemático gerado para a coordenada real de rua transitável mais próxima da malha viária de Belo Horizonte (extraída via `osmnx` e indexada espacialmente), evitando pontos na Lagoa da Pampulha, rios ou dentro de edifícios/quarteirões.

---

## 2. Estrutura do Repositório

```text
TP1/
├── bares.csv                           # Base de dados original de bares e restaurantes de BH
├── data/
│   ├── bh_road_points.parquet          # Cache de 55.735 pontos viários transitáveis de BH (OSMnx)
│   ├── restaurantes_georref.parquet    # Cache de 4.000 restaurantes georreferenciados na malha de BH
│   ├── exact_address_cache.json        # Cache persistente de geocodificação predial exata (número + bairro)
│   └── benchmark_results.csv           # Resultados experimentais de tempo de resposta (runtime)
├── src/
│   ├── core/
│   │   ├── geohash.py                  # Codificação Geohash (8 níveis) + cálculo de 8 células vizinhas
│   │   ├── radix_trie.py               # Árvore Trie Compacta (Radix Tree) com busca O(m + k)
│   │   └── geometry.py                 # Distância de Haversine, filtro de raio e cálculo de ETA
│   ├── simulation/
│   │   ├── preprocess_data.py          # Extração do grafo viário OSMnx de BH e matching com bares.csv
│   │   ├── geocoder.py                 # Geocodificação predial exata (logradouro + número + bairro) com cache
│   │   └── fleet_generator.py          # Geração sintética (Distribuição Normal + Snapping Viário)
│   └── ui/
│       └── app.py                      # Aplicação interativa em Dash + Dash-Leaflet + Bootstrap (OpenStreetMap)
├── scripts/
│   └── benchmark.py                    # Script de avaliação experimental de escalabilidade e runtime
├── tests/
│   └── test_core.py                    # Testes unitários automatizados (Geohash, Trie Compacta, Borda)
├── docs/
│   └── RELATORIO_TECNICO.md            # Relatório Final detalhado com decisões de projeto e experimentos
├── Dockerfile                          # Imagem Docker para execução containerizada
└── requirements.txt                    # Dependências do projeto
```

---

## 3. Instruções de Execução

### Opção A: Ambiente Virtual Python (Local)

1. Crie o ambiente virtual e instale as dependências:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. (Opcional) Caso deseje regerar o cache da malha viária de BH e dos restaurantes a partir do `bares.csv` (os arquivos processados já estão disponíveis em `data/`):
   ```bash
   PYTHONPATH=. python3 src/simulation/preprocess_data.py
   ```

3. Execute os testes unitários automatizados:
   ```bash
   PYTHONPATH=. pytest -v
   ```

4. Inicie a interface web interativa:
   ```bash
   PYTHONPATH=. python3 src/ui/app.py
   ```
   Acesse no navegador: **`http://localhost:8050`**

### Opção B: Execução via Docker

```bash
docker build -t tp1-geofleet-bh .
docker run -p 8050:8050 tp1-geofleet-bh
```
Acesse no navegador: **`http://localhost:8050`**

---

## 4. Como Utilizar a Interface Interativa

1. **Simulador de Frota (Painel Esquerdo)**:
   - Informe qualquer quantidade inteira desejada de entregadores ($N \in [1, 20.000]$) no campo numérico e pressione `Enter` ou clique em **"Gerar Entregadores"** (também é possível ajustar o controle deslizante de dispersão $\sigma$ da distribuição normal em metros).
   - O sistema descartará todos os entregadores anteriores (limpando a Trie Compacta e o mapa), gerará $N$ novas coordenadas com distribuição normal centrada nos restaurantes, projetará cada coordenada para a rua transitável mais próxima de BH e indexará os novos Geohashes de 8 níveis na Trie.
2. **Busca de Restaurante e Filtragem por Raio**:
   - Pesquise qualquer restaurante/bar de Belo Horizonte pelo **Nome Fantasia**, **Razão Social**, **Logradouro** ou **Bairro**.
   - Ajuste o **Raio de Atendimento ($R$)** em quilômetros (ex.: `2.0 km`).
   - O mapa atualizará dinamicamente exibindo:
     - **Pinos Vermelhos (Destaque)**: Entregadores dentro do raio de atendimento $R$.
     - **Pinos Cinzas (Sem Destaque)**: Entregadores descartados.
     - **Grade das 9 Células Geohash**: Célula central do restaurante + 8 células adjacentes consultadas na Trie.
   - Abaixo do mapa, a **Tabela Descritiva** apresenta os IDs dos entregadores, seus Geohashes de 8 níveis, distâncias exatas (km) e estimativa de tempo de chegada (ETA em minutos), acompanhada dos cartões de métricas e **tempo de resposta (runtime em ms)** no topo.
