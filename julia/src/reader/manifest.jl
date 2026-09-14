import Downloads
import JSON3


const _SEMVER = r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"


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


function _source_name(source)
    clean = first(split(source, r"[?#]"; limit=2))
    return basename(rstrip(clean, '/'))
end


function _direct_source(source)
    name = _source_name(source)
    return name == ".tacocat" || endswith(lowercase(name), ".zip") || occursin(_SEMVER, name)
end


_is_url(source) = occursin(r"^[A-Za-z][A-Za-z0-9+.-]*://", source)


function _manifest_candidate(source)
    _source_name(source) == "taco.json" && return source
    _direct_source(source) && return nothing
    if _is_url(source)
        clean = first(split(source, r"[?#]"; limit=2))
        return rstrip(clean, '/') * "/taco.json"
    end
    candidate = joinpath(source, "taco.json")
    return isfile(candidate) ? candidate : nothing
end


function _read_manifest(candidate, required)
    if !_is_url(candidate)
        if !isfile(candidate)
            required || return nothing
            error("taco: versioned manifest does not exist: $candidate")
        end
        try
            return Base.read(candidate)
        catch err
            error("taco: could not read versioned manifest $candidate: $(sprint(showerror, err))")
        end
    end

    output = IOBuffer()
    response = try
        Downloads.request(candidate; output=output, throw=false)
    catch err
        error("taco: could not read versioned manifest $candidate: $(sprint(showerror, err))")
    end
    response.status == 404 && !required && return nothing
    200 <= response.status < 300 ||
        error("taco: could not read versioned manifest $candidate: HTTP $(response.status)")
    return take!(output)
end


function _manifest_object(value, context)
    value isa AbstractDict || error("taco: $context must be an object")
    return Dict{String,Any}(String(key) => item for (key, item) in pairs(value))
end


function _parse_manifest(payload, candidate)
    value = try
        JSON3.read(String(payload))
    catch
        error("taco: versioned manifest is not valid JSON: $candidate")
    end
    manifest = _manifest_object(value, "versioned manifest")
    get(manifest, "taco:container", nothing) == "versioned" ||
        error("taco: taco:container must be 'versioned'")
    return manifest
end


function _normalize_url_path(path)
    trailing = endswith(path, '/')
    segments = String[]
    for segment in split(path, '/')
        (isempty(segment) || segment == ".") && continue
        if segment == ".."
            isempty(segments) || pop!(segments)
        else
            push!(segments, segment)
        end
    end
    result = "/" * join(segments, "/")
    trailing && result != "/" && (result *= "/")
    return result
end


function _join_manifest_href(candidate, href)
    _is_url(href) && return href
    if !_is_url(candidate)
        joined = isabspath(href) ? href : joinpath(dirname(candidate), href)
        return normpath(rstrip(joined, ['/', '\\']))
    end

    clean = first(split(candidate, r"[?#]"; limit=2))
    if startswith(href, "//")
        scheme = first(split(clean, ':'; limit=2))
        return "$scheme:$href"
    end
    matched = match(r"^([A-Za-z][A-Za-z0-9+.-]*://[^/]+)(/.*)?$", clean)
    matched === nothing && error("taco: invalid manifest URL: $candidate")
    origin = matched.captures[1]
    candidate_path = something(matched.captures[2], "/")
    target = startswith(href, '/') ? href : replace(candidate_path, r"[^/]*$" => "") * href
    return origin * _normalize_url_path(target)
end


function _validate_embedded_collection(collection, version)
    required = [
        "taco:version",
        "id",
        "dataset_version",
        "description",
        "licenses",
        "providers",
        "tasks",
        "taco:structure",
        "taco:metadata",
    ]
    missing = filter(key -> !haskey(collection, key), required)
    isempty(missing) || error(
        "taco: version '$version' embeds an invalid collection: " *
        "missing required fields $(join(missing, ", "))",
    )
    collection["taco:version"] == "3.0.0" || error(
        "taco: version '$version' embeds an invalid collection: " *
        "taco:version must be 3.0.0",
    )
    collection["taco:metadata"] isa AbstractDict || error(
        "taco: version '$version' embeds an invalid collection: " *
        "taco:metadata must be an object",
    )
    return nothing
end


function _resolve_dataset(source)
    sources = _normalize_sources(source)
    length(sources) == 1 || return DatasetResolution(sources)

    original = only(sources)
    explicit = _source_name(original) == "taco.json"
    candidate = _manifest_candidate(original)
    candidate === nothing && return DatasetResolution(sources)
    payload = _read_manifest(candidate, explicit)
    payload === nothing && return DatasetResolution(sources)

    manifest = _parse_manifest(payload, candidate)
    raw_versions = get(manifest, "taco:versions", nothing)
    version_names = raw_versions isa AbstractDict ? String.(collect(keys(raw_versions))) : String[]
    versions = _manifest_object(raw_versions, "taco:versions")
    isempty(versions) && error("taco: taco:versions must contain at least one version")

    selected = get(manifest, "taco:default_version", nothing)
    selected isa AbstractString && !isempty(selected) ||
        error("taco: taco:default_version must be a non-empty string")
    selected = String(selected)
    haskey(versions, selected) || error(
        "taco: taco:default_version '$selected' is not present in taco:versions",
    )

    entries = Dict{String,Tuple{String,Dict{String,Any},Vector{String}}}()
    for (raw_version, value) in versions
        version = String(raw_version)
        occursin(_SEMVER, version) ||
            error("taco: taco:versions key '$version' must follow Semantic Versioning")
        entry = _manifest_object(value, "version '$version'")
        href = get(entry, "href", nothing)
        href isa AbstractString && !isempty(href) ||
            error("taco: version '$version' needs a non-empty href")
        raw_collection = _manifest_object(
            get(entry, "collection", nothing),
            "version '$version' collection",
        )
        raw_metadata = get(raw_collection, "taco:metadata", nothing)
        levels = raw_metadata isa AbstractDict ? String.(collect(keys(raw_metadata))) : String[]
        collection = Dict{String,Any}(
            key => _plain(item) for (key, item) in raw_collection
        )
        embedded_version = get(collection, "dataset_version", nothing)
        embedded_version == version || error(
            "taco: version '$version' embeds collection dataset_version " * repr(embedded_version),
        )
        entries[version] = (String(href), collection, levels)
    end

    href, collection, levels = entries[selected]
    _validate_embedded_collection(collection, selected)
    return DatasetResolution(
        [_join_manifest_href(candidate, href)],
        collection,
        selected,
        version_names,
        candidate,
        levels,
    )
end
