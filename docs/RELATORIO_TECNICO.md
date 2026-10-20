# Relatório Técnico Final — Indexação Geoespacial e Geometria Computacional Híbrida

## 1. Introdução e Definição do Problema

Plataformas modernas de logística urbana e entrega sob demanda (como iFood, Uber Eats e Rappi) operam sobre frotas dinâmicas de milhares de entregadores distribuídos em malhas viárias densas. Quando um cliente simula ou realiza um pedido em um restaurante localizado nas coordenadas $(\phi_r, \lambda_r)$, o sistema precisa identificar instantaneamente quais entregadores estão disponíveis dentro de um raio de atendimento $R$ (por exemplo, $R = 2\text{ km}$) e estimar o tempo de chegada (ETA) de cada um.

Calcular a distância geodésica exata (via Fórmula de Haversine) entre o restaurante e todos os $N$ entregadores da cidade a cada consulta exige tempo linear $O(N)$, o que se torna um gargalo severo quando há milhares de consultas simultâneas por segundo.

Para resolver esse problema com eficiência assintótica ideal, este projeto implementa um **motor de busca e monitoramento geoespacial híbrido** para a cidade de **Belo Horizonte (MG)** dividido em duas fases:
1. **Filtragem Espacial Rápida por Prefixo ($O(m + k)$)**: As coordenadas 2D $(\text{latitude}, \text{longitude})$ são linearizadas em strings unidimensionais de **8 níveis** em Base32 utilizando a codificação **Geohash** e indexadas em uma **Árvore Trie Compacta (Radix Tree)**. Para eliminar falsos negativos nas divisões de células (problema de borda), a busca consulta a célula central do restaurante e suas **8 células adjacentes**.
2. **Refinamento Geométrico Exato**: Os $k$ entregadores candidatos retornados pela Trie ($k \ll N$) passam pelo cálculo da distância ortodrômica de **Haversine**, filtrando apenas aqueles com distância $d \le R$ e ordenando-os por proximidade e tempo estimado de chegada (ETA).

---

## 2. Decisões de Projeto e Implementação Algorítmica

Todas as estruturas de dados centrais foram implementadas do zero em Python puro (`src/core/`), sem utilização de bibliotecas externas para Geohash ou árvores de prefixos.

### 2.1. Codificação Geohash por Intercalação Binária (`src/core/geohash.py`)
- **Bisseção Sucessiva de Intervalos**: A latitude $\phi \in [-90^\circ, 90^\circ]$ e a longitude $\lambda \in [-180^\circ, 180^\circ]$ são convertidas em sequências de bits por subdivisão binária do intervalo.
- **Intercalação de Bits**: Bits em posições pares ($0, 2, 4, \dots$) codificam a longitude e bits em posições ímpares ($1, 3, 5, \dots$) codificam a latitude.
- **Representação Base32 em 8 Níveis**: Cada grupo de 5 bits é mapeado para um caractere do alfabeto Base32 (`0123456789bcdefghjkmnpqrstuvwxyz`). Com **8 níveis de precisão** (40 bits no total: 20 de longitude e 20 de latitude), cada célula foliar possui dimensões aproximadas de $38\text{m} \times 19\text{m}$ na latitude de Belo Horizonte ($\approx -19.92^\circ$), oferecendo resolução espacial de nível de quadra/edifício.

### 2.2. Tratamento do Problema de Borda (Células Adjacentes e Janela Adaptativa)
A grade hierárquica do Geohash possui uma propriedade crítica: dois pontos geograficamente muito próximos podem estar separados por uma linha divisória de célula e, consequentemente, apresentar prefixos diferentes.
- Para resolver o problema de borda antes da filtragem geométrica final, implementamos as funções `get_neighbors(geohash_prefix)` e `get_covering_cells_for_radius(lat, lon, radius_km)` em `src/core/geohash.py`:
  1. Decodifica o prefixo de consulta para obter o ponto central $(\phi_c, \lambda_c)$ e as dimensões $(\Delta\phi, \Delta\lambda)$ da célula naquele nível (`choose_prefix_precision_for_radius`).
  2. Projetamos os centros das **8 células vizinhas** ($\text{N, NE, E, SE, S, SW, W, NW}$) aplicando deslocamentos $(\pm \Delta\phi, \pm \Delta\lambda)$ e recodificamos cada centro com o mesmo tamanho de prefixo $m$.
  3. Assim, a consulta na Trie é executada sobre as **9 células** (grade $3 \times 3$ central + adjacentes), garantindo cobertura integral da circunferência de raio $R$ sem falsos negativos nas fronteiras de divisão.

