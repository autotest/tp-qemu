import logging
import os
import re

from avocado.utils import download
from avocado.utils import process

from virttest import error_context
from virttest import utils_misc


def _process_is_alive(name_pattern):
    return process.system("pgrep -f '^([^ /]*/)*(%s)([ ]|$)'" % name_pattern,
                          ignore_status=True, verbose=False) == 0


@error_context.context_aware
def run(test, params, env):
    """
    Multicast test using iperf.

    1) Boot up VM(s)
    2) Prepare the test environment in server/client/host,install iperf
    3) Execute iperf tests, analyze the results

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def server_start(cmd, catch_data):
        """
        Start the iperf server in host, and check whether the guest have connected
        this server through multicast address of the server
        """
        try:
            process.run(cmd)
        except process.CmdError as e:
            if not re.findall(catch_data, e.result.stdout):
                test.fail("Client not connected '%s'" % str(e))
            logging.info("Client multicast test pass "
                         % re.findall(catch_data, str(e)))

    os_type = params.get("os_type")
    win_iperf_url = params.get("win_iperf_url")
    linux_iperf_url = params.get("linux_iperf_url")
    iperf_version = params.get("iperf_version", "2.0.5")
    transfer_timeout = int(params.get("transfer_timeout", 360))
    login_timeout = int(params.get("login_timeout", 360))

    dir_name = test.tmpdir
    tmp_dir = params.get("tmp_dir", "/tmp/")
    host_path = os.path.join(dir_name, "iperf")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    clean_cmd = ""
    client_ip = vm.get_address(0)

    try:
        error_context.context("Test Env setup")
        iperf_downloaded = 0
        iperf_url = linux_iperf_url

        app_check_cmd = params.get("linux_app_check_cmd", "false")
        app_check_exit_status = int(params.get("linux_app_check_exit_status",
                                               "0"))
        exit_status = process.system(app_check_cmd, ignore_status=True,
                                     shell=True)

        # Install iperf in host if not available
        default_install_cmd = "tar zxvf %s; cd iperf-%s;"
        default_install_cmd += " ./configure; make; make install"
        install_cmd = params.get("linux_install_cmd", default_install_cmd)
        if not exit_status == app_check_exit_status:
            error_context.context("install iperf in host", logging.info)
            download.get_file(iperf_url, host_path)
            iperf_downloaded = 1
            process.system(install_cmd % (host_path, iperf_version),
                           shell=True)

        # The guest may not be running Linux, see if we should update the
        # app_check variables
        if not os_type == "linux":
            app_check_cmd = params.get("win_app_check_cmd", "false")
            app_check_exit_status = int(params.get("win_app_check_exit_status",
                                                   "0"))

        # Install iperf in guest if not available
        if not session.cmd_status(app_check_cmd) == app_check_exit_status:
            error_context.context("install iperf in guest", logging.info)
            if not iperf_downloaded:
                download.get_file(iperf_url, host_path)
            if os_type == "linux":
                guest_path = (tmp_dir + "iperf.tgz")
                clean_cmd = "rm -rf %s iperf-%s" % (guest_path, iperf_version)
            else:
                guest_path = (tmp_dir + "iperf.exe")
                iperf_url = win_iperf_url
                download.get_file(iperf_url, host_path)
                clean_cmd = "del %s" % guest_path
            vm.copy_files_to(host_path, guest_path, timeout=transfer_timeout)

            if os_type == "linux":
                session.cmd(install_cmd % (guest_path, iperf_version))

        muliticast_addr = params.get("muliticast_addr", "225.0.0.3")
        multicast_port = params.get("multicast_port", "5001")

        step_msg = "Start iperf server, bind host to multicast address %s "
        error_context.context(step_msg % muliticast_addr, logging.info)
        server_start_cmd = ("iperf -s -u -B %s -p %s " %
                            (muliticast_addr, multicast_port))

        default_flag = "%s port %s connected with %s"
        connected_flag = params.get("connected_flag", default_flag)
        catch_data = connected_flag % (muliticast_addr, multicast_port,
                                       client_ip)
        t = utils_misc.InterruptedThread(server_start,
                                         (server_start_cmd, catch_data))
        t.start()
        if not _process_is_alive("iperf"):
            test.error("Start iperf server failed cmd: %s" % server_start_cmd)
        logging.info("Server start successfully")

        step_msg = "In client try to connect server and transfer file "
        step_msg += " through multicast address %s"
        error_context.context(step_msg % muliticast_addr, logging.info)
        if os_type == "linux":
            client_cmd = "iperf"
        else:
            client_cmd = guest_path
        start_cmd = params.get("start_client_cmd", "%s -c %s -u -p %s")
        start_client_cmd = start_cmd % (client_cmd, muliticast_addr,
                                        multicast_port)
        session.cmd(start_client_cmd)
        logging.info("Client start successfully")

        error_context.context("Test finish, check the result", logging.info)
        process.system("pkill -2 iperf")
        t.join()

    finally:
        if _process_is_alive("iperf"):
            process.system("killall -9 iperf")
        process.system("rm -rf %s" % host_path)
        if session:
            if clean_cmd:
                session.cmd(clean_cmd)
            session.close()
