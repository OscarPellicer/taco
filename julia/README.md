# Taco.jl

Read TACO datasets in Julia.

```julia
using Pkg
Pkg.add(url="https://github.com/asterisk-labs/taco", subdir="julia")
```

Taco.jl downloads the matching native library from the TACO release on first
use. A development build can be selected explicitly with the `TACO_LIB`
environment variable.

```julia
using Taco

dataset = Taco.open_dataset("dataset.zip")
samples = Taco.read(dataset)
```
