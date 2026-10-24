// SPDX-License-Identifier: MIT
// Bounded runtime/dialog evaluation; no Gecko, graphics, JIT, profile or SDK allocator shim.
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#ifdef ORBISFOX_SDK_PROBE_NATIVE
#include <malloc_np.h>
#else
#include <malloc.h>
#endif

static unsigned constructor_ran;
__attribute__((constructor)) static void before_main(void) { constructor_ran = 0x51d0; }
static _Thread_local volatile unsigned tls_value = 0x1234;
#ifdef ORBISFOX_SDK_PROBE_DIALOG
static const int dialog_mode = 1;
#else
static const int dialog_mode = 0;
#endif
static atomic_int finished;
static int log_fd;
static FILE *output;
static unsigned checks, failures;

#if defined(ORBISFOX_SDK_PROBE_NATIVE) || defined(ORBISFOX_SDK_PROBE_EXIT_TEST)
extern int32_t sceSystemServiceLoadExec(const char *, const char **);
static char exit_log_path[512];

// The SDK explicitly provides this weak main-return hook. This C-only probe has
// already joined every worker and closed its owned resources before returning.
// Do not turn this into a general exit/_exit interposer or a C++ teardown claim.
__attribute__((noreturn)) void catchReturnFromMain(int status) {
  const int flush_error = fflush(NULL);
  if (flush_error && status == 0) status = 1;
  int fd = exit_log_path[0] ? open(exit_log_path, O_WRONLY | O_APPEND | O_NOFOLLOW) : -1;
  char line[128];
  int count = snprintf(line, sizeof(line), "APP_EXIT request status=%d flush=%d\n", status, flush_error);
  if (fd >= 0) {
    if (count > 0 && (size_t)count < sizeof(line)) (void)write(fd, line, (size_t)count);
    (void)fsync(fd);
    (void)close(fd);
  }
  // Normal application-manager termination, not the denied POSIX exit syscall.
  const int32_t rc = sceSystemServiceLoadExec("exit", NULL);
  // Zero may mean an accepted asynchronous request. Allow genuine manager
  // termination instead of turning that successful return into another crash.
  if (rc == 0) {
    struct timespec start, now;
    if (clock_gettime(CLOCK_MONOTONIC, &start) == 0) {
      for (;;) {
        if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) break;
        if (now.tv_sec - start.tv_sec > 5 ||
            (now.tv_sec - start.tv_sec == 5 && now.tv_nsec >= start.tv_nsec)) break;
        const struct timespec delay = {0, 100000000};
        if (nanosleep(&delay, NULL) != 0 && errno != EINTR) break;
      }
    }
  }
  fd = exit_log_path[0] ? open(exit_log_path, O_WRONLY | O_APPEND | O_NOFOLLOW) : -1;
  count = snprintf(line, sizeof(line), "FAIL APP_EXIT did not terminate rc=0x%08x\n", (unsigned)rc);
  if (fd >= 0) {
    if (count > 0 && (size_t)count < sizeof(line)) (void)write(fd, line, (size_t)count);
    (void)fsync(fd);
    (void)close(fd);
  }
  // A failed request or an expired termination deadline is not clean shutdown.
  // Never fall back to the known-denied syscall or silently report success.
  __builtin_trap();
}
#endif

static int check(int ok, const char *name, int result) {
  ++checks;
  if (!ok) ++failures;
  fprintf(output, "%s %s result=%d errno=%d\n", ok ? "PASS" : "FAIL", name, result, errno);
  fflush(output);
  return ok;
}

#ifdef ORBISFOX_SDK_PROBE_DIALOG
#include "homebrew_dialog_probe.h"
#endif

static int same(const unsigned char *p, size_t size, unsigned char value) {
  for (size_t i = 0; i < size; ++i) if (p[i] != value) return 0;
  return 1;
}

