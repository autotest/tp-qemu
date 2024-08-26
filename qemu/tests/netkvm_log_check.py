import re
import logging

from virttest import error_context
from virttest import utils_net

LOG_JOB = logging.getLogger('avocado.test')


@error_context.context_aware
def run(test, params, env):
    """
    Netkvm log checking using traceview:

    1) Start the VM.
    2) Configure and verify the advanced parameters of the NIC.
    3) Use TraceView.exe to apply filters and capture relevant keywords.
    4) Restart the NIC.
    5) Monitor the output in TraceView.exe and extract the captured keywords.
    6) Restore the default parameter value

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_keyword_from_traceview(keyword):
        """
        Get the keyword by `TraceView.exe`

        Return the keywords which means that we found it.
        """

        device_mac = vm.virtnet[0].mac
        error_context.context(
            f"Check {keyword} from the traceview", test.log.info)
        output = utils_net.dump_traceview_log_windows(params, vm)
        utils_net.restart_guest_network(session, device_mac, params["os_type"])
        mapping_output = re.findall(keyword, output)
        if mapping_output == []:
            test.fail(f"Can't get {keyword} from traceview")
        return mapping_output

    timeout = params.get_numeric("login_timeout", 240)
    vm_name = params['main_vm']
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    session = vm.wait_for_serial_login(timeout=timeout)
    netkvmco_name = params.get("netkvmco_name")
    netkvmco_value = params.get("netkvmco_value")
    expected_log_msg = params.get("expected_log_msg")
    default_value = utils_net.get_netkvm_param_value(vm, netkvmco_name)
    # Set the new parameter value
    utils_net.set_netkvm_param_value(vm, netkvmco_name, netkvmco_value)
    cur_value = utils_net.get_netkvm_param_value(vm, netkvmco_name)
    if cur_value != netkvmco_value:
        test.fail(f"Current value '{cur_value}' does not match target value '{netkvmco_value}'")
    # Check for the expected log message
    result = get_keyword_from_traceview(expected_log_msg)
    error_context.context(f"Found '{result}' in TraceView logs", logging.info)
    # Restore the default parameter value
    utils_net.set_netkvm_param_value(vm, netkvmco_name, default_value)
    cur_value = utils_net.get_netkvm_param_value(vm, netkvmco_name)
    if cur_value != default_value:
        test.fail(f"Current value '{cur_value}' was not restored to default value '{default_value}'")
    session.close()
