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

    def analyze_ping_results(session, dest, count, timeout):
        """
        Conduct a ping test to check the packet loss on slow memory buffer reallocation.

        :param session: The session to execute the ping command.
        :param dest: Destination IP address to ping.
        :param count: Number of ICMP packets to send.
        :param timeout: Timeout for the ping command.
        """
        status, output = utils_net.ping(
            dest=dest, session=session, count=count, timeout=timeout
        )
        if status != 0:
            test.fail("Ping failed, status: %s, output: %s" % (status, output))
        match = re.search(r"(\d+)% loss", output)
        return match and match.group(1)

    def modify_and_analyze_params_result(vm, param_name, value):
        """
        Set netkvm driver parameter and verify if it was correctly set.

        :param vm: Target VM.
        :param param_name: Parameter name to be modified.
        :param value: Value to set.
        """
        utils_net.set_netkvm_param_value(vm, param_name, value)
        cur_value = utils_net.get_netkvm_param_value(vm, param_name)
        if cur_value != value:
            test.fail(f"Failed to set '{param_name}' to '{value}'")

    def check_and_restart_port(session, script_to_run):
        """
        Check if a Python process is running. If not, restart the appropriate script.

        :param session: The session to execute commands.
        :param script_to_run: The command to run the Python script.
        """
        check_live_python = params.get("check_live_python")
        status, output = session.cmd_status_output(check_live_python, timeout=1200)
        if status == 0:
            return
        if "server" in script_to_run:
            s_session.cmd(dest_location)
            error_context.context("Run server script on the server node", test.log.info)
            status, output = session.cmd_status_output(server_cmd, timeout=1200)
            if status != 0:
                test.fail("The server node failed to start.")
        else:
            c_session.cmd(dest_location)
            error_context.context("Run client script on the client node", test.log.info)
            status, output = session.cmd_status_output(
                client_cmd % s_vm_ip, timeout=1200
            )
            if status != 0:
                test.fail("The client could not connect to the server node.")

    timeout = params.get_numeric("login_timeout", 360)
    param_name = params.get("param_name")
    param_values = params.get("param_values")
    dest_location = params.get("dest_location")
    copy_all_cmd = params.get("copy_all_cmd")
    pip_cmd = params.get("pip_cmd")
    server_cmd = params.get("server_cmd")
    client_cmd = params.get("client_cmd")

    s_vm_name = params["vms"].split()[0]
    s_vm = env.get_vm(s_vm_name)
    s_vm.verify_alive()
    s_session = s_vm.wait_for_serial_login(timeout=timeout)
    s_vm_ip = s_vm.get_address()

    c_vm_name = params["vms"].split(s_vm_name)[1].strip()
    c_vm_params = params.object_params(c_vm_name)
    c_vm_params["nic_extra_params_nic1"] = ""
    c_vm_params["start_vm"] = "yes"
    env_process.preprocess_vm(test, c_vm_params, env, c_vm_name)
    c_vm = env.get_vm(c_vm_name)
    c_vm.verify_alive()
    c_session = c_vm.wait_for_serial_login(timeout=timeout)
    c_vm_ip = c_vm.get_address()

    # Copy and install dependencies
    s_session.cmd(dest_location)
    copy_all_cmd = utils_misc.set_winutils_letter(s_session, copy_all_cmd)
    s_session.cmd(copy_all_cmd)

    c_session.cmd(dest_location)
    copy_all_cmd = utils_misc.set_winutils_letter(c_session, copy_all_cmd)
    c_session.cmd(copy_all_cmd)
    c_session.cmd(pip_cmd)

    # Run the packet loss simulation with different buffer settings
    ping_results = []
    error_context.context(
        "Modify NIC parameters on the server and monitor packet loss", test.log.info
    )
    for value in param_values.split():
        modify_and_analyze_params_result(vm=s_vm, param_name=param_name, value=value)
        check_and_restart_port(session=s_session, script_to_run=server_cmd)
        check_and_restart_port(session=c_session, script_to_run=client_cmd)
        ping_loss = int(
            analyze_ping_results(
                session=c_session, dest=s_vm_ip, count=100, timeout=timeout
            )
        )
        ping_results.append(ping_loss)

    error_context.context("Analyze ping packet loss trend", test.log.info)
    if sum(ping_results) != 0:
        if not all(
            ping_results[i] > ping_results[i + 1] for i in range(len(ping_results) - 1)
        ):
            test.fail(
                "With parameter changes, packet loss should decrease progressively."
            )

    # Final validation on client side (no BSOD)
    error_context.context("Verify no BSOD on the client node", test.log.info)
    for value in param_values.split():
        modify_and_analyze_params_result(vm=c_vm, param_name=param_name, value=value)
    status, output = utils_net.ping(
        dest=c_vm_ip, session=c_session, count=10, timeout=60
    )
    if status != 0:
        test.fail("Ping failed, status: %s, output: %s" % (status, output))
