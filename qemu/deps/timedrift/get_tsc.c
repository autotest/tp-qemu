/*
 * Programme to get cpu's TSC(time stamp counter)
 * Copyright(C) 2009 Redhat, Inc.
 * Amos Kong <akong@redhat.com>
 * Dec 9, 2009
 *
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdint.h>

typedef unsigned long long u64;

#if defined(__x86_64__)
u64 rdtsc(void)
{
	unsigned tsc_lo, tsc_hi;

	asm volatile("rdtsc" : "=a"(tsc_lo), "=d"(tsc_hi));
	return tsc_lo | (u64)tsc_hi << 32;
}
#elif defined(__aarch64__)
u64 rdtsc(void)
{
	u64 tsc;

	asm volatile("mrs %0, CNTVCT_EL0" : "=r" (tsc) : : );

	return tsc;
}
#endif

int main(void)
{
	printf("%lld\n", rdtsc());
	return 0;
}
