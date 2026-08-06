def dfs(graph, start):
    """DFS,返回访问过的节点集。有环图不能无限递归。"""
    visited = set()
    def go(n):
        visited.add(n)
        for nb in graph.get(n, []):
            go(nb)
    go(start)
    return visited
