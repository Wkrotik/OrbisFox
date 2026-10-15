/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "OrbisPath.h"
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <limits.h>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

namespace mozilla::orbisfox {
char* ResolveNativePath(const char* path, char* buffer) {
  if (!path || !*path) {
    errno = path ? ENOENT : EINVAL;
    return nullptr;
  }
  const size_t length = strnlen(path, PATH_MAX);
  if (length >= PATH_MAX) { errno = ENAMETOOLONG; return nullptr; }
  std::string pending(path, length);
  std::string resolved = "/";
  if (pending[0] != '/') {
    char cwd[PATH_MAX];
    if (!getcwd(cwd, sizeof(cwd))) return nullptr;
    resolved = cwd;
  }
  unsigned links = 0;
  while (!pending.empty()) {
    if (pending[0] == '/') {
      // Only absolute input/absolute link targets reset resolved (below).
      const size_t first = pending.find_first_not_of('/');
      if (first == std::string::npos) break;
      pending.erase(0, first);
    }
    const size_t separator = pending.find('/');
    const std::string component = pending.substr(0, separator);
    const bool needsDirectory = separator != std::string::npos;
    const std::string remainder = needsDirectory ? pending.substr(separator) : "";
    pending = remainder;
    if (component == ".") continue;
    if (component == "..") {
      if (resolved != "/") {
        const size_t parent = resolved.rfind('/');
        resolved.resize(parent ? parent : 1);
      }
      continue;
    }
    std::string candidate = resolved == "/" ? "/" + component : resolved + "/" + component;
    if (candidate.size() >= PATH_MAX) { errno = ENAMETOOLONG; return nullptr; }
    struct stat info{};
    if (lstat(candidate.c_str(), &info) != 0) return nullptr;
    if (S_ISLNK(info.st_mode)) {
      if (++links > 40) { errno = ELOOP; return nullptr; }
      char target[PATH_MAX];
      const ssize_t size = readlink(candidate.c_str(), target, sizeof(target));
      if (size < 0) return nullptr;
      if (size == 0) { errno = ENOENT; return nullptr; }
      if (size >= PATH_MAX) { errno = ENAMETOOLONG; return nullptr; }
      if (target[0] == '/') resolved = "/";
      pending.assign(target, static_cast<size_t>(size));
      pending += remainder;
      if (pending.size() >= PATH_MAX) { errno = ENAMETOOLONG; return nullptr; }
      continue;
    }
    if (needsDirectory && !S_ISDIR(info.st_mode)) { errno = ENOTDIR; return nullptr; }
    resolved = std::move(candidate);
  }
  // Covers '/', relative '.'/'..', and trailing separators on those paths.
  struct stat info{};
  if (stat(resolved.c_str(), &info) != 0) return nullptr;
  if (resolved.size() >= PATH_MAX) { errno = ENAMETOOLONG; return nullptr; }
  if (!buffer) {
    buffer = static_cast<char*>(malloc(resolved.size() + 1));
    if (!buffer) { errno = ENOMEM; return nullptr; }
  }
  memcpy(buffer, resolved.c_str(), resolved.size() + 1);
  return buffer;
}
}
