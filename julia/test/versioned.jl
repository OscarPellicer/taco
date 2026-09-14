function versioned_manifest()
    first_collection = deepcopy(Taco.open_dataset(FIXTURE).collection)
    second_collection = deepcopy(first_collection)
    second_collection["dataset_version"] = "2.0.0"
    return Dict{String,Any}(
        "taco:container" => "versioned",
        "taco:default_version" => "2.0.0",
        "taco:versions" => Dict{String,Any}(
            "1.0.0" => Dict(
                "href" => "1.0.0/",
                "collection" => first_collection,
            ),
            "2.0.0" => Dict(
                "href" => "2.0.0/",
                "collection" => second_collection,
            ),
        ),
    )
end


function write_manifest(root, manifest=versioned_manifest())
    mkpath(root)
    path = joinpath(root, "taco.json")
    write(path, JSON3.write(manifest))
    return path
end


@testset "versioned dataset discovery" begin
    @testset "local root" begin
        mktempdir() do root
            path = write_manifest(root)
            dataset = Taco.open_dataset(root)

            @test dataset.sources == [normpath(joinpath(root, "2.0.0"))]
            @test dataset.collection["dataset_version"] == "2.0.0"
            @test dataset.contract.levels == ["sample", "children"]
            @test dataset.version == "2.0.0"
            @test Set(dataset.versions) == Set(["1.0.0", "2.0.0"])
            @test dataset.manifest == path
        end
    end

    @testset "explicit manifest" begin
        mktempdir() do root
            path = write_manifest(root)
            dataset = Taco.open_dataset(path)
            @test dataset.version == "2.0.0"
            @test dataset.manifest == path
        end
    end

    @testset "read resolves default" begin
        mktempdir() do root
            manifest = versioned_manifest()
            manifest["taco:versions"]["2.0.0"]["href"] = "part.zip"
            write_manifest(root, manifest)
            cp(FIXTURE, joinpath(root, "part.zip"))
            @test size(Taco.read(root; idx=0), 1) == 1
        end
    end

    @testset "direct sources skip discovery" begin
        @test Taco._manifest_candidate("https://example.test/part.zip") === nothing
        @test Taco._manifest_candidate("https://example.test/PART.ZIP") === nothing
        @test Taco._manifest_candidate("https://example.test/.tacocat/") === nothing
        @test Taco._manifest_candidate("https://example.test/data/1.2.3/") === nothing
        @test Taco._manifest_candidate("https://example.test/data.v3/") ==
              "https://example.test/data.v3/taco.json"
    end

    @testset "absolute href" begin
        mktempdir() do root
            manifest = versioned_manifest()
            manifest["taco:versions"]["2.0.0"]["href"] =
                "https://cdn.example/dataset.zip"
            write_manifest(root, manifest)
            @test Taco.open_dataset(root).sources == ["https://cdn.example/dataset.zip"]
        end
    end


    @testset "remote href forms" begin
        candidate = "https://example.test/catalog/releases/taco.json"
        @test Taco._join_manifest_href(candidate, "../2.0.0/") ==
              "https://example.test/catalog/2.0.0/"
        @test Taco._join_manifest_href(candidate, "/stable/data.zip") ==
              "https://example.test/stable/data.zip"
        @test Taco._join_manifest_href(candidate, "//cdn.example/data.zip") ==
              "https://cdn.example/data.zip"
    end

    @testset "invalid manifests" begin
        cases = [
            (value -> (value["taco:container"] = "zip"), "taco:container"),
            (value -> (value["taco:versions"] = Dict()), "at least one"),
            (value -> (value["taco:default_version"] = "3.0.0"), "not present"),
            (
                value -> begin
                    value["taco:versions"]["latest"] = pop!(
                        value["taco:versions"],
                        "1.0.0",
                    )
                end,
                "Semantic Versioning",
            ),
            (
                value -> (value["taco:versions"]["1.0.0"]["href"] = ""),
                "non-empty href",
            ),
            (
                value -> (
                    value["taco:versions"]["2.0.0"]["collection"]["dataset_version"] =
                        "1.0.0"
                ),
                "embeds collection dataset_version",
            ),
            (
                value -> delete!(
                    value["taco:versions"]["2.0.0"]["collection"],
                    "description",
                ),
                "invalid collection",
            ),
        ]
        for (change, message) in cases
            mktempdir() do root
                manifest = versioned_manifest()
                change(manifest)
                path = write_manifest(root, manifest)
                @test_throws message Taco.open_dataset(path)
            end
        end
    end

    @testset "invalid and missing manifest" begin
        mktempdir() do root
            path = joinpath(root, "taco.json")
            write(path, "not JSON")
            @test_throws "not valid JSON" Taco.open_dataset(path)
            rm(path)
            @test_throws "does not exist" Taco.open_dataset(path)
        end
    end
end
