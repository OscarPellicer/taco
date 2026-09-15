import JSON3


struct DatasetResolution
    sources::Vector{String}
    collection::Union{Nothing,Dict{String,Any}}
    version::Union{Nothing,String}
    versions::Vector{String}
    manifest::Union{Nothing,String}
    levels::Vector{String}
end


DatasetResolution(sources) = DatasetResolution(sources, nothing, nothing, String[], nothing, String[])


function _plain(value::JSON3.Object)
    result = Dict{String,Any}()
    for (key, item) in pairs(value)
        result[String(key)] = _plain(item)
    end
    return result
end


_plain(value::JSON3.Array) = Any[_plain(item) for item in value]
_plain(value) = value


_is_url(source) = occursin(r"^[A-Za-z][A-Za-z0-9+.-]*://", source)
_local_path(path) = _is_url(path) ? path : normpath(path)


_manifest_candidate(source) = _native_manifest_candidate(source)
_join_manifest_href(candidate, href) = _local_path(_native_join_manifest_href(candidate, href))


function _resolve_dataset(source)
    sources = _normalize_sources(source)
    length(sources) == 1 || return DatasetResolution(sources)

    resolution = _native_resolve(only(sources))
    resolution["manifest"] === nothing && return DatasetResolution(sources)
    collection = resolution["collection"]
    return DatasetResolution(
        [_local_path(String(resolution["source"]))],
        _plain(collection),
        String(resolution["version"]),
        String.(resolution["versions"]),
        String(resolution["manifest"]),
        String.(collect(keys(collection["taco:metadata"]))),
    )
end
