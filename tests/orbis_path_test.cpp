#include "../gecko/orbisfox/OrbisPath.h"
#include <cassert>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <limits.h>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
using mozilla::orbisfox::ResolveNativePath;
static void check(const std::string& path) {
  char expected[PATH_MAX];
  assert(realpath(path.c_str(), expected));
  struct { unsigned char before[32]; char path[PATH_MAX]; unsigned char after[32]; } guarded;
  memset(&guarded, 0xa5, sizeof(guarded));
  assert(ResolveNativePath(path.c_str(), guarded.path) == guarded.path);
  assert(strcmp(expected, guarded.path) == 0);
  for (auto byte : guarded.before) assert(byte == 0xa5);
  for (auto byte : guarded.after) assert(byte == 0xa5);
  char* allocated = ResolveNativePath(path.c_str(), nullptr);
  assert(allocated && strcmp(expected, allocated) == 0);
  free(allocated);
}
static void fails(const std::string& path, int error) {
  char buffer[PATH_MAX]; memset(buffer, 0xa5, sizeof(buffer)); errno = 0;
  assert(!ResolveNativePath(path.c_str(), buffer));
  assert(errno == error);
  for (char byte : buffer) assert(static_cast<unsigned char>(byte) == 0xa5);
}
int main() {
  char cwd[PATH_MAX]; assert(getcwd(cwd, sizeof(cwd)));
  char temporary[] = "/tmp/orbisfox-path-XXXXXX";
  const char* directory = mkdtemp(temporary); assert(directory);
  assert(chdir(directory) == 0);
  assert(mkdir("a", 0700) == 0); assert(mkdir("a/b", 0700) == 0);
  FILE* file = fopen("a/b/file", "wb"); assert(file); fclose(file);
  assert(symlink("a/b", "relative") == 0);
  assert(symlink((std::string(directory)+"/a").c_str(), "absolute") == 0);
  assert(symlink("relative/file", "chain") == 0);
  assert(symlink("loop2", "loop1") == 0); assert(symlink("loop1", "loop2") == 0);
  assert(symlink("absent", "dangling") == 0);
  assert(symlink("/", "root") == 0);
  for (unsigned repetition=0; repetition<32; ++repetition) {
    for (const char* path : {".", "..", "/", "////", "a/b/file", "a//./b/../b/file",
                             "relative/file", "absolute/b/file", "chain", "a/b/", "root/",
                             "relative/..", "a/b/../..", "root/../", "a/./"}) check(path);
    check(std::string(directory)+"/a/b/file");
    fails("a/b/file/", ENOTDIR); fails("a/b/file/../", ENOTDIR);
    fails("chain/.", ENOTDIR); fails("missing/../a", ENOENT);
    fails("dangling", ENOENT); fails("loop1", ELOOP); fails("", ENOENT);
    fails(std::string(PATH_MAX, 'x'), ENAMETOOLONG);
    errno=0; assert(!ResolveNativePath(nullptr, nullptr) && errno==EINVAL);
  }
  assert(unlink("a/b/file") == 0);
  for (const char* path : {"relative", "absolute", "chain", "loop1", "loop2", "dangling", "root"})
    assert(unlink(path) == 0);
  assert(rmdir("a/b") == 0); assert(rmdir("a") == 0);
  assert(chdir(cwd) == 0); assert(rmdir(directory) == 0);
  puts("Native path resolver: 32 real filesystem cycles passed (not firmware certification)");
}
