import os
import re
import shutil

from aexpect import ShellCmdError
from avocado.utils import process
from virttest import data_dir, error_context, utils_misc, utils_net, utils_package


@error_context.context_aware
def run(test, params, env):
    """
    iperf testing with multicast/multiqueue.

    1) Boot up VM
    2) Prepare the iperf environment
    3) Select guest or host to start iperf server/client
    4) Execute iperf tests, analyze the result
    5) Finish test and cleanup host environment
    6) Add rss test for virtio-net dirver

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def iperf_compile(src_path, dst_path, session=None):
        """Compile iperf and return its binary file path."""
        iperf_version = params["iperf_version"]
        iperf_source_path = os.path.join(dst_path, iperf_version)
        compile_cmd = params["linux_compile_cmd"] % (
            src_path,
            dst_path,
            iperf_source_path,
        )
        try:
            if session:
                test.log.info("Compiling %s in guest...", iperf_version)
                session.cmd(compile_cmd)
            else:
                test.log.info("Compiling %s in host...", iperf_version)
                process.run(compile_cmd, shell=True, verbose=False)
        except (process.CmdError, ShellCmdError) as err_msg:
            test.log.error(err_msg)
            test.error("Failed to compile iperf")
        else:
            iperf_bin_name = re.sub(r"[-2]", "", iperf_version.split(".")[0])
            return os.path.join(iperf_source_path, "src", iperf_bin_name)

    def iperf_start(session, iperf_path, options, catch_data):
        """Start iperf session, analyze result if catch_data."""
        iperf_cmd = iperf_path + options
        try:
            info_text = "Start iperf session in %s with cmd: %s"
            if session:
                test.log.info(info_text, "guest", iperf_cmd)
                data_info = session.cmd_output(iperf_cmd, timeout=120)
            else:
                test.log.info(info_text, "host", iperf_cmd)
                data_info = process.system_output(
                    iperf_cmd, timeout=120, verbose=False
                ).decode()
        except Exception as err_msg:
            test.log.error(str(err_msg))
            test.error("Failed to start iperf session")
        else:
            if catch_data:
                test.log.debug("Full connection log:\n%s", data_info)
                parallel_cur = len(re.findall(catch_data, data_info))
                parallel_exp = int(params.get("parallel_num", 0))
                if not parallel_cur:
                    test.fail("iperf client not connected to server")
                elif parallel_exp and parallel_cur != parallel_exp:
                    test.fail(
                        "Number of parallel threads running(%d) is "
                        "inconsistent with expectations(%d)"
                        % (parallel_cur, parallel_exp)
                    )
                test.log.info("iperf client successfully connected to server")

    def is_iperf_running(name_pattern, session=None):
        if session:
            check_iperf_cmd = params["check_iperf_cmd"] % name_pattern
            status = serial_session.cmd_status(check_iperf_cmd)
        else:
            status = process.system(
                "pgrep -f %s" % name_pattern, ignore_status=True, verbose=False
            )
        return status == 0

    def rss_check():
        if os_type == "linux":
            ifname = utils_net.get_linux_ifname(guest_session, vm.get_mac_address())
            check_rss_state_cmd = params.get("check_rss_state")
            output = guest_session.cmd_output(check_rss_state_cmd % ifname)
            error_messages = "Operation not supported"
            if error_messages in output:
                test.fail("Rss support for virtio-net driver is bad")
            else:
                test.log.info("Rss support for virtio-net driver is works well")
            test.log.info("enable rxhash to check network if can works well")
            enable_rxhash_cmd = params.get("enable_rxhash_cmd")
            status, output = guest_session.cmd_status_output(enable_rxhash_cmd % ifname)
            if status != 0:
                test.fail("Can not enable rxhash: %s" % output)
        else:
            test.log.info('Run the command "netkvm-wmi.cmd rss" to collect statistics')
            rss_test_cmd = utils_misc.set_winutils_letter(
                guest_session, params["rss_test_cmd"]
            )
            rss_statistics = guest_session.cmd_output(rss_test_cmd)
            patterns = r"^((?:Errors)|(?:Misses))=0"
            result = re.findall(patterns, rss_statistics, re.M)
            if len(result) == 2:
                test.log.info("Rss support for virtio-net driver is works well")
            else:
                test.fail("Rss support for virtio-net driver is bad")

    os_type = params["os_type"]
    login_timeout = int(params.get("login_timeout", 360))
    fw_stop_cmd = params["fw_stop_cmd"]
    tmp_dir = params.get("tmp_dir", "/tmp/")
    iperf_test_duration = int(params["iperf_test_duration"])
    iperf_deps_dir = data_dir.get_deps_dir("iperf")
    host_iperf_file = params["host_iperf_file"]
    guest_iperf_file = params.get("guest_iperf_file", host_iperf_file)
    host_iperf_src_path = os.path.join(iperf_deps_dir, host_iperf_file)
    guest_iperf_remote_path = os.path.join(iperf_deps_dir, guest_iperf_file)
    guest_iperf_path = params.get("guest_iperf_path", tmp_dir)
    guest_iperf_src_path = os.path.join(guest_iperf_path, guest_iperf_file)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    serial_session = vm.wait_for_serial_login(timeout=login_timeout)
    guest_session = vm.wait_for_login(timeout=login_timeout)
    guest_session.cmd(fw_stop_cmd, ignore_all_errors=True)

    vm.copy_files_to(guest_iperf_remote_path, guest_iperf_path)
    host_ip_addr = utils_net.get_host_ip_address(params)
    guest_ip_addr = vm.get_address()
    host_iperf_bin = iperf_compile(host_iperf_src_path, tmp_dir)

    if os_type == "linux":
        if not utils_package.package_install("gcc-c++", guest_session):
            test.cancel("Please install gcc-c++ to proceed")
        guest_iperf__bin = iperf_compile(guest_iperf_src_path, tmp_dir, guest_session)
    else:
        guest_iperf__bin = guest_iperf_src_path
        iperf_deplist = params.get("iperf_deplist")
        if iperf_deplist:
            for d_name in iperf_deplist.split(","):
                dep_path = os.path.join(data_dir.get_deps_dir("iperf"), d_name)
                vm.copy_files_to(dep_path, guest_iperf_path)

    search_pattern = {
        "host": host_iperf_bin.replace("src/", "src/.*"),
        "linux": guest_iperf__bin.replace("src/", "src/.*"),
        "windows": guest_iperf_file,
    }

    if params.get("iperf_server") == params["main_vm"]:
        s_ip = params.get("multicast_addr", guest_ip_addr)
        s_info = [search_pattern[os_type], s_ip, guest_session, guest_iperf__bin]
        c_info = [search_pattern["host"], host_ip_addr, None, host_iperf_bin]
    else:
        s_ip = params.get("multicast_addr", host_ip_addr)
        s_info = [search_pattern["host"], s_ip, None, host_iperf_bin]
        c_info = [
            search_pattern[os_type],
            guest_ip_addr,
            guest_session,
            guest_iperf__bin,
        ]

    s_catch_data = params["catch_data"] % (s_info[1], c_info[1])
    s_options = params["iperf_server_options"]
    c_options = params["iperf_client_options"] % (
        s_info[1],
        c_info[1],
        iperf_test_duration,
    )
    s_info.extend([s_options, s_catch_data])
    c_info.extend([c_options, None])

    try:
        if params.get_boolean("rss_test"):
            rss_check()

        s_start_args = tuple(s_info[-4:])
        c_start_args = tuple(c_info[-4:])
        bg_server = utils_misc.InterruptedThread(iperf_start, s_start_args)
        bg_client = utils_misc.InterruptedThread(iperf_start, c_start_args)

        bg_server.start()
        if not utils_misc.wait_for(
            lambda: is_iperf_running(s_info[0], s_info[2]), 5, 2
        ):
            test.error("Failed to start iperf server.")
        error_context.context("iperf server has started.", test.log.info)
        bg_client.start()
        if not utils_misc.wait_for(lambda: is_iperf_running(c_info[0], c_info[2]), 5):
            test.error("Failed to start iperf client.")
        error_context.context("iperf client has started.", test.log.info)
        utils_misc.wait_for(
            lambda: not is_iperf_running(c_info[0], c_info[2]),
            iperf_test_duration,
            0,
            5,
            "Waiting for iperf test to finish.",
        )
        bg_server.join(timeout=60)
        bg_client.join(timeout=60)

    finally:
        test.log.info("Cleanup host environment...")
        if is_iperf_running(search_pattern["host"]):
            process.run(
                "pkill -9 -f %s" % search_pattern["host"],
                verbose=False,
                ignore_status=True,
            )
        shutil.rmtree(host_iperf_bin.rsplit("/", 2)[0], ignore_errors=True)
        guest_session.close()
        serial_session.close()