static void allocation_checks(void) {
  const size_t sizes[] = {1, 31, 4096, 13112, 65536, 262144};
  int good = 1;
  for (unsigned i = 0; i < sizeof(sizes) / sizeof(*sizes); ++i) {
    size_t n = sizes[i];
    unsigned char *p = malloc(n);
    if (!p) { good = 0; break; }
    size_t capacity = malloc_usable_size(p);
    if (capacity < n) { free(p); good = 0; break; }
    memset(p, 0x5a, capacity);  // Exercise capacity reported to real clients.
    size_t changed = n == 262144 ? 50201 : n + 65536;
    unsigned char *q = realloc(p, changed);
    if (!q) { free(p); good = 0; break; }
    size_t preserved = n < changed ? n : changed;
    if (!same(q, preserved, 0x5a) || malloc_usable_size(q) < changed) good = 0;
    memset(q, 0xc3, changed);
    free(q);
    if (!good) break;
  }
  check(good, "malloc/usable-capacity/realloc-grow-and-shrink", good ? 0 : -1);
  unsigned char *zero = calloc(4096, 4);
  check(zero && same(zero, 16384, 0), "calloc-zero", zero ? 0 : -1);
  free(zero);
  void *aligned = NULL;
  int rc = posix_memalign(&aligned, 16384, 32768);
  check(rc == 0 && aligned && ((uintptr_t)aligned % 16384) == 0, "aligned-allocation", rc);
  if (rc == 0 && aligned) { memset(aligned, 0x6d, 32768); free(aligned); }
}

struct Worker { unsigned id; int ok, destroyed; uintptr_t tls_address; };
static pthread_mutex_t recursive;
static pthread_key_t key;
static pthread_once_t once = PTHREAD_ONCE_INIT;
static unsigned once_calls, counter;
static atomic_uint ready_workers;
static atomic_int start_workers;
static void initialize_once(void) { ++once_calls; }
static void destroy_key(void *p) { ((struct Worker *)p)->destroyed = 1; }

static void *worker(void *opaque) {
  struct Worker *w = opaque;
  w->ok = tls_value == 0x1234;
  w->tls_address = (uintptr_t)&tls_value;
  tls_value = w->id;
  atomic_fetch_add(&ready_workers, 1);
  while (!atomic_load(&start_workers)) { struct timespec tick = {0, 1000000}; nanosleep(&tick, NULL); }
  if (pthread_setspecific(key, w) || pthread_once(&once, initialize_once)) w->ok = 0;
  for (unsigned i = 0; i < 128 && w->ok; ++i) {
    size_t n = 32 + ((i * 197u + w->id) % 65536);
    unsigned char *p = malloc(n);
    if (!p) { w->ok = 0; break; }
    memset(p, (unsigned char)w->id, n);
    if (!same(p, n, (unsigned char)w->id) || tls_value != w->id || pthread_getspecific(key) != w)
      w->ok = 0;
    free(p);
    if (pthread_mutex_lock(&recursive)) { w->ok = 0; break; }
    if (pthread_mutex_lock(&recursive)) { pthread_mutex_unlock(&recursive); w->ok = 0; break; }
    ++counter;
    if (pthread_mutex_unlock(&recursive) || pthread_mutex_unlock(&recursive)) w->ok = 0;
  }
  return NULL;
}

