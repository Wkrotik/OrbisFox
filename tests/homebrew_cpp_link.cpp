// SPDX-License-Identifier: MIT
// Native link fixture, NOT a console-executed test or application entrypoint.
#include <atomic>
#include <condition_variable>
#include <filesystem>
#include <list>
#include <locale>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

static_assert(sizeof(wchar_t) == 2);
static_assert(sizeof(pthread_mutex_t) == 8);
static_assert(sizeof(pthread_cond_t) == 8);
static_assert(sizeof(pthread_once_t) == 16);

static int& initialized() {
  static int value = [] { return 7; }();
  return value;
}

int main() {
  thread_local std::wstring threadName = L"native";
  std::vector<std::wstring> values(2, threadName);
  std::list<void*> nodes;
  nodes.push_back(&values);
  std::mutex mutex;
  std::condition_variable condition;
  std::atomic<int> done{0};
  std::thread worker([&] {
    std::lock_guard lock(mutex);
    done.store(initialized());
    done.notify_all();
    condition.notify_one();
  });
  {
    std::unique_lock lock(mutex);
    condition.wait_for(lock, std::chrono::milliseconds(10), [&] { return done.load() != 0; });
  }
  worker.join();
  done.wait(0);
  auto path = (std::filesystem::path(L"/data") / L"probe").wstring();
  std::wstringstream text;
  text.imbue(std::locale::classic());
  text << path << done.load();
  try {
    throw std::runtime_error("native exception");
  } catch (const std::exception& error) {
    return values.empty() || text.str().empty() || !error.what();
  }
}
