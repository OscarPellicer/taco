using DataFrames: DataFrame, rename!, select!


function _check_idx(idx)
    idx === nothing && return nothing
    values = idx isa Tuple || idx isa AbstractVector ? collect(idx) : Any[idx]
    length(values) in (1, 2) ||
        throw(ArgumentError("taco: `idx` must be one sample number or a two-element range"))
    all(
        value -> value isa Integer && !(value isa Bool) &&
                 value >= 0 && value <= typemax(Int64),
        values,
    ) || throw(ArgumentError("taco: `idx` must contain whole, non-negative numbers"))
    length(values) == 2 && values[1] > values[2] &&
        throw(ArgumentError("taco: `idx` range start must not exceed its end"))
    return nothing
end


function _idx_text(idx)
    idx === nothing && return nothing
    values = idx isa Integer ? Any[idx] : collect(idx)
    length(values) == 1 && return string(only(values))
    return "[$(values[1]), $(values[2])]"
end


const _LOCATION_COLUMN = "taco:location"
const _LEGACY_LOCATION_COLUMN = "cozip:gdal_vsi"


function _read_call(location_argument)
    return string(
        "read_taco(?, idx := ?::VARCHAR, level := ?::VARCHAR, ",
        "pivoted := ?::BOOLEAN, files := ?::VARCHAR[], ",
        location_argument,
        " := ?::BOOLEAN)",
    )
end


function _legacy_taco_signature(message)
    return occursin("read_taco", message) &&
           occursin("gdal_vsi", message) &&
           occursin("does not support the supplied arguments", message)
end


function _normalize_locations!(result, location, level, layout, legacy)
    preserve_current = !legacy && location && level === nothing && layout == "long"
    drop = intersect(["cozip:location"], names(result))
    if !preserve_current && _LOCATION_COLUMN in names(result)
        push!(drop, _LOCATION_COLUMN)
    end
    preserve_legacy = legacy && location && level === nothing && layout == "long"
    if !preserve_legacy && _LEGACY_LOCATION_COLUMN in names(result)
        push!(drop, _LEGACY_LOCATION_COLUMN)
    end
    isempty(drop) || select!(result, setdiff(names(result), drop))
    if preserve_legacy && _LEGACY_LOCATION_COLUMN in names(result)
        rename!(result, Symbol(_LEGACY_LOCATION_COLUMN) => Symbol(_LOCATION_COLUMN))
    end
    return result
end


function _read_table(
    sources;
    layout::AbstractString = "wide",
    idx = nothing,
    level::Union{Nothing,AbstractString} = nothing,
    files::Union{Nothing,AbstractVector{<:AbstractString}} = nothing,
    location::Bool = true,
)::DataFrame
    layout in ("wide", "long") ||
        throw(ArgumentError("taco: `layout` must be \"wide\" or \"long\""))
    _check_idx(idx)
    level === nothing || !isempty(level) ||
        throw(ArgumentError("taco: `level` must be non-empty"))
    if files !== nothing && (isempty(files) || any(isempty, files))
        throw(ArgumentError("taco: `files` entries must be non-empty"))
    end

    options = Any[
        _idx_text(idx),
        level === nothing ? nothing : String(level),
        layout == "wide",
        files === nothing ? nothing : String.(files),
        location,
    ]

    return _with_reader() do con
        function query(location_argument)
            call = _read_call(location_argument)
            if length(sources) == 1
                sql = "SELECT * FROM $call"
                return sql, Any[only(sources), options...]
            end

            projection = if level === nothing
                "taco.sample_id, ?::VARCHAR AS source_file, taco.* EXCLUDE (sample_id)"
            else
                "?::VARCHAR AS source_file, taco.*"
            end
            branch = "SELECT $projection FROM $call AS taco"
            sql = join(fill(branch, length(sources)), " UNION ALL BY NAME ")
            params = Any[]
            for (label, path) in zip(_source_labels(sources), sources)
                append!(params, Any[label, path, options...])
            end
            return sql, params
        end

        sql, params = query("location")
        legacy = false
        result = try
            _dataframe(con, sql, params)
        catch err
            _legacy_taco_signature(sprint(showerror, err)) || rethrow()
            legacy = true
            legacy_sql, legacy_params = query("gdal_vsi")
            _dataframe(con, legacy_sql, legacy_params)
        end
        return _normalize_locations!(result, location, level, layout, legacy)
    end
end
