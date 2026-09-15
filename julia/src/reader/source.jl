function _check_path(source)
    source isa AbstractString ||
        throw(ArgumentError("taco: source paths must be strings"))
    path = String(source)
    isempty(path) && throw(ArgumentError("taco: source paths must be non-empty"))
    occursin('\0', path) && throw(ArgumentError("taco: a source path contains a NUL byte"))
    return path
end


_normalize_sources(source::AbstractString) = [_check_path(source)]


function _normalize_sources(source::AbstractVector)
    isempty(source) &&
        throw(ArgumentError("taco: `source` must contain one or more paths"))
    paths = [_check_path(path) for path in source]
    length(unique(paths)) == length(paths) ||
        throw(ArgumentError("taco: source paths must be unique"))
    return paths
end


_normalize_sources(source) =
    throw(ArgumentError("taco: `source` must be a path or a vector of paths"))
