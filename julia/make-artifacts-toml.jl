using Downloads
using Pkg.Artifacts
using SHA

const REPOSITORY = "asterisk-labs/taco"
const VERSION = only(ARGS)
const PLATFORMS = [
    (
        properties = ["arch = \"aarch64\"", "os = \"linux\"", "libc = \"glibc\""],
        asset = "libtaco-$VERSION-linux-aarch64.tar.gz",
    ),
    (
        properties = ["arch = \"x86_64\"", "os = \"linux\"", "libc = \"glibc\""],
        asset = "libtaco-$VERSION-linux-x86_64.tar.gz",
    ),
    (
        properties = ["arch = \"aarch64\"", "os = \"macos\""],
        asset = "libtaco-$VERSION-macos-aarch64.tar.gz",
    ),
    (
        properties = ["arch = \"x86_64\"", "os = \"macos\""],
        asset = "libtaco-$VERSION-macos-x86_64.tar.gz",
    ),
    (
        properties = ["arch = \"x86_64\"", "os = \"windows\""],
        asset = "libtaco-$VERSION-windows-x86_64.tar.gz",
    ),
]


function hashes(asset)
    url = "https://github.com/$REPOSITORY/releases/download/v$VERSION/$asset"
    archive = Downloads.download(url)
    sha256 = bytes2hex(open(SHA.sha256, archive))
    tree = create_artifact() do directory
        run(`tar -xzf $archive -C $directory`)
    end
    return (; url, sha256, tree)
end


for platform in PLATFORMS
    info = hashes(platform.asset)
    println("[[taco]]")
    foreach(println, platform.properties)
    println("git-tree-sha1 = \"$(info.tree)\"")
    println("lazy = true\n")
    println("    [[taco.download]]")
    println("    url = \"$(info.url)\"")
    println("    sha256 = \"$(info.sha256)\"\n")
end