### 2.3. Estrutura de Nós da Árvore Trie Compacta (`src/core/radix_trie.py`)
Em vez de uma Trie comum (onde cada nível armazena apenas um caractere e cria longos caminhos de nós com apenas um filho), implementamos uma **Trie Compacta (Radix Tree / Patricia Trie)**:
- **Estrutura do Nó (`RadixNode`)**:
  - `edge_label: str` — Substring compactada que rotula a aresta de chegada ao nó (ex.: `"7h2y8"` em vez de 5 nós encadeados `'7' -> 'h' -> '2' -> 'y' -> '8'`).
  - `children: dict[str, RadixNode]` — Tabela hash indexada pelo primeiro caractere do `edge_label` de cada filho, garantindo decisão de ramificação em tempo constante $O(1)$.
  - `items: list[dict]` — Lista de entregadores cujos Geohashes de 8 níveis terminam exatamente naquele nó.
- **Inserção com Split de Aresta**: Ao inserir uma chave `key`, percorremos os rótulos das arestas. Caso ocorra uma divergência parcial no índice `common_len` de um `edge_label`, o nó existente é dividido (*split*) em um nó intermediário com `label[:common_len]` e dois ramos filhos (`label[common_len:]` e `remaining[common_len:]`).
- **Garantia de Complexidade $O(m + k)$ na Busca**:
  - A fase de descida consome os $m$ caracteres do prefixo buscado em no máximo $m$ passos ($O(m)$). Mesmo que o prefixo buscado termine no meio do `edge_label` de uma aresta compactada, o nó filho correspondente já representa toda a subárvore daquele prefixo.
  - A fase de coleta percorre a subárvore a partir do nó alcançado. Como todo nó interno em uma Trie Compacta possui fator de ramificação $\ge 2$, o número de nós internos na subárvore é estritamente limitado pelo número de folhas com entregadores, garantindo tempo de coleta proporcional a $O(k)$.

---

## 3. Pré-processamento Geográfico, Geocodificação Predial e Simulador de Entregadores

### 3.1. Georreferenciamento de `bares.csv` com Precisão de Número Predial (`src/simulation/geocoder.py`)
O arquivo fornecido `bares.csv` contém 20.860 estabelecimentos de Belo Horizonte com endereço textual (`DESC_LOGRADOURO`, `NOME_LOGRADOURO`, `NUMERO_IMOVEL`, `NOME_BAIRRO`), sem coordenadas explícitas de latitude e longitude. Para evitar imprecisões ao longo de vias extensas (como a Av. Presidente Antônio Carlos ou a Rua Padre Pedro Pinto, que cruzam múltiplos bairros), implementamos uma abordagem em duas camadas:
1. **Extração da Malha Viária de BH (`src/simulation/preprocess_data.py`)**: Extraímos o grafo completo da malha viária transitável (`network_type="drive"`) de Belo Horizonte via `osmnx` (**32.399 nós** e **83.160 segmentos de vias**), salvando **55.735 pontos viários** em `data/bh_road_points.parquet` e gerando a base `data/restaurantes_georref.parquet` com **4.000 estabelecimentos**.
2. **Geocodificação ao Nível do Número do Imóvel (`src/simulation/geocoder.py`)**: Implementamos a classe `ExactAddressGeocoder`, que resolve o endereço completo (`Logradouro + Número do Imóvel + Bairro + Belo Horizonte`) com precisão predial (*PointAddress* / *StreetAddress*) e persiste os resultados em cache local (`data/exact_address_cache.json`). Dessa forma, cada restaurante consultado na interface é posicionado exatamente no número predial e quarteirão corretos sobre os tiles oficiais do OpenStreetMap (`tile.openstreetmap.org`).

