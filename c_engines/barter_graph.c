#include <stddef.h>
#include <stdlib.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

#define MAX_DEPTH 4

typedef struct {
    int user_id;
    int has_skill;
    int wants_skill;
} BarterNode;

typedef struct {
    int length;
    int users[MAX_DEPTH];
    int has_skills[MAX_DEPTH];
    int wants_skills[MAX_DEPTH];
} TradeLoop;

typedef struct {
    int count;
    TradeLoop *loops;
} BarterResult;

typedef struct {
    TradeLoop *items;
    int count;
    int capacity;
} LoopBuffer;

static int edge_exists(const BarterNode *from, const BarterNode *to) {
    return from->wants_skill == to->has_skill && from->user_id != to->user_id;
}

static int append_loop(LoopBuffer *buffer, const BarterNode *nodes, const int *path, int depth) {
    if (depth < 2 || depth > MAX_DEPTH) {
        return 1;
    }

    if (buffer->count >= buffer->capacity) {
        int new_capacity = buffer->capacity == 0 ? 8 : buffer->capacity * 2;
        TradeLoop *items = (TradeLoop *)realloc(buffer->items, (size_t)new_capacity * sizeof(TradeLoop));
        if (items == NULL) {
            return 0;
        }
        buffer->items = items;
        buffer->capacity = new_capacity;
    }

    TradeLoop loop;
    loop.length = depth;
    for (int i = 0; i < MAX_DEPTH; i++) {
        loop.users[i] = 0;
        loop.has_skills[i] = 0;
        loop.wants_skills[i] = 0;
    }
    for (int i = 0; i < depth; i++) {
        int idx = path[i];
        loop.users[i] = nodes[idx].user_id;
        loop.has_skills[i] = nodes[idx].has_skill;
        loop.wants_skills[i] = nodes[idx].wants_skill;
    }

    buffer->items[buffer->count++] = loop;
    return 1;
}

static int is_in_path(const int *path, int depth, int idx) {
    for (int i = 0; i < depth; i++) {
        if (path[i] == idx) {
            return 1;
        }
    }
    return 0;
}

static int is_canonical_cycle(const int *path, int depth) {
    int min_idx = path[0];
    for (int i = 1; i < depth; i++) {
        if (path[i] < min_idx) {
            min_idx = path[i];
        }
    }
    return path[0] == min_idx;
}

static int dfs(const BarterNode *nodes, int node_count, int start, int current, int *path, int depth, LoopBuffer *buffer) {
    if (depth > MAX_DEPTH) {
        return 1;
    }

    for (int next = 0; next < node_count; next++) {
        if (!edge_exists(&nodes[current], &nodes[next])) {
            continue;
        }

        if (next == start && depth >= 2) {
            if (is_canonical_cycle(path, depth)) {
                if (!append_loop(buffer, nodes, path, depth)) {
                    return 0;
                }
            }
            continue;
        }

        if (depth < MAX_DEPTH && !is_in_path(path, depth, next)) {
            path[depth] = next;
            if (!dfs(nodes, node_count, start, next, path, depth + 1, buffer)) {
                return 0;
            }
        }
    }

    return 1;
}

EXPORT BarterResult *find_trade_loops(const BarterNode *nodes, int node_count) {
    BarterResult *result = (BarterResult *)calloc(1, sizeof(BarterResult));
    if (result == NULL || nodes == NULL || node_count <= 0) {
        return result;
    }

    LoopBuffer buffer = {0};
    int path[MAX_DEPTH] = {0};

    for (int start = 0; start < node_count; start++) {
        path[0] = start;
        if (!dfs(nodes, node_count, start, start, path, 1, &buffer)) {
            free(buffer.items);
            return result;
        }
    }

    result->count = buffer.count;
    result->loops = buffer.items;
    return result;
}

EXPORT void free_results(BarterResult *result) {
    if (result == NULL) {
        return;
    }
    free(result->loops);
    free(result);
}
