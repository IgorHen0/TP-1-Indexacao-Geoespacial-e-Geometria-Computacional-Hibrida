"""
Implementação Autoral de Árvore Trie Compacta (Radix Tree / Patricia Trie)
para Indexação e Busca por Prefixo de Geohashes.

Complexidade garantida:
- Inserção: O(m), onde m é o tamanho do Geohash (8 níveis).
- Busca por prefixo: O(m + k), onde m é o tamanho do prefixo consultado e k é o
  número de entregadores encontrados na subárvore. Como a árvore é compacta (sem
  caminhos unários redundantes), o número de nós internos visitados na subárvore é
  estritamente limitado por O(k).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class RadixNode:
    """
    Nó de uma Trie Compacta (Radix Tree).

    Atributos:
        edge_label: Substring que rotula a aresta de entrada para este nó.
        children: Dicionário que mapeia o primeiro caractere da aresta filha para o RadixNode filho.
        items: Lista de entregadores (dicionários/objetos) cujos Geohashes terminam exatamente neste nó.
    """
    edge_label: str = ""
    children: Dict[str, "RadixNode"] = field(default_factory=dict)
    items: List[Any] = field(default_factory=list)


def _common_prefix_length(s1: str, s2: str) -> int:
    """Retorna o tamanho do maior prefixo comum entre duas strings."""
    limit = min(len(s1), len(s2))
    idx = 0
    while idx < limit and s1[idx] == s2[idx]:
        idx += 1
    return idx


class CompactTrie:
    """
    Árvore Trie Compacta (Radix Tree) para indexação espacial via Geohash.
    Totalmente implementada sem uso de bibliotecas externas.
    """

    def __init__(self) -> None:
        self.root = RadixNode(edge_label="")
        self.total_items = 0
        self.total_nodes = 1  # Conta a raiz

    def clear(self) -> None:
        """Descarta todos os entregadores e reinicia a árvore do zero."""
        self.root = RadixNode(edge_label="")
        self.total_items = 0
        self.total_nodes = 1

    def insert(self, key: str, item: Any) -> None:
        """
        Insere um item associado à chave `key` (ex.: Geohash de 8 níveis) na Trie Compacta.
        Realiza divisão (split) de arestas quando há casamento parcial de prefixo.
        """
        if not key:
            raise ValueError("A chave Geohash não pode ser vazia.")

        current = self.root
        remaining = key

        while remaining:
            first_char = remaining[0]
            child = current.children.get(first_char)

            # Caso 1: Não existe aresta iniciando com `first_char` -> cria nova folha
            if child is None:
                new_node = RadixNode(edge_label=remaining, items=[item])
                current.children[first_char] = new_node
                self.total_items += 1
                self.total_nodes += 1
                return

            # Calcula prefixo comum entre o restante da chave e o rótulo da aresta filha
            label = child.edge_label
            common_len = _common_prefix_length(remaining, label)

            # Caso 2: A aresta filha inteira é prefixo de `remaining` -> avança na árvore
            if common_len == len(label):
                remaining = remaining[common_len:]
                current = child
                if not remaining:
                    current.items.append(item)
                    self.total_items += 1
                    return
                continue

            # Caso 3: Divergência no meio do rótulo da aresta -> faz split do nó `child`
            common_prefix = label[:common_len]
            child_suffix = label[common_len:]
            remaining_suffix = remaining[common_len:]

            # Cria nó intermediário com o prefixo comum
            split_node = RadixNode(edge_label=common_prefix)
            self.total_nodes += 1

            # Atualiza o nó filho antigo para conter apenas o sufixo restante
            child.edge_label = child_suffix
            split_node.children[child_suffix[0]] = child

            # Liga o nó atual ao novo nó intermediário
            current.children[first_char] = split_node

            if not remaining_suffix:
                # A chave inserida termina exatamente no nó intermediário
                split_node.items.append(item)
                self.total_items += 1
            else:
                # Cria um novo ramo folha a partir do nó intermediário
                new_leaf = RadixNode(edge_label=remaining_suffix, items=[item])
                split_node.children[remaining_suffix[0]] = new_leaf
                self.total_items += 1
                self.total_nodes += 1
            return

    def search_prefix(self, prefix: str) -> List[Any]:
        """
        Busca todos os itens cujas chaves iniciam com `prefix` em tempo O(m + k),
        onde m = len(prefix) e k = número de itens retornados.
        """
        if not prefix:
            return self._collect_all(self.root)

        current = self.root
        remaining = prefix

        # 1. Fase de descida até esgotar o prefixo: O(m)
        while remaining:
            first_char = remaining[0]
            child = current.children.get(first_char)
            if child is None:
                return []

            label = child.edge_label
            common_len = _common_prefix_length(remaining, label)

            if common_len == len(remaining):
                # Todo o prefixo buscado foi consumido (mesmo que no meio da aresta `label`)
                return self._collect_all(child)

            if common_len == len(label):
                # Consumiu a aresta inteira e ainda resta parte do prefixo
                remaining = remaining[common_len:]
                current = child
            else:
                # Divergência antes de terminar o prefixo -> nenhum elemento casa
                return []

        return self._collect_all(current)

    def search_multiple_prefixes(self, prefixes: List[str]) -> List[Any]:
        """
        Realiza a busca na Trie para múltiplos prefixos (ex.: célula central + 8 adjacentes)
        e retorna a lista consolidada de itens encontrados.
        """
        results: List[Any] = []
        for prefix in prefixes:
            results.extend(self.search_prefix(prefix))
        return results

    def _collect_all(self, start_node: RadixNode) -> List[Any]:
        """
        Coleta todos os itens na subárvore enraizada em `start_node` usando busca em
        profundidade iterativa em O(k).
        """
        collected: List[Any] = []
        stack = [start_node]
        while stack:
            node = stack.pop()
            if node.items:
                collected.extend(node.items)
            for child in node.children.values():
                stack.append(child)
        return collected
