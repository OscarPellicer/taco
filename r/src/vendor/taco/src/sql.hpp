#pragma once

// The SQL that reads a TACO dataset. Nothing here touches a file: the query
// is fully determined by the dataset and the options, and DuckDB runs it over
// the local metadata copies with read_parquet.

#include "dataset.hpp"

#include <string>
#include <vector>

namespace taco {

struct ReadOptions {
    // Empty for every sample, "5" for one, "[0, 100]" for a half-open range.
    std::string idx;
    // Empty for the joined view, otherwise one contract level read raw.
    std::string level;
    // One row per sample with a column per structure leaf.
    bool pivot = true;
    std::vector<std::string> files;
    bool has_files = false;
    bool location = true;
};

std::string build_sql(const Dataset& dataset, const ReadOptions& options);

// Partitions of one collection. Every row carries the source_file it came from.
std::string build_union_sql(const std::vector<const Dataset*>& datasets, const ReadOptions& options);

} // namespace taco
