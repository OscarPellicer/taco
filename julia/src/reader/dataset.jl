struct Contract
    structure::Union{Nothing,Vector{String}}
    metadata::Dict{String,Any}
    derived::Dict{String,Any}
    levels::Vector{String}
end


struct Dataset
    sources::Vector{String}
    collection::Dict{String,Any}
    contract::Contract
    version::String
    versions::Vector{String}
    manifest::Union{Nothing,String}
end


Dataset(sources, collection, contract) = Dataset(
    sources,
    collection,
    contract,
    String(collection["dataset_version"]),
    String[],
    nothing,
)


function _build_contract(collection, levels)
    raw_structure = collection["taco:structure"]
    structure = raw_structure === nothing ? nothing : String.(raw_structure)
    metadata = Dict{String,Any}(collection["taco:metadata"])
    derived = Dict{String,Any}(get(collection, "taco:derived", Dict{String,Any}()))
    return Contract(structure, metadata, derived, levels)
end


function _open_dataset(source)
    resolution = _resolve_dataset(source)
    sources = resolution.sources
    collection = resolution.collection
    levels = String[]
    if collection === nothing
        parsed = _parse_collection.(_collection_documents(sources))
        collection = _merge_collections(first.(parsed), last.(parsed), sources)
        levels = last(first(parsed))
    else
        levels = resolution.levels
    end
    version = something(resolution.version, String(collection["dataset_version"]))
    return Dataset(
        sources,
        collection,
        _build_contract(collection, levels),
        version,
        resolution.versions,
        resolution.manifest,
    )
end


function Base.show(io::IO, dataset::Dataset)
    collection = dataset.collection
    print(io, "Taco.Dataset(")
    show(io, collection["id"])
    print(
        io,
        ", version=",
        collection["dataset_version"],
        ", sources=",
        length(dataset.sources),
        ")",
    )
end
