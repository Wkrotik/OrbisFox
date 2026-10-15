// Initial Rust standard-library gate, not JavaScript/Gecko integration.
use std::mem::{align_of, size_of, offset_of};

#[no_mangle]
pub static ORBISFOX_RUST_ABI: [u64; 32] = [size_of::<libc::mode_t>() as u64,
         size_of::<libc::pthread_attr_t>() as u64, align_of::<libc::pthread_attr_t>() as u64,
         size_of::<libc::pthread_mutex_t>() as u64, align_of::<libc::pthread_mutex_t>() as u64,
         size_of::<libc::pthread_cond_t>() as u64, align_of::<libc::pthread_cond_t>() as u64,
         size_of::<libc::pthread_rwlock_t>() as u64, align_of::<libc::pthread_rwlock_t>() as u64,
         size_of::<libc::pthread_mutexattr_t>() as u64, size_of::<libc::pthread_condattr_t>() as u64,
         size_of::<libc::pthread_rwlockattr_t>() as u64, size_of::<libc::pthread_key_t>() as u64,
         size_of::<libc::stat>() as u64, align_of::<libc::stat>() as u64,
         offset_of!(libc::stat, st_mode) as u64, offset_of!(libc::stat, st_uid) as u64,
         offset_of!(libc::stat, st_atime) as u64, offset_of!(libc::stat, st_size) as u64,
         offset_of!(libc::stat, st_birthtime) as u64,
         size_of::<libc::timespec>() as u64, size_of::<libc::sigset_t>() as u64,
         size_of::<libc::sigaction>() as u64, offset_of!(libc::sigaction, sa_mask) as u64,
         size_of::<libc::dirent>() as u64, offset_of!(libc::dirent, d_name) as u64,
         libc::EAGAIN as u64, libc::MAP_ANON as u64, libc::CLOCK_MONOTONIC as u64,
         libc::O_CREAT as u64, libc::O_CLOEXEC as u64, libc::AF_INET6 as u64];

#[no_mangle]
pub unsafe extern "C" fn orbisfox_rust_check_abi(values: *const u64, count: usize) -> u32 {
    if values.is_null() { return u32::MAX; }
    let expected = &ORBISFOX_RUST_ABI;
    if expected.len() != count { return u32::MAX; }
    for (i, (&a, &b)) in std::slice::from_raw_parts(values, count).iter().zip(expected).enumerate() {
        if a != b { return i as u32 + 1; }
    }
    0
}
#[no_mangle]
pub extern "C" fn orbisfox_rust_alloc_probe() -> u32 {
    let mut values = Vec::with_capacity(64);
    for n in 0..64u32 { values.push(n * n); }
    let text = String::from("OrbisFox Rust: ").to_owned() + "\u{1f98a}";
    if values.iter().sum::<u32>() == 85344 && text.chars().count() == 16 { 1 } else { 0 }
}