static void thread_checks(void) {
  struct AttrGuard { unsigned char before[32]; pthread_mutexattr_t value; unsigned char after[32]; } attr;
  memset(&attr, 0xa5, sizeof(attr));
  int rc = pthread_mutexattr_init(&attr.value);
  if (!check(rc == 0, "mutex-attribute-init", rc)) return;
  check(same(attr.before, 32, 0xa5) && same(attr.after, 32, 0xa5), "mutex-attribute-ABI-guards", 0);
  rc = pthread_mutexattr_settype(&attr.value, PTHREAD_MUTEX_RECURSIVE);
  if (!check(rc == 0, "recursive-mutex-attribute", rc)) { pthread_mutexattr_destroy(&attr.value); return; }
  rc = pthread_mutex_init(&recursive, &attr.value);
  check(pthread_mutexattr_destroy(&attr.value) == 0, "mutex-attribute-destroy", 0);
  if (!check(rc == 0, "recursive-mutex-init", rc)) return;
  rc = pthread_key_create(&key, destroy_key);
  if (!check(rc == 0, "pthread-key-create", rc)) { pthread_mutex_destroy(&recursive); return; }
  pthread_t threads[4];
  struct Worker workers[4] = {{0}};
  unsigned created = 0;
  for (; created < 4; ++created) {
    workers[created].id = created + 1;
    rc = pthread_create(&threads[created], NULL, worker, &workers[created]);
    if (rc) break;
  }
  check(created == 4, "pthread-create-four-workers", rc);
  while (atomic_load(&ready_workers) != created) { struct timespec tick = {0, 1000000}; nanosleep(&tick, NULL); }
  atomic_store(&start_workers, 1);
  int good = 1;
  for (unsigned i = 0; i < created; ++i) {
    rc = pthread_join(threads[i], NULL);
    if (rc) { check(0, "pthread-join-ownership-uncertain", rc); _exit(125); }
    if (!workers[i].ok || !workers[i].destroyed || workers[i].tls_address == (uintptr_t)&tls_value) good = 0;
    for (unsigned j = 0; j < i; ++j) if (workers[i].tls_address == workers[j].tls_address) good = 0;
  }
  check(good && created == 4 && counter == 512 && once_calls == 1 && tls_value == 0x1234,
        "recursive-lock/once/compiler-TLS/key-destructors/concurrent-heap", 0);
  check(pthread_key_delete(key) == 0, "pthread-key-delete", 0);
  check(pthread_mutex_destroy(&recursive) == 0, "recursive-mutex-destroy", 0);
}

static void condition_checks(void) {
  pthread_mutex_t mutex;
  pthread_cond_t condition;
  int rc = pthread_mutex_init(&mutex, NULL);
  if (!check(rc == 0, "condition-mutex-init", rc)) return;
  rc = pthread_cond_init(&condition, NULL);
  if (!check(rc == 0, "condition-init", rc)) { pthread_mutex_destroy(&mutex); return; }
  struct timespec deadline;
  rc = clock_gettime(CLOCK_REALTIME, &deadline);
  if (check(rc == 0, "condition-realtime-deadline", rc)) {
    deadline.tv_nsec += 2000000;
    if (deadline.tv_nsec >= 1000000000) { ++deadline.tv_sec; deadline.tv_nsec -= 1000000000; }
    rc = pthread_mutex_lock(&mutex);
    if (check(rc == 0, "condition-mutex-lock", rc)) {
      do { rc = pthread_cond_timedwait(&condition, &mutex, &deadline); } while (rc == 0);
      check(rc == ETIMEDOUT, "condition-genuine-timeout", rc);
      check(pthread_mutex_unlock(&mutex) == 0, "condition-mutex-unlock", 0);
    }
  }
  check(pthread_cond_destroy(&condition) == 0, "condition-destroy", 0);
  check(pthread_mutex_destroy(&mutex) == 0, "condition-mutex-destroy", 0);
}

static void clock_checks(void) {
  struct timespec first, last, real, resolution;
  int rc = clock_gettime(CLOCK_MONOTONIC, &first);
  if (!check(rc == 0, "monotonic-clock", rc)) return;
  struct timespec delay = {0, 4000000};
  rc = nanosleep(&delay, NULL);
  check(rc == 0, "nanosleep", rc);
  rc = clock_gettime(CLOCK_MONOTONIC, &last);
  check(rc == 0 && (last.tv_sec > first.tv_sec ||
        (last.tv_sec == first.tv_sec && last.tv_nsec > first.tv_nsec)), "monotonic-advances", rc);
  rc = clock_getres(CLOCK_MONOTONIC, &resolution);
  check(rc == 0 && (resolution.tv_sec > 0 || resolution.tv_nsec > 0), "monotonic-resolution", rc);
  rc = clock_gettime(CLOCK_REALTIME, &real);
  check(rc == 0 && real.tv_sec > 0, "realtime-clock", rc);
  fprintf(output, "clock-id=%d pthread=%zu mutex=%zu attr=%zu wchar=%zu available-cpus=%ld\n",
          CLOCK_MONOTONIC, sizeof(pthread_t), sizeof(pthread_mutex_t), sizeof(pthread_mutexattr_t),
          sizeof(wchar_t), sysconf(_SC_NPROCESSORS_ONLN));
  fflush(output);
}

