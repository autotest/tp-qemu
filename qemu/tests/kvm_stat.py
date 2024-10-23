import os
import re

from avocado.utils import process
from virttest import env_process, utils_misc, utils_package
from virttest.utils_numeric import normalize_data_size


def run(test, params, env):
    """
    1.install kernel-tools package in host
    2.modify kvm_stat.service file and start kvm_stat.service
    3.run VM
    4.use "logrotate" to separate the log file
    5.Check the generated log file

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    interval = float(params.get("interval_time", "10"))

    def tweak_file(origin, target, filename):
        with open(filename, "r") as f:
            content = f.read()
            content = re.sub(origin, target, content)
        with open(filename, "w") as f:
            f.write(content)

    def separate_file(file_path, rotate_size_limit):
        rotate_size_limit = int(
            normalize_data_size(rotate_size_limit, order_magnitude="B", factor=1024)
        )
        num = rotate_time + 1
        while num > 0:
            if utils_misc.wait_for(
                lambda: os.path.getsize(file_path) > rotate_size_limit, 60, 5, 5
            ):
                process.system("logrotate -v /etc/logrotate.d/kvm_stat")
            num -= 1

    def check_log():
        test.log.info("check if log file num match with rotate")
        check_log_num = int(
            process.system_output(params.get("check_log_num"), shell=True)
        )
        if check_log_num == rotate_time:
            test.log.info("Get the expected log file num %s", check_log_num)
        else:
            test.fail("Except %s log file, but get %s" % (rotate_time, check_log_num))

    def restore_env():
        test.log.info("Restore the host environment")
        tweak_file(
            r"-s\s([\.\d]+)\s",
            "-s %s " % initial_kvm_stat_interval,
            kvm_stat_service_path,
        )
        tweak_file(
            r"size \s(.*)\s",
            "size %s" % initial_rotate_size,
            logrotate_config_file_path,
        )

    depends_pkgs = params.objects("depends_pkgs")
    test.log.info("Install packages: %s in host", depends_pkgs)
    if not utils_package.package_install(depends_pkgs):
        test.cancel("Install %s packages failed", depends_pkgs)

    kvm_stat_service_path = params.get("kvm_stat_service_path")
    with open(kvm_stat_service_path, "r") as fd:
        content = fd.read()
    initial_kvm_stat_interval = re.search(
        r"ExecStart=.*-s\s([\.\d]+)\s", content
    ).group(1)

    logrotate_config_file_path = params.get("logrotate_config_file_path")
    with open(logrotate_config_file_path, "r") as fd:
        content = fd.read()
    initial_rotate_size = re.search(r"size\s(.*)\s", content).group(1)
    rotate_time = int(re.search(r"rotate\s+(\d+)", content)[1])

    rotate_size_limit = params.get("rotate_size_limit")
    kvm_stat_interval = params.get("kvm_stat_interval")

    try:
        test.log.info(
            "Adjust the parameter '-s' is %s in %s",
            kvm_stat_interval,
            kvm_stat_service_path,
        )
        tweak_file(
            r"-s %s" % initial_kvm_stat_interval,
            "-s %s" % kvm_stat_interval,
            kvm_stat_service_path,
        )

        test.log.info("Start kvm_stat.service")
        kvm_stat_start_cmd = params.get("kvm_stat_start_cmd")
        start_service = process.system(kvm_stat_start_cmd, timeout=interval, shell=True)
        if start_service != 0:
            test.error("Failed to start the kvm_stat.server")
        else:
            test.log.info("Successfully to start the kvm_stat.service")

        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        env.get_vm(params["main_vm"])

        test.log.info("Start logrotate command")
        tweak_file(
            r"size %s" % initial_rotate_size,
            "size %s" % rotate_size_limit,
            logrotate_config_file_path,
        )
        log_file = params.get("log_file")
        separate_file(log_file, rotate_size_limit)
        check_log()
    finally:
        restore_env()
