---
title: Data structures and algorithms
summary: The core ideas behind efficient programs — lists, maps, stacks, queues, trees, graphs, sorting, searching and Big-O.
tags: [computer-science, algorithms, data-structures, big-o, interviews, pathfinding]
---
# Data structures and algorithms

## Big-O in one minute
Big-O describes how work grows as input grows. O(1): constant (dict lookup). O(log n): halving each step (binary search). O(n): one pass. O(n log n): good sorting. O(n²): nested loops over the same data — fine for 100 items, painful for 1,000,000.

## Core data structures
| Structure | Good at | Python | JavaScript |
|---|---|---|---|
| Array / list | Ordered items, index access O(1) | `list` | `Array` |
| Hash map | Lookup by key O(1) | `dict` | `Map` / object |
| Set | Membership, removing duplicates | `set` | `Set` |
| Stack | Last in, first out (undo, DFS) | `list.append/pop` | `push/pop` |
| Queue | First in, first out (BFS, tasks) | `collections.deque` | array + index, or a library |
| Heap / priority queue | Always get the smallest next (Dijkstra, A*) | `heapq` | library |
| Tree | Hierarchies, sorted data | classes | classes |
| Graph | Networks, maps, robot path planning | dict of lists | `Map` of arrays |

## Key algorithms
- **Binary search**: find in sorted data by halving — O(log n).
- **Sorting**: use the built-in sort (O(n log n)); learn merge sort and quicksort to understand it.
- **Recursion**: a function that solves a smaller version of the same problem; needs a base case.
- **BFS**: explores neighbors level by level; shortest path in unweighted grids (robot on a grid map).
- **DFS**: goes deep first; mazes, detecting cycles.
- **Dijkstra / A\***: shortest paths with costs; A* adds a distance estimate and is standard in robotics and games.
- **Dynamic programming**: remember answers to sub-problems instead of recomputing.

## Learning path
### Level 1 — Using structures well
Lists, dicts, sets; choosing the right one; Big-O intuition.
Exercise: find duplicate names in a list of 100,000 in under a second.

### Level 2 — Classic algorithms
Binary search, sorting algorithms, recursion, stacks and queues.
Exercise: implement binary search and merge sort and test them.

### Level 3 — Graphs
Graph representations, BFS, DFS, Dijkstra, A*.
Exercise: a grid maze solver that prints the shortest path.

### Level 4 — Problem solving
Dynamic programming, greedy algorithms, practice problems (LeetCode, Advent of Code).
Exercise: solve 10 problems, explaining the time complexity of each.

## Complete example
```python run
from collections import deque

GRID = [
    "S.#.....",
    ".##.###.",
    "....#...",
    ".#.##.#.",
    "...#..#G",
]


def shortest_path(grid):
    """Breadth-first search: the classic way a robot finds the shortest route on a grid map."""
    rows, cols = len(grid), len(grid[0])
    start = next((r, c) for r in range(rows) for c in range(cols) if grid[r][c] == "S")
    came_from = {start: None}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        r, c = cell
        if grid[r][c] == "G":
            path = []
            while cell:
                path.append(cell)
                cell = came_from[cell]
            return path[::-1]
        for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] != "#" and (nr, nc) not in came_from:
                came_from[(nr, nc)] = cell
                queue.append((nr, nc))
    return None


path = shortest_path(GRID)
print(f"Shortest path: {len(path) - 1} steps")
for r, row in enumerate(GRID):
    print("".join("*" if (r, c) in path and ch == "." else ch for c, ch in enumerate(row)))
```