static void storage_checks(const char *directory) {
  char name[512];
  snprintf(name, sizeof(name), "%s/storage.tmp", directory);
  int fd = open(name, O_CREAT | O_EXCL | O_RDWR | O_NOFOLLOW, 0600);
  if (!check(fd >= 0, "create-owned-storage-file", fd)) return;
  static const char bytes[] = "OrbisFox SDK probe";
  check(write(fd, bytes, sizeof(bytes)) == (ssize_t)sizeof(bytes), "file-write", 0);
  check(fsync(fd) == 0, "file-sync", 0);
  struct StatGuard { unsigned char before[32]; struct stat value; unsigned char after[32]; } st;
  memset(&st, 0xa5, sizeof(st)); memset(&st.value, 0, sizeof(st.value));
  int rc = fstat(fd, &st.value);
  check(rc == 0 && st.value.st_size == (off_t)sizeof(bytes) &&
        same(st.before, 32, 0xa5) && same(st.after, 32, 0xa5), "fstat-size-and-ABI-guards", rc);
  struct flock lock;
  memset(&lock, 0, sizeof(lock)); lock.l_type = F_WRLCK; lock.l_whence = SEEK_SET;
  rc = fcntl(fd, F_SETLK, &lock);
  check(rc == 0, "file-lock-acquire-no-contention-proof", rc);
  if (!rc) { lock.l_type = F_UNLCK; check(fcntl(fd, F_SETLK, &lock) == 0, "file-lock-release", 0); }
  check(lseek(fd, 0, SEEK_SET) == 0, "file-seek", 0);
  char actual[sizeof(bytes)] = {0};
  check(read(fd, actual, sizeof(actual)) == (ssize_t)sizeof(actual) &&
        memcmp(actual, bytes, sizeof(bytes)) == 0, "file-readback", 0);
  check(close(fd) == 0, "storage-close", 0);
  check(unlink(name) == 0, "remove-owned-storage-file", 0);
}

static void shared_checks(void) {
  long page = sysconf(_SC_PAGESIZE);
  if (!check(page > 0 && page <= 65536, "native-page-size", (int)page)) return;
#ifdef ORBISFOX_SDK_PROBE_NATIVE
  int fd = shm_open(SHM_ANON, O_RDWR, 0600);
#else
  char name[80]; snprintf(name, sizeof(name), "/orbisfox-sdk-probe-%ld", (long)getpid());
  int fd = shm_open(name, O_CREAT | O_EXCL | O_RDWR, 0600);
  if (fd >= 0 && shm_unlink(name)) { close(fd); check(0, "unlink-owned-shm-name", -1); return; }
#endif
  if (!check(fd >= 0, "anonymous-shared-memory-create", fd)) return;
  size_t size = (size_t)page * 2;
  int rc = ftruncate(fd, (off_t)size);
  if (!check(rc == 0, "shared-backing-size", rc)) { close(fd); return; }
  unsigned char *p = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (!check(p != MAP_FAILED, "shared-RW-map", p == MAP_FAILED ? -1 : 0)) { close(fd); return; }
  int clone = dup(fd);
  check(clone >= 0, "clone-shared-descriptor", clone);
  unsigned char *q = MAP_FAILED;
  if (clone >= 0) q = mmap(NULL, (size_t)page, PROT_READ, MAP_SHARED, clone, (off_t)page);
  check(q != MAP_FAILED, "shared-readonly-page-offset-map", q == MAP_FAILED ? -1 : 0);
  memset(p, 0x6b, size);
  if (q != MAP_FAILED) check(same(q, (size_t)page, 0x6b), "shared-view-byte-coherence", 0);
  rc = mprotect(p, size, PROT_READ);
  check(rc == 0, "owned-map-RW-to-R", rc);
  if (!rc) check(mprotect(p, size, PROT_READ | PROT_WRITE) == 0, "owned-map-R-to-RW", 0);
  check(close(fd) == 0, "close-original-shared-descriptor", 0);
  if (q != MAP_FAILED) {
    check(same(q, (size_t)page, 0x6b), "shared-view-survives-original-descriptor-close", 0);
    check(munmap(q, (size_t)page) == 0, "unmap-readonly-owned-view", 0);
  }
  check(munmap(p, size) == 0, "unmap-RW-owned-view", 0);
  if (clone >= 0) check(close(clone) == 0, "close-cloned-shared-descriptor", 0);
}

