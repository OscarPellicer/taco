# taco

Read TACO datasets in R.

```r
remotes::install_github("asterisk-labs/taco", subdir = "r")
```

The source package carries the TACO and Karu sources and compiles them during
installation. It requires a C++23 compiler, pkg-config, libcurl 7.83 or newer,
and OpenSSL 3 or newer.

```r
dataset <- taco::open_dataset("dataset.zip")
samples <- taco::read(dataset)
```
