/* MPL-2.0: native filesystem path resolution for OrbisFox. */
#pragma once
namespace mozilla::orbisfox {
// Uses actual lstat/readlink/getcwd. Does not depend on Linux /proc/fd.
// buffer, when supplied, must have PATH_MAX bytes. A null buffer allocates.
char* ResolveNativePath(const char* path, char* buffer);
}
