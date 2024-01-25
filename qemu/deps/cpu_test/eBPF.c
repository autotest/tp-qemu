#if defined(CONFIG_FUNCTION_TRACER)
#define CC_USING_FENTRY
#endif

#include <linux/kvm_host.h>

kprobe:direct_page_fault 
{
	$ctr = ((struct kvm_vcpu*)arg0)->kvm->mmu_notifier_seq;
	@counts[pid] = $ctr;
}

interval:s:2 
{
	print(@counts);
	print("---\n");
}
