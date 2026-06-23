#include <math.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

#define EPSILON 0.000001

typedef struct {
    int from_id;
    int to_id;
    double amount;
} Debt;

typedef struct {
    int from_id;
    int to_id;
    double amount;
} Transaction;

typedef struct {
    int count;
    Transaction *transactions;
} SettlementResult;

typedef struct {
    int user_id;
    double balance;
} BalanceNode;

typedef struct {
    BalanceNode *items;
    int size;
    int capacity;
    int is_max_heap;
} Heap;

static void heap_swap(BalanceNode *a, BalanceNode *b) {
    BalanceNode tmp = *a;
    *a = *b;
    *b = tmp;
}

static int heap_better(const Heap *heap, double a, double b) {
    if (heap->is_max_heap) {
        return a > b;
    }
    return a < b;
}

static int heap_push(Heap *heap, BalanceNode node) {
    if (heap->size >= heap->capacity) {
        int new_capacity = heap->capacity == 0 ? 8 : heap->capacity * 2;
        BalanceNode *items = (BalanceNode *)realloc(heap->items, (size_t)new_capacity * sizeof(BalanceNode));
        if (items == NULL) {
            return 0;
        }
        heap->items = items;
        heap->capacity = new_capacity;
    }

    int idx = heap->size++;
    heap->items[idx] = node;

    while (idx > 0) {
        int parent = (idx - 1) / 2;
        if (!heap_better(heap, heap->items[idx].balance, heap->items[parent].balance)) {
            break;
        }
        heap_swap(&heap->items[idx], &heap->items[parent]);
        idx = parent;
    }

    return 1;
}

static BalanceNode heap_pop(Heap *heap) {
    BalanceNode result = heap->items[0];
    heap->items[0] = heap->items[--heap->size];

    int idx = 0;
    while (1) {
        int left = idx * 2 + 1;
        int right = left + 1;
        int best = idx;

        if (left < heap->size && heap_better(heap, heap->items[left].balance, heap->items[best].balance)) {
            best = left;
        }
        if (right < heap->size && heap_better(heap, heap->items[right].balance, heap->items[best].balance)) {
            best = right;
        }
        if (best == idx) {
            break;
        }
        heap_swap(&heap->items[idx], &heap->items[best]);
        idx = best;
    }

    return result;
}

static int find_balance_index(const BalanceNode *balances, int count, int user_id) {
    for (int i = 0; i < count; i++) {
        if (balances[i].user_id == user_id) {
            return i;
        }
    }
    return -1;
}

static int add_balance(BalanceNode **balances, int *count, int *capacity, int user_id, double delta) {
    int idx = find_balance_index(*balances, *count, user_id);
    if (idx >= 0) {
        (*balances)[idx].balance += delta;
        return 1;
    }

    if (*count >= *capacity) {
        int new_capacity = *capacity == 0 ? 16 : *capacity * 2;
        BalanceNode *items = (BalanceNode *)realloc(*balances, (size_t)new_capacity * sizeof(BalanceNode));
        if (items == NULL) {
            return 0;
        }
        *balances = items;
        *capacity = new_capacity;
    }

    (*balances)[*count].user_id = user_id;
    (*balances)[*count].balance = delta;
    (*count)++;
    return 1;
}

static int append_transaction(Transaction **transactions, int *count, int *capacity, Transaction tx) {
    if (*count >= *capacity) {
        int new_capacity = *capacity == 0 ? 8 : *capacity * 2;
        Transaction *items = (Transaction *)realloc(*transactions, (size_t)new_capacity * sizeof(Transaction));
        if (items == NULL) {
            return 0;
        }
        *transactions = items;
        *capacity = new_capacity;
    }

    (*transactions)[*count] = tx;
    (*count)++;
    return 1;
}

EXPORT SettlementResult *settle_debts(const Debt *debts, int debt_count) {
    SettlementResult *result = (SettlementResult *)calloc(1, sizeof(SettlementResult));
    if (result == NULL || debts == NULL || debt_count <= 0) {
        return result;
    }

    BalanceNode *balances = NULL;
    int balance_count = 0;
    int balance_capacity = 0;

    for (int i = 0; i < debt_count; i++) {
        if (debts[i].amount <= EPSILON || debts[i].from_id == debts[i].to_id) {
            continue;
        }

        if (!add_balance(&balances, &balance_count, &balance_capacity, debts[i].from_id, -debts[i].amount) ||
            !add_balance(&balances, &balance_count, &balance_capacity, debts[i].to_id, debts[i].amount)) {
            free(balances);
            return result;
        }
    }

    Heap creditors = {0};
    Heap debtors = {0};
    creditors.is_max_heap = 1;
    debtors.is_max_heap = 0;

    for (int i = 0; i < balance_count; i++) {
        if (balances[i].balance > EPSILON) {
            if (!heap_push(&creditors, balances[i])) {
                goto cleanup;
            }
        } else if (balances[i].balance < -EPSILON) {
            if (!heap_push(&debtors, balances[i])) {
                goto cleanup;
            }
        }
    }

    Transaction *transactions = NULL;
    int transaction_count = 0;
    int transaction_capacity = 0;

    while (creditors.size > 0 && debtors.size > 0) {
        BalanceNode creditor = heap_pop(&creditors);
        BalanceNode debtor = heap_pop(&debtors);
        double payment = fmin(creditor.balance, -debtor.balance);

        if (payment > EPSILON) {
            Transaction tx;
            tx.from_id = debtor.user_id;
            tx.to_id = creditor.user_id;
            tx.amount = payment;

            if (!append_transaction(&transactions, &transaction_count, &transaction_capacity, tx)) {
                free(transactions);
                transactions = NULL;
                transaction_count = 0;
                break;
            }
        }

        creditor.balance -= payment;
        debtor.balance += payment;

        if (creditor.balance > EPSILON) {
            if (!heap_push(&creditors, creditor)) {
                break;
            }
        }
        if (debtor.balance < -EPSILON) {
            if (!heap_push(&debtors, debtor)) {
                break;
            }
        }
    }

    result->count = transaction_count;
    result->transactions = transactions;

cleanup:
    free(balances);
    free(creditors.items);
    free(debtors.items);
    return result;
}

EXPORT void free_results(SettlementResult *result) {
    if (result == NULL) {
        return;
    }
    free(result->transactions);
    free(result);
}
