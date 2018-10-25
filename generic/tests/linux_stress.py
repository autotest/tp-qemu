import time
import logging

from avocado.core import exceptions

from virttest import utils_test


def run(test, params, env):
    """
    General stress test for linux:
       1). Install stress if need
       2). Start stress process
       3). If no stress_duration defined, keep stress until test_timeout;
       otherwise execute below steps after sleeping stress_duration long
       4). Stop stress process
       5). Uninstall stress
       6). Verify guest kernel crash

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    stress_duration = int(params.get("stress_duration", "0"))
    # NOTE: stress_duration = 0 ONLY for some legacy test cases using
    # autotest stress.control as their sub test.
    # Please DO define stress_duration to make sure the clean action
    # being performed, if your case can not be controlled by time,
    # use utils_test.VMStress() directly
    stress_type = params.get("stress_type", "stress")
    vms = env.get_all_vms()
    up_time = {}
    error = False
    stress_server = {}

    for vm in vms:
        try:
            up_time[vm.name] = vm.uptime()
            stress_server[vm.name] = utils_test.VMStress(vm, stress_type, params)
            stress_server[vm.name].load_stress_tool()
        except exceptions.TestError as err_msg:
            error = True
            logging.error(err_msg)

    if stress_duration:
        time.sleep(stress_duration)
        for vm in vms:
            try:
                s_ping, o_ping = utils_test.ping(vm.get_address(), count=5, timeout=20)
                if s_ping != 0:
                    error = True
                    logging.error("%s seem to have gone out of network", vm.name)
                    continue
                uptime = vm.uptime()
                if up_time[vm.name] > uptime:
                    error = True
                    logging.error("%s seem to have rebooted during the stress run", vm.name)
                stress_server[vm.name].unload_stress()
                stress_server[vm.name].clean()
                vm.verify_dmesg()
            except exceptions.TestError as err_msg:
                error = True
                logging.error(err_msg)

    if error:
        test.fail("Run failed: see error messages above")
