"""Wild hot-plug-unplug test"""
import copy
import logging
import time
import os

from virttest.qemu_monitor import QMPCmdError
from virttest import error_context, env_process
from virttest import data_dir as virttest_data_dir


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    1) Boot the vm with multiple data disks.
    2) Run some operation in guest if request.
    3) Execute device_del for data disks.
    4) Sleep some time.
    5) Execute device_add for data disks.
    6) Sleep some time.
    7) repeat step 3-6 if request.

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

    def _configure_images_params():
        for i in range(image_num):
            name = "stg%d" % i
            params['image_name_%s' % name] = "images/%s" % name
            params['image_size_%s' % name] = stg_image_size
            params["images"] = params["images"] + " " + name
            if params["drive_format"] == "scsi-hd":
                params["drive_bus_%s" % name] = 1
                params["blk_extra_params_%s" % name] = "lun=%d" % i
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
                logging.warning('Ignore hotplug error: %s', str(e))

    def _hotunplug_images():
        for i in range(1, image_num):
            name = "stg%d" % i
            try:
                vm.monitor.cmd("device_del", {"id": name}, debug=False)
            except QMPCmdError as e:
                logging.warning('Ignore hotunplug error: %s', str(e))

    stg_image_size = params.get("stg_image_size", "256M")
    image_num = params.get_numeric("stg_image_num", 20)
    repeat_num = params.get_numeric("repeat_num", 1)
    unplug_time = params.get_numeric("unplug_time", 5)
    plug_time = params.get_numeric("plug_time", 5)
    images_params = {}
    error_context.context("Create images %d" % image_num, logging.info)
    _configure_images_params()
    params['start_vm'] = 'yes'
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params['main_vm'])
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    error_context.context("Get images params", logging.info)
    _get_images_params()

    disks_num = int(session.cmd("lsblk -d -n|wc -l", timeout=60))
    logging.info("There are total %d disks", disks_num)

    guest_operation = params.get("guest_operation")
    if guest_operation:
        logging.info("Run %s in guest ", guest_operation)
        locals_var = locals()
        locals_var[guest_operation]()

    for n in range(repeat_num):
        error_context.context("Start unplug loop:%d" % n, logging.info)
        _hotunplug_images()
        time.sleep(unplug_time)
        error_context.context("Start plug loop:%d" % n, logging.info)
        _hotplug_images()
        time.sleep(plug_time)

    error_context.context("Check disks in guest.", logging.info)
    # re-login in case previous session is expired
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    new_disks_num = int(session.cmd("lsblk -d -n|wc -l", timeout=300))
    logging.info("There are total %d disks after hotplug", new_disks_num)
    if new_disks_num != disks_num:
        logging.warning("Find unmatched disk numbers %d %d", disks_num,
                        new_disks_num)
