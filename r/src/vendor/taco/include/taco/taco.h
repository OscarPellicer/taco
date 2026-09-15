// C API for reading TACO datasets.
//
// The core resolves ZIP, FOLDER and TACOCAT containers, local or remote,
// copies their metadata into a cache and writes the SQL that DuckDB runs to
// read them. Python, R and Julia bind this header.
#ifndef TACO_H
#define TACO_H

#include <stddef.h>

#if defined(_WIN32)
#  if defined(TACO_BUILD)
#    define TACO_API __declspec(dllexport)
#  else
#    define TACO_API __declspec(dllimport)
#  endif
#else
#  define TACO_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define TACO_API_VERSION 1

typedef enum {
    TACO_OK = 0,
    TACO_ERR_INVALID = 1,
    TACO_ERR_IO = 2,
    TACO_ERR_NOT_FOUND = 3,
    TACO_ERR_INTERNAL = 99
} taco_status;

TACO_API int taco_api_version(void);
TACO_API const char* taco_version_string(void);

// Error text of the latest failed call on this thread.
TACO_API const char* taco_last_error(void);

// Releases a string returned through a char** parameter.
TACO_API void taco_free(char* text);

typedef struct taco_dataset taco_dataset;

// Opens a dataset. Remote metadata, and the metadata inside any ZIP, is
// copied into cache_dir, or into the default cache when it is NULL.
TACO_API taco_status taco_open(const char* source, const char* cache_dir, taco_dataset** out);
TACO_API void taco_close(taco_dataset* dataset);

// Views owned by the dataset. They stay valid until taco_close.
TACO_API const char* taco_dataset_source(const taco_dataset* dataset);
TACO_API const char* taco_dataset_container(const taco_dataset* dataset);
TACO_API const char* taco_dataset_collection(const taco_dataset* dataset);
TACO_API size_t taco_dataset_level_count(const taco_dataset* dataset);
TACO_API const char* taco_dataset_level(const taco_dataset* dataset, size_t index);
TACO_API size_t taco_dataset_structure_count(const taco_dataset* dataset);
TACO_API const char* taco_dataset_structure(const taco_dataset* dataset, size_t index);
// Serialized taco:derived object, or NULL when the collection has none.
TACO_API const char* taco_dataset_derived(const taco_dataset* dataset);

typedef struct {
    // NULL for every sample, "5" for one, "[0, 100]" for a half-open range.
    const char* idx;
    // NULL for the joined view, otherwise one contract level read raw.
    const char* level;
    // Nonzero for one row per sample, zero for one row per file.
    int pivoted;
    // Structure leaves to read, or NULL for every leaf.
    const char* const* files;
    size_t file_count;
    // Nonzero to calculate file locations.
    int location;
} taco_read_options;

// The query that reads one dataset, or the union of compatible partitions.
TACO_API taco_status taco_sql(const taco_dataset* const* datasets, size_t count,
                              const taco_read_options* options, char** out_sql);

// Profile of a CoZIP archive: "none", "flat", "taco" or "unknown:<n>".
TACO_API taco_status taco_profile(const char* source, char** out_name);

// Where a versioned manifest would be, or NULL when the source is a dataset.
TACO_API taco_status taco_manifest_candidate(const char* source, char** out_candidate);

// A version href resolved against the manifest that lists it.
TACO_API taco_status taco_join_manifest_href(const char* candidate, const char* href,
                                             char** out_source);

// Resolves a versioned root to its default version. The JSON object has
// "source", "collection", "version", "versions" and "manifest"; the last
// four are null or empty when the source is not versioned.
TACO_API taco_status taco_resolve(const char* source, char** out_json);

#ifdef __cplusplus
} // extern "C"
#endif

#endif // TACO_H
