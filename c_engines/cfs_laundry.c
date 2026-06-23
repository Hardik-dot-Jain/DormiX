#include <float.h>
#include <stddef.h>
#include <stdlib.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

typedef struct {
    int user_id;
    double vruntime;
    double weight;
} LaundryJob;

typedef struct {
    int winning_index;
    int user_id;
    double score;
    double projected_vruntime;
} LaundryResult;

EXPORT LaundryResult *schedule_laundry(const LaundryJob *jobs, int job_count, double runtime_increment) {
    LaundryResult *result = (LaundryResult *)calloc(1, sizeof(LaundryResult));
    if (result == NULL) {
        return NULL;
    }

    result->winning_index = -1;
    result->user_id = -1;
    result->score = DBL_MAX;
    result->projected_vruntime = 0.0;

    if (jobs == NULL || job_count <= 0) {
        return result;
    }

    for (int i = 0; i < job_count; i++) {
        if (jobs[i].weight <= 0.0) {
            continue;
        }

        double score = jobs[i].vruntime / jobs[i].weight;
        if (score < result->score) {
            result->winning_index = i;
            result->user_id = jobs[i].user_id;
            result->score = score;
            result->projected_vruntime = jobs[i].vruntime + (runtime_increment / jobs[i].weight);
        }
    }

    return result;
}

EXPORT void free_results(LaundryResult *result) {
    free(result);
}
