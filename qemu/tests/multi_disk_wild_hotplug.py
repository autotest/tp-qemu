"""Wild hot-plug-unplug test"""

import copy
import os
import time

from avocado.utils import process
from virttest import data_dir as virttest_data_dir
from virttest import env_process, error_context
from virttest.qemu_monitor import QMPCmdError


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    1) Boot the vm with multiple data disks.
    2) Run some operation in guest if requested.
    3) Execute device_del for data disks.
    4) Sleep some time.
    5) Execute device_add for data disks.
    6) Sleep some time.
    7) repeat step 3-6 if requested.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _run_sg_luns():
        file_name = "guest_sg_luns.sh"
        guest_dir = "/tmp/"
        deps_dir = virttest_data_dir.get_deps_dir()
        host_file = os.path.join(deps_dir, file_name)
        guest_file = guest_dir + file_name
        vm.copy_files_to(host_file, guest_dir)
        session.sendline("$SHELL " + guest_file)

    def _simple_io_test():
        file_name = "guest_sg_luns.sh"
        guest_dir = "/tmp/"
        deps_dir = virttest_data_dir.get_deps_dir()
        host_file = os.path.join(deps_dir, file_name)
        guest_file = guest_dir + file_name
        vm.copy_files_to(host_file, guest_dir)
        session.sendline("$SHELL " + guest_file)

    def _configure_images_params():
        for i in range(image_num):
            name = "stg%d" % i
            params["image_name_%s" % name] = "images/%s" % name
            params["image_size_%s" % name] = stg_image_size
            params["images"] = params["images"] + " " + name
            if params["drive_format"] == "scsi-hd":
                params["drive_bus_%s" % name] = 0 if share_bus == "yes" else 1
                params["blk_extra_params_%s" % name] = "lun=%d" % (i + 1)
            image_params = params.object_params(name)
            env_process.preprocess_image(test, image_params, name)

    def _get_images_params():
        for i in range(image_num):
            name = "stg%d" % i
            dev = vm.devices.get_by_qid(name)[0]
            images_params[name] = copy.deepcopy(dev.params)

    def _hotplug_images():
        for i in range(1, image_num):
            name = "stg%d" % i
            try:
                vm.monitor.cmd("device_add", images_params[name], debug=False)
            except QMPCmdError as e:
                test.log.warning("Ignore hotplug error: %s", str(e))

    def _hotunplug_images():
        for i in range(1, image_num):
            name = "stg%d" % i
            try:
                vm.monitor.cmd("device_del", {"id": name}, debug=False)
            except QMPCmdError as e:
                test.log.warning("Ignore hotunplug error: %s", str(e))

    stg_image_size = params.get("stg_image_size", "256M")
    image_num = params.get_numeric("stg_image_num", 20)
    repeat_num = params.get_numeric("repeat_num", 1)
    unplug_time = params.get_numeric("unplug_time", 5)
    plug_time = params.get_numeric("plug_time", 5)
    wait_time = params.get_numeric("wait_time", 0)
    share_bus = params.get("share_bus", "no")
    images_params = {}
    error_context.context("Create images %d" % image_num, test.log.info)
    _configure_images_params()
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    try:
        session = vm.wait_for_login(timeout=params.get_numeric("login_timeout", 360))

        error_context.context("Get images params", test.log.info)
        _get_images_params()

        disks_num = int(session.cmd("lsblk -d -n|wc -l", timeout=60))
        test.log.info("There are total %d disks", disks_num)

        guest_operation = params.get("guest_operation")
        if guest_operation:
            test.log.info("Run %s in guest ", guest_operation)
            locals_var = locals()
            locals_var[guest_operation]()

        for n in range(repeat_num):
            error_context.context("Start unplug loop:%d" % n, test.log.info)
            _hotunplug_images()
            time.sleep(unplug_time)
            error_context.context("Start plug loop:%d" % n, test.log.info)
            _hotplug_images()
            time.sleep(plug_time)

        error_context.context("Waiting for %d seconds" % wait_time, test.log.info)
        time.sleep(wait_time)
        error_context.context("Check disks in guest.", test.log.info)
        # re-login in case previous session is expired
        session = vm.wait_for_login(timeout=params.get_numeric("relogin_timeout", 60))
        new_disks_num = int(session.cmd("lsblk -d -n|wc -l", timeout=300))
        test.log.info("There are total %d disks after hotplug", new_disks_num)
        if new_disks_num != disks_num:
            test.log.warning(
                "Find unmatched disk numbers %d %d", disks_num, new_disks_num
            )
    except Exception as e:
        pid = vm.get_pid()
        test.log.debug("Find %s Exception:'%s'.", pid, str(e))
        if pid:
            logdir = test.logdir
            process.getoutput("gstack %s > %s/gstack.log" % (pid, logdir))
            process.getoutput(
                "timeout 20 strace -tt -T -v -f -s 32 -p %s -o %s/strace.log"
                % (pid, logdir)
            )
        else:
            test.log.debug("VM dead...")
        raise e
