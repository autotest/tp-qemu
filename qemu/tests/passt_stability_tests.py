import os
import re
import shutil
import time

from aexpect import ShellCmdError
from avocado.utils import process
from virttest import data_dir, error_context, utils_misc, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    passt stability tests

    1) Boot up VM with passt backend
    2) Prepare the iperf environment
    3) Select host to start iperf server, guest as client
    4) Execute iperf tests, analyze the result
    5) Finish test and cleanup host environment

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def transfer_iperf_package():
        receive_cmd = params.get("receive_cmd")
        serial_session.sendline(receive_cmd)
        time.sleep(5)
        sent_cmd = params.get("sent_cmd")
        process.run(sent_cmd % host_iperf_src_path)

    def iperf_compile(src_path, dst_path, serial_session=None):
        """Compile iperf and return its binary file path."""
        iperf_version = params["iperf_version"]
        iperf_source_path = os.path.join(dst_path, iperf_version)
        compile_cmd = params["linux_compile_cmd"] % (
            src_path,
            dst_path,
            iperf_source_path,
        )
        try:
            if serial_session:
                test.log.info("Compiling %s in guest...", iperf_version)
                serial_session.sendline(compile_cmd)
            else:
                test.log.info("Compiling %s in host...", iperf_version)
                process.run(compile_cmd, shell=True, verbose=False)
        except (process.CmdError, ShellCmdError) as err_msg:
            test.log.error(err_msg)
            test.error("Failed to compile iperf")
        else:
            iperf_bin_name = re.sub(r"[-2]", "", iperf_version.split(".")[0])
            return os.path.join(iperf_source_path, "src", iperf_bin_name)

    def iperf_server_start():
        """Start iperf server"""
        info_text = "Start iperf server session in %s with cmd: %s"
        iperf_server_cmd = iperf_server_options % host_iperf_bin
        try:
            test.log.info(info_text, "host", iperf_server_cmd)
            server_output = process.system_output(
                iperf_server_cmd, timeout=300, verbose=False
            ).decode()
        except Exception as err_msg:
            test.log.error(str(err_msg))
            test.error("Failed to start iperf session")
        else:
            test.log.debug("Full connection server log:\n%s", server_output)
            catch_data = params["catch_data"]
            parallel_cur = len(re.findall(catch_data, server_output))
            parallel_exp = int(params.get("parallel_num", 0))
            if not parallel_cur:
                test.fail("iperf client not connected to server")
            elif parallel_exp and parallel_cur != parallel_exp:
                test.fail(
                    "Number of parallel threads running(%d) is "
                    "inconsistent with expectations(%d)" % (parallel_cur, parallel_exp)
                )
            test.log.info("iperf client successfully connected to server")

    def iperf_client_start():
        """ "Start iperf client"""
        info_text = "Start iperf client session in %s with cmd: %s"
        iperf_client_cmd = iperf_client_options % (guest_iperf_bin, client_getway)
        test.log.info(info_text, "guest", iperf_client_cmd)
        serial_session.sendline(iperf_client_cmd)

    def is_iperf_running(name_pattern, session=None):
        if session:
            check_iperf_cmd = params["check_iperf_cmd"] % name_pattern
            status = serial_session.cmd_status(check_iperf_cmd, safe=True)
        else:
            status = process.system(
                "pgrep -f %s" % name_pattern, ignore_status=True, verbose=False
            )
        return status == 0

    login_timeout = params.get_numeric("login_timeout", 360)
    fw_stop_cmd = params["fw_stop_cmd"]
    tmp_dir = params.get("tmp_dir", "/tmp")
    iperf_deps_dir = data_dir.get_deps_dir("iperf")
    host_iperf_file = params["host_iperf_file"]
    host_iperf_src_path = os.path.join(iperf_deps_dir, host_iperf_file)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    serial_session = vm.wait_for_serial_login(timeout=login_timeout)
    serial_session.cmd_output_safe(fw_stop_cmd)

    client_getway = utils_net.get_default_gateway()
    transfer_iperf_package()
    host_iperf_bin = iperf_compile(host_iperf_src_path, tmp_dir)
    guest_iperf_file = params.get("guest_iperf_file", host_iperf_file)
    guest_iperf_path = params.get("guest_iperf_path", tmp_dir)
    guest_iperf_src_path = os.path.join(guest_iperf_path, guest_iperf_file)
    guest_iperf_bin = iperf_compile(guest_iperf_src_path, tmp_dir, serial_session)
    iperf_server_options = params.get("iperf_server_options")
    iperf_client_options = params.get("iperf_client_options")

    try:
        bg_server = utils_misc.InterruptedThread(iperf_server_start)
        bg_client = utils_misc.InterruptedThread(iperf_client_start)
        bg_server.start()
        if not utils_misc.wait_for(lambda: is_iperf_running(host_iperf_bin), 5, 2):
            test.error("Failed to start iperf server.")
        error_context.context("iperf server has started.", test.log.info)
        bg_client.start()

        error_context.context("iperf client has started.", test.log.info)
        if not utils_misc.wait_for(
            lambda: is_iperf_running(guest_iperf_bin, serial_session), 5, 2
        ):
            test.error("Failed to start iperf client.")
        utils_misc.wait_for(
            lambda: not is_iperf_running(host_iperf_bin),
            330,
            0,
            30,
            "Waiting for iperf test to finish.",
        )
        bg_server.join(timeout=60)
        bg_client.join(timeout=60)

    finally:
        test.log.info("Cleanup host environment...")
        process.run(
            "pkill -9 -f %s" % host_iperf_bin, verbose=False, ignore_status=True
        )
        shutil.rmtree(host_iperf_bin.rsplit("/", 2)[0], ignore_errors=True)
        serial_session.close()
