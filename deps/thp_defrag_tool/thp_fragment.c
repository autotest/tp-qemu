// SPDX-License-Identifier: GPL-3.0-or-later
/*
 * Simple program that allocates as many THP as possible, to the split
 * them and free all but a single subpage. This causes heavy fragmentation.
 *
 * Without memory compaction, other processes won't be able top consume
 * THPs.
 *
 * v2:
 *  * Minimize #VMAs so we can allocate a lot more THPs, not running into
 *    #VMA limits.
 *  * Disable KSM on the THP area.
 *
 *  Copyright (C) 2024  Red Hat, Inc.
 *  Author: David Hildenbrand <david@redhat.com>
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <unistd.h>
#include <sys/resource.h>

#ifndef MADV_COLD
#define MADV_COLD	20
#endif

static unsigned long pagesize;
static unsigned long pmd_thpsize;

static uint64_t pagemap_get_entry(int fd, char *start)
{
	const unsigned long pfn = (unsigned long)start / pagesize;
	uint64_t entry;
	int ret;

	ret = pread(fd, &entry, sizeof(entry), pfn * sizeof(entry));
	if (ret != sizeof(entry)) {
		perror("pread");
		exit(-errno);
	}
	return entry;
}

static bool pagemap_is_populated(char *start)
{
	int fd = open("/proc/self/pagemap", O_RDONLY);
	uint64_t entry;

	if (fd < 0) {
		perror("open");
		exit(-errno);
	}
	entry = pagemap_get_entry(fd, start);
	close(fd);

	/* Present or swapped. */
	return entry & 0xc000000000000000ull;
}

static unsigned long detect_thp_size(void)
{
	int fd = open("/sys/kernel/mm/transparent_hugepage/hpage_pmd_size", O_RDONLY);
	unsigned long val;
	char buf[80 + 1];
	int ret;

	if (fd < 0) {
		fprintf(stderr, "Assuming 2 MiB THP\n");
		return 2 * 1024 * 1024u;
	}

	ret = pread(fd, buf, sizeof(buf) - 1, 0);
	if (ret <= 0) {
		fprintf(stderr, "Assuming 2 MiB THP\n");
		val = 2 * 1024 * 1024u;
	} else {
		buf[ret] = 0;
		val = strtoul(buf, NULL, 10);
	}
	close(fd);

	return val;
}

static int try_alloc_thp(char *addr)
{
	char *mmap_area;

	mmap_area = mmap(addr, pmd_thpsize, PROT_READ | PROT_WRITE,
			 MAP_ANONYMOUS | MAP_PRIVATE | MAP_FIXED, -1, 0);
	if (mmap_area != addr)
		return -errno;

	/*
	 * We really want a THP. At this point, we'll merge with any VMA
	 * containing already a THP, reducing the total number of VMAs.
	 *
	 * This has to happen before we actually populate memory, allocating
	 * an anon_vma!
	 */
	if (madvise(addr, pmd_thpsize, MADV_HUGEPAGE)) {
		perror("madvise(MADV_HUGEPAGE)");
		exit(1);
	}

	/*
	 * Disable KSM, just in case. We might still end up swapping out
	 * THPs, but we want to avoid mlock() here.
	 */
	if (madvise(addr, pmd_thpsize, MADV_UNMERGEABLE)) {
		perror("madvise(MADV_UNMERGEABLE)");
		exit(1);
	}


	/* Try populating a THP. */
	*addr = 1;

	/* No THP :( */
	if (!pagemap_is_populated(addr + pmd_thpsize - pagesize))
		return -EAGAIN;
	return 0;
}

int main(void)
{
	/* Start with 32 TiB. */
	const unsigned long long mmap_size = 32 * 1024ull * 1024ull * 1024ull * 1024ul;
	char *mmap_area, *next_thp, *cur;
	int i, retries = 0;

	pagesize = sysconf(_SC_PAGE_SIZE);
	pmd_thpsize = detect_thp_size();

	/*
	 * Reserve a very large memory area. The kernel won't commit any memory
	 * in that region.
	 */
	while (true) {
		mmap_area = mmap(NULL, mmap_size, PROT_NONE,
				 MAP_ANONYMOUS | MAP_PRIVATE, -1, 0);
		if (mmap_area != MAP_FAILED)
			break;
		mmap_size >> 1;
	}

	/* THP-aligned area */
	mmap_area = mmap_area + pmd_thpsize - ((uintptr_t)mmap_area & (pmd_thpsize - 1));

	/* Try allocating as many THP as possible. */
	next_thp = mmap_area;
	while (next_thp < mmap_area + mmap_size - pmd_thpsize) {
		if (try_alloc_thp(next_thp)) {
			if (retries++ > 1000)
				break;
			continue;
		}
		retries = 0;
		next_thp += pmd_thpsize;
	}
	printf("Allocated %d THPs\n", (next_thp - mmap_area) / pmd_thpsize);

	/* Disable khugepagd */
	if (madvise(mmap_area, next_thp - mmap_area, MADV_NOHUGEPAGE)) {
		perror("madvise(MADV_NOHUGEPAGE)");
		exit(1);
	}

	/* After we allocated these THPs, discard all but a single page. */
	for (cur = mmap_area; cur < next_thp; cur += pmd_thpsize) {
		/*
		 * Let's first try splitting the THP. Probably unnecessary,
		 * but this way they don't end up on the deferred split queue.
		 * And can easily be compacted later when need be.
		 */
		if (madvise(cur + pagesize, pmd_thpsize - pagesize,
			    MADV_COLD)) {
			perror("madvise(MADV_COLD)");
			exit(1);
		}

		/* Now, actually free all but a single page. */
		if (madvise(cur + pagesize, pmd_thpsize - pagesize,
			    MADV_DONTNEED)) {
			perror("madvise(MADV_DONTNEED)");
			exit(1);
		}
	}

	return 0;
}
