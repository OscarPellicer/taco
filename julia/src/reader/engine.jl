using DataFrames: DataFrame
import DBInterface
import DuckDB


const _DATABASE = Ref{Union{Nothing,DuckDB.DB}}(nothing)
const _CONNECTION = Ref{Union{Nothing,DuckDB.Connection}}(nothing)
const _LOCK = ReentrantLock()


function _has_reader(con)
    query = DBInterface.execute(
        con,
        "SELECT count(*) AS n FROM duckdb_functions() WHERE function_name = 'read_taco'",
    )
    return first(first(collect(query))) > 0
end


function _require_reader(con)
    _has_reader(con) || error(
        "taco: the loaded cozip extension has no TACO reader. " *
        "Upgrade DuckDB or point COZIP_EXTENSION at a local build",
    )
    return nothing
end


function _open_reader()
    con = _CONNECTION[]
    con === nothing || return con

    local_extension = get(ENV, "COZIP_EXTENSION", "")
    db = if isempty(local_extension)
        DuckDB.DB()
    else
        DuckDB.DB(config=Dict("allow_unsigned_extensions" => "true"))
    end
    con = DBInterface.connect(db)
    try
        DBInterface.execute(con, "INSTALL httpfs")
        DBInterface.execute(con, "LOAD httpfs")
        if isempty(local_extension)
            DBInterface.execute(con, "INSTALL cozip FROM community")
            DBInterface.execute(con, "LOAD cozip")
        else
            path = replace(local_extension, "'" => "''")
            DBInterface.execute(con, "LOAD '$path'")
        end
        _require_reader(con)
    catch
        DBInterface.close!(con)
        DBInterface.close!(db)
        rethrow()
    end

    _DATABASE[] = db
    _CONNECTION[] = con
    return con
end


function _close_reader!()
    lock(_LOCK) do
        con = _CONNECTION[]
        db = _DATABASE[]
        _CONNECTION[] = nothing
        _DATABASE[] = nothing
        con === nothing || DBInterface.close!(con)
        db === nothing || DBInterface.close!(db)
    end
    return nothing
end


function __init__()
    _DATABASE[] = nothing
    _CONNECTION[] = nothing
    atexit(_close_reader!)
end


function _check_platform()
    Sys.iswindows() && error(
        "taco: reading is not supported on Windows because DuckDB.jl " *
        "cannot load the cozip filesystem extension there",
    )
    return nothing
end


function _with_reader(body)
    _check_platform()
    return lock(_LOCK) do
        body(_open_reader())
    end
end


function _dataframe(con, sql, params)
    return DataFrame(DBInterface.execute(con, sql, params))
end
