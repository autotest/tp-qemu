import time

from virttest import utils_test


def run(test, params, env):
    """
    General stress test for linux:
       1). Install stress if need
       2). Start stress process
       3). If no stress_time defined, keep stress until test_timeout;
       otherwise execute below steps after sleeping stress_time long
       4). Stop stress process
       5). Uninstall stress
       6). Verify guest kernel crash

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params['main_vm'])
    vm.verify_alive()
    stress = utils_test.VMStress(vm, 'stress', params)
    stress.load_stress_tool()
    stress_duration = int(params.get('stress_duration', 0))
    # NOTE: stress_duration = 0 ONLY for some legacy test cases using
    # autotest stress.control as their sub test.
    # Please DO define stress_duration to make sure the clean action
    # being performed, if your case can not be controlled by time,
    # use utils_test.VMStress() directly

    if stress_duration:
        time.sleep(stress_duration)
        stress.unload_stress()
        stress.clean()
        vm.verify_kernel_crash()
