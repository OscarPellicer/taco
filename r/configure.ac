AC_INIT([taco], [0.7.0])
AC_CONFIG_SRCDIR([DESCRIPTION])

AC_PATH_TOOL([PKG_CONFIG], [pkg-config], [no])
AS_IF([test "x$PKG_CONFIG" = xno], [
    AC_MSG_ERROR([pkg-config is required to find libcurl and OpenSSL])
])

AC_MSG_CHECKING([for libcurl >= 7.83.0 and OpenSSL >= 3.0])
AS_IF([$PKG_CONFIG --exists 'libcurl >= 7.83.0' 'openssl >= 3.0'], [
    AC_MSG_RESULT([yes])
], [
    AC_MSG_RESULT([no])
    AC_MSG_ERROR([libcurl >= 7.83.0 and OpenSSL >= 3.0 are required])
])

DEPENDENCY_CPPFLAGS=`$PKG_CONFIG --cflags libcurl openssl`
DEPENDENCY_LIBS=`$PKG_CONFIG --libs libcurl openssl`
NATIVE_OBJECTS=`find src/vendor/taco/src src/vendor/karu/src -type f -name '*.cpp' -print | LC_ALL=C sort | sed -e 's|^src/||' -e 's|\.cpp$|.o|' | tr '\n' ' '`
AC_SUBST([DEPENDENCY_CPPFLAGS])
AC_SUBST([DEPENDENCY_LIBS])
AC_SUBST([NATIVE_OBJECTS])

AC_CONFIG_FILES([src/Makevars])
AC_OUTPUT
