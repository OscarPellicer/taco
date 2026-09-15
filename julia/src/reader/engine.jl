using DataFrames: DataFrame
import DBInterface
import DuckDB


const _DATABASE = Ref{Union{Nothing,DuckDB.DB}}(nothing)
const _CONNECTION = Ref{Union{Nothing,DuckDB.Connection}}(nothing)
const _LOCK = ReentrantLock()


function _open_reader()
    con = _CONNECTION[]
    con === nothing || return con
    db = DuckDB.DB()
    _DATABASE[] = db
    _CONNECTION[] = DBInterface.connect(db)
    return _CONNECTION[]
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


function _with_reader(body)
    return lock(_LOCK) do
        body(_open_reader())
    end
end


function _dataframe(con, sql)
    return DataFrame(DBInterface.execute(con, sql))
end