static void *watchdog(void *unused) {
  (void)unused;
  for (unsigned i = 0; i < (dialog_mode ? 120u : 30u); ++i) {
    if (atomic_load(&finished)) return NULL;
    struct timespec delay = {1, 0};
    nanosleep(&delay, NULL);
  }
  static const char message[] = "FAIL watchdog: SDK probe exceeded its deadline\n";
  write(log_fd, message, sizeof(message) - 1);
  _exit(124);  // Never report a hung probe as successful.
}

static int directory(const char *path) {
  if (mkdir(path, 0700) && errno != EEXIST) return 0;
  struct stat st;
  return lstat(path, &st) == 0 && S_ISDIR(st.st_mode) && !S_ISLNK(st.st_mode);
}

int main(int argc, char **argv) {
  (void)argc; (void)argv;
#ifdef ORBISFOX_SDK_PROBE_NATIVE
  if (!directory("/data/orbisfox") || !directory("/data/orbisfox/sdk-probe")) return 1;
  char run[] = "/data/orbisfox/sdk-probe/run-XXXXXX";
#else
  char run[] = "/tmp/orbisfox-sdk-probe-XXXXXX";
  (void)directory;
#endif
  if (!mkdtemp(run)) return 2;
  char path[512]; snprintf(path, sizeof(path), "%s/runtime.log", run);
#if defined(ORBISFOX_SDK_PROBE_NATIVE) || defined(ORBISFOX_SDK_PROBE_EXIT_TEST)
  memcpy(exit_log_path, path, strlen(path) + 1);
#endif
  log_fd = open(path, O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW, 0600);
  if (log_fd < 0) return 3;
  output = fdopen(log_fd, "w");
  if (!output) { close(log_fd); return 4; }
  fprintf(output, "OrbisFox new-SDK %s probe v1; no browser/GPU/JIT\n",
          dialog_mode ? "CommonDialog/IME" : "runtime");
  fflush(output);
  pthread_t timer;
  int rc = pthread_create(&timer, NULL, watchdog, NULL);
  if (!check(rc == 0, "watchdog-thread", rc)) { fclose(output); return 5; }
  check(constructor_ran == 0x51d0, "CRT-constructor-before-main", 0);
  if (dialog_mode) {
    // Volatile access retains the real TLS segment in this smaller probe too.
    check(tls_value == 0x1234, "native-TLS-initial-value", 0);
#ifdef ORBISFOX_SDK_PROBE_DIALOG
    dialog_checks();
#endif
  } else {
    clock_checks();
    allocation_checks();
    thread_checks();
    condition_checks();
    storage_checks(run);
    shared_checks();
  }
  atomic_store(&finished, 1);
  rc = pthread_join(timer, NULL);
  if (rc) { check(0, "watchdog-join-ownership-uncertain", rc); _exit(125); }
  fprintf(output, "RESULT %s checks=%u failures=%u\n", failures ? "FAIL" : "PASS", checks, failures);
  fflush(output);
  int result = failures ? 1 : 0;
  if (fclose(output)) result = 1;
  printf("SDK runtime probe: %s; log=%s\n", result ? "FAIL" : "PASS", path);
  return result;
}
