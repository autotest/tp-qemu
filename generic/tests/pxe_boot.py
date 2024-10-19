import aexpect
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    PXE test:

    1) Boot up guest from NIC(from pxe/gpxe server)
    2) Snoop the tftp packet in the tap device
    3) Analyzing the tcpdump result

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    error_context.context("Try to boot from NIC", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("pxe_timeout", 60))

    error_context.context("Snoop packet in the tap device", test.log.info)
    tcpdump_cmd = "tcpdump -nli %s port '(tftp or bootps)'" % vm.get_ifname()
    try:
        tcpdump_process = aexpect.run_bg(
            command=tcpdump_cmd,
            output_func=test.log.debug,
            output_prefix="(pxe capture) ",
        )
        if not tcpdump_process.read_until_output_matches(["tftp"], timeout=timeout):
            test.fail("Couldn't find any TFTP packets after %s seconds" % timeout)
        test.log.info("Found TFTP packet")
    finally:
        try:
            tcpdump_process.kill()
        except:
            pass
