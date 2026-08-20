#include <stdint.h>

#define WORD_COUNT 1024U
#define WORD_STRIDE 16U

static volatile uint32_t arena[WORD_COUNT] __attribute__((aligned(64)));
static volatile uint32_t scratch_sink;

static int
build_pattern(void)
{
    for (uint32_t i = 0; i < WORD_COUNT; ++i) {
        arena[i] = (i * 0x9e3779b9U) ^ 0xa5a5a5a5U;
    }

    for (uint32_t i = 0; i < WORD_COUNT; ++i) {
        uint32_t next = (i + WORD_STRIDE) & (WORD_COUNT - 1U);
        arena[i] = next;
    }

    return 0;
}

static int
verify_pattern(void)
{
    for (uint32_t i = 0; i < WORD_COUNT; ++i) {
        uint32_t expected = (i + WORD_STRIDE) & (WORD_COUNT - 1U);
        if (arena[i] != expected) {
            return 1;
        }
    }

    return 0;
}

static int
run_pointer_walk(void)
{
    uint32_t idx = 0;
    uint32_t checksum = 0;

    for (uint32_t i = 0; i < WORD_COUNT; ++i) {
        idx = arena[idx];
        checksum ^= idx + (i << 1);
    }

    scratch_sink = checksum;
    return idx == 0 ? 0 : 2;
}

static int
run_stride_mix(void)
{
    uint32_t checksum = 0;

    for (uint32_t pass = 0; pass < 2; ++pass) {
        for (uint32_t i = pass; i < WORD_COUNT; i += 32U) {
            checksum ^= arena[i];
            arena[i] = arena[i] ^ (0x01010101U * pass);
        }
    }

    scratch_sink ^= checksum;
    return 0;
}

static int
run_test(void)
{
    int rc = build_pattern();
    if (rc != 0) {
        return 10;
    }

    rc = verify_pattern();
    if (rc != 0) {
        return 11;
    }

    rc = run_pointer_walk();
    if (rc != 0) {
        return 12;
    }

    rc = run_stride_mix();
    if (rc != 0) {
        return 13;
    }

    return 0;
}

void
_start(void)
{
    long code = run_test();
    __asm__ volatile (
        "mov $60, %%rax\n"
        "mov %0, %%rdi\n"
        "syscall\n"
        :
        : "r"(code)
        : "rax", "rdi", "rcx", "r11", "memory");
    __builtin_unreachable();
}
