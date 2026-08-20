#include <stdint.h>

static volatile uint8_t arena[256] __attribute__((aligned(64)));

static int
check_u8(uint32_t off, uint8_t expected, int code)
{
    return arena[off] == expected ? 0 : code;
}

static int
check_u16(uint32_t off, uint16_t expected, int code)
{
    volatile uint16_t *p = (volatile uint16_t *)(uintptr_t)&arena[off];
    return *p == expected ? 0 : code;
}

static int
check_u32(uint32_t off, uint32_t expected, int code)
{
    volatile uint32_t *p = (volatile uint32_t *)(uintptr_t)&arena[off];
    return *p == expected ? 0 : code;
}

static int
check_u64(uint32_t off, uint64_t expected, int code)
{
    volatile uint64_t *p = (volatile uint64_t *)(uintptr_t)&arena[off];
    return *p == expected ? 0 : code;
}

static int
run_test(void)
{
    volatile uint8_t stack_bytes[80] __attribute__((aligned(64)));
    int rc;

    arena[0] = 0x11;
    arena[1] = 0x22;
    arena[63] = 0x33;
    arena[64] = 0x44;
    arena[65] = 0x55;
    arena[127] = 0x66;

    *(volatile uint16_t *)(uintptr_t)&arena[2] = 0x7788U;
    *(volatile uint16_t *)(uintptr_t)&arena[62] = 0x99aaU;
    *(volatile uint32_t *)(uintptr_t)&arena[4] = 0xbbccddeeU;
    *(volatile uint32_t *)(uintptr_t)&arena[128] = 0x10203040U;
    *(volatile uint64_t *)(uintptr_t)&arena[8] = 0x1122334455667788ULL;
    *(volatile uint64_t *)(uintptr_t)&arena[192] = 0x8877665544332211ULL;

    stack_bytes[0] = 0x5a;
    stack_bytes[63] = 0xc3;
    *(volatile uint32_t *)(uintptr_t)&stack_bytes[64] = 0xdecafbadU;

    if ((rc = check_u8(0, 0x11, 1)) != 0) return rc;
    if ((rc = check_u8(1, 0x22, 2)) != 0) return rc;
    if ((rc = check_u16(2, 0x7788U, 3)) != 0) return rc;
    if ((rc = check_u32(4, 0xbbccddeeU, 4)) != 0) return rc;
    if ((rc = check_u64(8, 0x1122334455667788ULL, 5)) != 0) return rc;
    if ((rc = check_u16(62, 0x99aaU, 6)) != 0) return rc;
    if ((rc = check_u8(64, 0x44, 7)) != 0) return rc;
    if ((rc = check_u8(65, 0x55, 8)) != 0) return rc;
    if ((rc = check_u8(127, 0x66, 9)) != 0) return rc;
    if ((rc = check_u32(128, 0x10203040U, 10)) != 0) return rc;
    if ((rc = check_u64(192, 0x8877665544332211ULL, 11)) != 0) return rc;

    if (stack_bytes[0] != 0x5a) return 12;
    if (stack_bytes[63] != 0xc3) return 13;
    if (*(volatile uint32_t *)(uintptr_t)&stack_bytes[64] != 0xdecafbadU) return 14;

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