### 3.2. Geração Sintética de Frota (`src/simulation/fleet_generator.py`)
Ao informar uma quantidade arbitrária $N \in [1, 20.000]$ no campo numérico da interface, ajustar a dispersão $\sigma$ (em metros) ou clicar no botão **"Gerar Entregadores"**:
1. **Descarte Completo**: A Trie Compacta e o mapa são imediatamente esvaziados (`trie.clear()`).
2. **Distribuição Espacial Baseada em Demanda**: Os $N$ entregadores são distribuídos equitativamente entre os restaurantes disponíveis. Para cada centro $(\mu_\phi, \mu_\lambda)$, sorteia-se um deslocamento segundo uma **Distribuição Normal** $\Delta\phi, \Delta\lambda \sim \mathcal{N}(0, \sigma^2)$, gerando alta densidade de entregadores nas zonas boêmias/comerciais (Savassi, Centro, Lourdes, Pampulha, Venda Nova, Padre Eustáquio) e decaimento gradual conforme a distância aumenta.
3. **Restrição Viária (Snapping para Rua Mais Próxima)**: Coordenadas puramente gaussianas podem cair dentro da Lagoa da Pampulha, parques ou no interior de quarteirões edificados. Para garantir realismo geográfico, indexamos os **55.735 pontos viários transitáveis** de Belo Horizonte em uma `cKDTree` e projetamos cada entregador para a rua transitável mais próxima antes de codificar seu Geohash de 8 níveis e inseri-lo na Trie Compacta.

---

## 4. Avaliação Experimental e Tempo de Resposta (Runtime)

Os experimentos foram conduzidos pelo script `scripts/benchmark.py` (resultados completos salvos em `data/benchmark_results.csv`), avaliando frotas de $N = 100$ até $N = 10.000$ entregadores em Belo Horizonte, calculando a média de 20 consultas em diferentes restaurantes para raios de $1.0\text{ km}$ e $2.0\text{ km}$:

| Frota ($N$) | Raio ($R$) | Nós na Trie Compacta | Tempo Geração Frota (ms) | Candidatos Trie ($k$ médio) | Filtrados no Raio | Runtime Busca Trie (ms) | Runtime Total Híbrido (ms) | Busca Linear Exaustiva (ms) | Ganho (Speedup) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **100** | 1.0 km | 134 | 1.85 ms | 5.0 | 2.6 | 0.0436 ms | **0.0534 ms** | 0.0466 ms | 0.9x |
| **500** | 1.0 km | 655 | 4.90 ms | 23.5 | 12.4 | 0.0480 ms | **0.0897 ms** | 0.3004 ms | **3.3x** |
| **1.000** | 1.0 km | 1.275 | 9.10 ms | 49.1 | 26.4 | 0.0552 ms | **0.1339 ms** | 0.4911 ms | **3.7x** |
| **2.500** | 1.0 km | 2.986 | 21.40 ms | 121.3 | 64.5 | 0.0769 ms | **0.2750 ms** | 1.3115 ms | **4.8x** |
| **5.000** | 1.0 km | 5.612 | 42.10 ms | 240.3 | 126.3 | 0.1243 ms | **0.5711 ms** | 2.5379 ms | **4.4x** |
| **10.000** | 1.0 km | 10.473 | 83.50 ms | 478.3 | 251.8 | 0.2080 ms | **1.0907 ms** | 5.6397 ms | **5.2x** |
| **10.000** | 2.0 km | 10.473 | 83.50 ms | 478.3 | 463.1 | 0.2039 ms | **1.1514 ms** | 5.4864 ms | **4.8x** |

### Análise dos Resultados Experimentais:
1. **Eficiência de Memória da Trie Compacta**: Para $N = 10.000$ chaves de 8 caracteres (que exigiriam até $80.000$ nós em uma Trie não compactada no pior caso), a Trie Compacta utilizou apenas **10.473 nós**, reduzindo drasticamente o consumo de memória e os saltos de ponteiros durante a busca.
2. **Seletividade Espacial e Tempo Sub-milissegundo**: Para uma frota de $2.500$ entregadores, a busca nas 9 células Geohash na Trie Compacta leva apenas **0,076 ms (76 microssegundos)** e reduz o espaço de busca de $2.500$ para apenas $\approx 121$ candidatos locais, resultando em um tempo total de resposta de **0,275 ms** (quase **5 vezes mais rápido** que a varredura linear).
3. **Eliminação Total do Problema de Borda**: Conforme validado pelo teste automatizado `test_hybrid_search_no_boundary_false_negatives` (`tests/test_core.py`), a busca combinando a célula central e suas 8 adjacentes obteve **100% de precisão (recall = 1.0)** em relação à busca exaustiva, mesmo quando o restaurante foi posicionado a menos de 5 metros da fronteira entre células Geohash.
