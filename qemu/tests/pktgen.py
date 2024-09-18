import os
import re
import time

import aexpect
from avocado.utils import process
from virttest import data_dir, error_context, remote, utils_misc, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Run Pktgen test between host/guest

    1) Boot the main vm, or just grab it if it's already booted.
    2) Configure pktgen server(only linux)
    3) Run pktgen test, finish when timeout or env["pktgen_run"] != True

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    login_timeout = float(params.get("login_timeout", 360))
    error_context.context("Init the VM, and try to login", test.log.info)
    external_host = params.get("external_host")
    if not external_host:
        get_host_cmd = "ip route | awk '/default/ {print $3}'"
        external_host = process.system_output(get_host_cmd, shell=True).decode()
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)

    error_context.context("Pktgen server environment prepare", test.log.info)
    # pktgen server only support linux, since pktgen is a linux kernel module
    pktgen_server = params.get("pktgen_server", "localhost")
    params_server = params.object_params("pktgen_server")
    s_shell_client = params_server.get("shell_client", "ssh")
    s_shell_port = params_server.get("shell_port", "22")
    s_username = params_server.get("username", "root")
    s_passwd = params_server.get("password", "123456")
    s_shell_prompt = params_server.get("shell_prompt")

    server_session = ""
    # pktgen server is autotest virtual guest(only linux)
    if pktgen_server in params.get("vms", "vm1 vm2"):
        vm_pktgen = env.get_vm(pktgen_server)
        vm_pktgen.verify_alive()
        server_session = vm_pktgen.wait_for_login(timeout=login_timeout)
        runner = server_session.cmd
        pktgen_ip = vm_pktgen.get_address()
        pktgen_mac = vm_pktgen.get_mac_address()
        server_interface = utils_net.get_linux_ifname(server_session, pktgen_mac)
    # pktgen server is a external host assigned
    elif re.match(r"((\d){1,3}\.){3}(\d){1,3}", pktgen_server):
        pktgen_ip = pktgen_server
        server_session = remote.wait_for_login(
            s_shell_client,
            pktgen_ip,
            s_shell_port,
            s_username,
            s_passwd,
            s_shell_prompt,
        )
        runner = server_session.cmd
        server_interface = params.get("server_interface")
        if not server_interface:
            test.cancel("Must config server interface before test")
    else:
        # using host as a pktgen server
        server_interface = params.get("netdst", "switch")
        host_nic = utils_net.Interface(server_interface)
        pktgen_ip = host_nic.get_ip()
        pktgen_mac = host_nic.get_mac()
        runner = process.system

    # copy pktgen_test scipt to the test server.
    local_path = os.path.join(data_dir.get_root_dir(), "shared/scripts/pktgen.sh")
    remote_path = "/tmp/pktgen.sh"
    remote.scp_to_remote(
        pktgen_ip, s_shell_port, s_username, s_passwd, local_path, remote_path
    )

    error_context.context("Run pktgen test", test.log.info)
    run_threads = params.get("pktgen_threads", 1)
    pktgen_stress_timeout = float(params.get("pktgen_test_timeout", 600))
    exec_cmd = "%s %s %s %s %s" % (
        remote_path,
        vm.get_address(),
        vm.get_mac_address(),
        server_interface,
        run_threads,
    )
    try:
        env["pktgen_run"] = True
        try:
            # Set a run flag in env, when other case call this case as a sub
            # backgroud process, can set run flag to False to stop this case.
            start_time = time.time()
            stop_time = start_time + pktgen_stress_timeout
            while env["pktgen_run"] and time.time() < stop_time:
                runner(exec_cmd, timeout=pktgen_stress_timeout)

        # using ping to kill the pktgen stress
        except aexpect.ShellTimeoutError:
            session.cmd("ping %s" % pktgen_ip, ignore_all_errors=True)
    finally:
        env["pktgen_run"] = False

    error_context.context(
        "Verify Host and guest kernel no error " "and call trace", test.log.info
    )
    vm.verify_kernel_crash()
    utils_misc.verify_dmesg()

    error_context.context("Ping external host after pktgen test", test.log.info)
    session_ping = vm.wait_for_login(timeout=login_timeout)
    status, output = utils_test.ping(
        dest=external_host, session=session_ping, timeout=240, count=20
    )
    loss_ratio = utils_test.get_loss_ratio(output)
    if loss_ratio > int(params.get("packet_lost_ratio", 5)) or loss_ratio == -1:
        test.log.debug("Ping %s output: %s", external_host, output)
        test.fail(
            "Guest network connction unusable, "
            "packet lost ratio is '%d%%'" % loss_ratio
        )
    if server_session:
        server_session.close()
    if session:
        session.close()
    if session_ping:
        session_ping.close()
