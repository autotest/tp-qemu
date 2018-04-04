import logging

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
    error_context.context("Try to boot from NIC", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("pxe_timeout", 60))

    error_context.context("Snoop packet in the tap device", logging.info)
    output = aexpect.run_fg("tcpdump -nli %s" % vm.get_ifname(),
                            logging.debug, "(pxe capture) ", timeout)[1]

    error_context.context("Analyzing the tcpdump result", logging.info)
    if "tftp" not in output:
        test.fail("Couldn't find any TFTP packets after %s seconds" % timeout)
    logging.info("Found TFTP packet")
