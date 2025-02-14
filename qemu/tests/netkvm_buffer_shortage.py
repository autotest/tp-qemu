import re

from virttest import env_process, error_context, utils_misc, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Simulate high packet rate between host and device by running Python scripts
    on both server and client side. This test is executed on two VM guests:

    1) Start a VM guest as the server.
    2) Start a VM guest as the client.
    3) Simulate buffer allocation issues on the server node.
    4) Use a Python script to connect the client to the server.
    5) Adjust the MinRxBufferPercent parameter to work around the issue.
    6) Ensure no BSOD occurs on the client node.

    :param test: QEMU test object.
    :param params: Dictionary of test parameters.
    :param env: Dictionary of test environment details.
    """

    def analyze_ping_results(session, count, timeout):
        """
        conduct a ping test to check the packet loss on slow memory buffer reallocation

        :param session: Local executon hint or session to execute the ping command.
        :param count: Count of icmp packet.
        :param timeout: Timeout for the ping command.
        """

        status, output = utils_net.ping(
            s_vm_ip, session=c_session, count=count, timeout=timeout
        )
        if status != 0:
            test.fail("Ping failed, status: %s," " output: %s" % (status, output))
        pattern = r"(\d+)% loss"
        match = re.search(pattern, output)
        if match:
            return match.group(1)

    def modify_and_analyze_params_result(vm, netkvmco_name, value):
        """
        First set netkvm driver parameter 'param_name'
        to value 'param_value'. Then read the current and compare
        to 'param_value' to check identity Raised exception when
        checking netkvmco.exe setup was unsuccessful if something is wrong.

        param vm: the selected vm
        param netkvmco_name: the netkvm driver parameter to modify
        param value: the value to set to
        """

        utils_net.set_netkvm_param_value(vm, netkvmco_name, value)
        cur_value = utils_net.get_netkvm_param_value(vm, netkvmco_name)
        if cur_value != value:
            test.fail(f"Current value '{cur_value}' was not equires '{value}'")

    def check_and_restart_port(session, port, script_to_run):
        """
        Check if a Python process is listening on the specified port.
        If not, restart the appropriate Python script (server or client).

        param session:  session to execute commands on the target machine.
        port: the port number to monitor.
        script_to_run:  the path to the Python script to execute.
        """

        check_live_python = params.get("check_live_python")
        dest_location = params.get("dest_location")
        c_pip_copy_cmd = params.get("c_pip_copy_cmd")
        c_pip_cmd = params.get("c_pip_cmd")
        c_py_copy_cmd = params.get("c_py_copy_cmd")
        s_py_copy_cmd = params.get("s_py_copy_cmd")
        status, output = session.cmd_status_output(check_live_python, timeout=1200)
        if status == 0:
            return
        session.cmd(dest_location)
        if "server" in script_to_run:
            error_context.context(
                "Run python3 code runs on the server node", test.log.info
            )
            s_py_copy_cmd = utils_misc.set_winutils_letter(session, s_py_copy_cmd)
            session.cmd(s_py_copy_cmd)
            status, output = session.cmd_status_output(s_py_cmd, timeout=1200)
            if status != 0:
                test.fail("The server node failed to start.")
        else:
            error_context.context(
                "Run python3 code runs on the client node", test.log.info
            )
            c_pip_copy_cmd = utils_misc.set_winutils_letter(session, c_pip_copy_cmd)
            session.cmd(c_pip_copy_cmd)
            session.cmd(c_pip_cmd)
            c_py_copy_cmd = utils_misc.set_winutils_letter(session, c_py_copy_cmd)
            session.cmd(c_py_copy_cmd)
            status, output = session.cmd_status_output(c_py_cmd % s_vm_ip, timeout=1200)
            if status != 0:
                test.fail(
                    "The client could not connect to the server node.", test.log.info
                )

    timeout = params.get_numeric("login_timeout", 360)
    port_num = params.get("port_num")
    s_py_cmd = params.get("s_py_cmd")
    c_py_cmd = params.get("c_py_cmd")
    param_name = params.get("param_name")
    param_values = params.get("param_values")

    s_vm_name = params["vms"].split()[0]
    s_vm = env.get_vm(s_vm_name)
    s_vm.verify_alive()
    s_session = s_vm.wait_for_serial_login(
        timeout=int(params.get("login_timeout", 360))
    )
    s_vm_ip = s_vm.get_address()

    c_vm_name = params["vms"].split(s_vm_name)[1].strip()
    c_vm_params = params.object_params(c_vm_name)
    c_vm_params["nic_extra_params_nic1"] = ""
    c_vm_params["start_vm"] = "yes"
    env_process.preprocess_vm(test, c_vm_params, env, c_vm_name)
    c_vm = env.get_vm(c_vm_name)
    c_vm.verify_alive()
    c_session = c_vm.wait_for_serial_login(
        timeout=int(params.get("login_timeout", 360))
    )

    ping_results = []
    error_context.context(
        "Open the NIC properties and change the values in the server node",
        test.log.info,
    )
    for value in param_values.split(" "):
        modify_and_analyze_params_result(vm=s_vm, netkvmco_name=param_name, value=value)
        check_and_restart_port(session=s_session, port=port_num, script_to_run=s_py_cmd)
        check_and_restart_port(session=c_session, port=port_num, script_to_run=c_py_cmd)
        ping_results.append(
            int(analyze_ping_results(session=c_session, count=100, timeout=timeout))
        )

    error_context.context(
        "Get the packet loss percentage of the ping request", test.log.info
    )
    if sum(ping_results) != 0:
        if not all(
            ping_results[i] > ping_results[i + 1] for i in range(len(ping_results) - 1)
        ):
            test.fail(
                "With the parameter, the number of lost packets should be "
                "less than without the parameter."
            )

    error_context.context("no BSOD will occur on the client side", test.log.info)
    for value in param_values.split(" "):
        modify_and_analyze_params_result(vm=c_vm, netkvmco_name=param_name, value=value)
