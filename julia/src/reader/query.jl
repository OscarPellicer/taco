using DataFrames: DataFrame


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

    datasets = [_open_native(source) for source in sources]
    sql = _native_sql(
        datasets;
        idx=_idx_text(idx),
        level=level,
        pivoted=layout == "wide",
        files=files,
        location=location,
    )
    return _with_reader() do con
        _dataframe(con, sql)
    end
end
