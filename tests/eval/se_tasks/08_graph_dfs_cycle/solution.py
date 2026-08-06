def dfs(graph, start):
    visited = set()
    def go(n):
        visited.add(n)
        for nb in graph.get(n, []):
            if nb not in visited:
                go(nb)
    go(start)
    return visited
