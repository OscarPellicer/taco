"""Open a TACO dataset and load its collection and contract."""
open_dataset(source) = _open_dataset(source)


"""
    read(source; layout="wide", idx=nothing, level=nothing, files=nothing,
         location=true) -> DataFrame

Read a path, a vector of compatible partitions or an open `Dataset`.
`location` fills file columns in a wide read or includes the calculated
`taco:location` column in a long read. Raw level reads never synthesize one.
"""
function read(source; kwargs...)
    sources = _resolve_dataset(source).sources
    length(sources) > 1 && return read(open_dataset(sources); kwargs...)
    return _read_table(sources; kwargs...)
end


read(dataset::Dataset; kwargs...) = _read_table(dataset.sources; kwargs...)
