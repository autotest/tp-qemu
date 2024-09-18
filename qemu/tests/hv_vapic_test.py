import os
import re
import time

from virttest import data_dir, env_process, error_context, utils_disk
from virttest.qemu_storage import QemuImg

from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Test the hv_vapic flag improvement
    1) Create tmpfs data disk in host
    2) Mount&format the disk in guest, then prepare the fio test
       environment
    3) Boot the guest with all hv flags
    4) Run fio test, record the result's bw value
    5) Shutdown and boot the guest again without hv_vapic flag
    6) Run fio test again, record the result's bw value
    7) Calculate the improvement value of the 2 fio tests,
       then check if it is obvious enough

    param test: the test object
    param params: the test params
    param env: the test env object
    """

    def _create_tmpfs_data_disk():
        """
        Create a tmpfs data disk
        """
        test.log.info("Create tmpfs data disk")
        disk_name_key = params["disk_name_key"]
        tmp_dir = data_dir.get_tmp_dir()
        tmpfs_dir = os.path.join(tmp_dir, "tmpfs")
        if not os.path.isdir(tmpfs_dir):
            os.makedirs(tmpfs_dir)
        params[disk_name_key] = os.path.join(tmpfs_dir, "data")
        tmpfs_image_name = params["tmpfs_image_name"]
        img_param = params.object_params(tmpfs_image_name)
        img = QemuImg(img_param, data_dir.get_data_dir(), tmpfs_image_name)
        img.create(img_param)

    def _format_tmpfs_disk():
        """
        Format the new tmpfs disk in guest

        return: the formatted drive letter of the disk
        """
        test.log.info("Boot the guest to setup tmpfs disk")
        vm, session = _boot_guest_with_cpu_flag(cpu_model_flags)
        test.log.info("Format tmpfs disk")
        disk_size = params["image_size_" + params["tmpfs_image_name"]]
        disk_id = utils_disk.get_windows_disks_index(session, disk_size)[0]
        drive_letter = utils_disk.configure_empty_windows_disk(
            session, disk_id, disk_size
        )[0]
        vm.graceful_shutdown(timeout=timeout)
        return drive_letter

    def _boot_guest_with_cpu_flag(hv_flag):
        """
        Boot the guest, with param cpu_model_flags set to hv_flag

        param hv_flag: the hv flags to set to cpu

        return: the booted vm and a loggined session
        """
        params["cpu_model_flags"] = hv_flag
        params["start_vm"] = "yes"
        vm_name = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        return (vm, session)

    def _run_fio(session, drive_letter):
        """
        First format tmpfs disk to wipe out cache,
        then run fio test, and return the result's bw value

        param session: a session loggined to guest os
        drive_letter: the drive to run the fio job on
        return: the bw value of the running result(bw=xxxB/s)
        """
        bw_search_reg = params["bw_search_reg"]
        test.log.info("Format tmpfs data disk")
        utils_disk.create_filesystem_windows(session, drive_letter, "ntfs")
        test.log.info("Start fio test")
        fio = generate_instance(params, vm, "fio")
        o = fio.run(params["fio_options"] % drive_letter)
        return int(re.search(bw_search_reg, o, re.M).group(1))

    timeout = params.get_numeric("timeout", 360)
    cpu_model_flags = params["cpu_model_flags"]

    error_context.context("Create tmpfs data disk in host", test.log.info)
    _create_tmpfs_data_disk()

    error_context.context("Prepare tmpfs in guest", test.log.info)
    drive_letter = _format_tmpfs_disk()

    error_context.context("Boot guest with all the hv flags")
    vm, session = _boot_guest_with_cpu_flag(cpu_model_flags)
    time.sleep(300)
    error_context.context("Start fio in guest", test.log.info)
    bw_with_hv_vapic = _run_fio(session, drive_letter)

    error_context.context("Shutdown guest and boot without hv_vapnic", test.log.info)
    vm.graceful_shutdown(timeout=timeout)
    cpu_model_flags = cpu_model_flags.replace(",hv_vapic", "")
    vm, session = _boot_guest_with_cpu_flag(cpu_model_flags)
    time.sleep(300)
    error_context.context("Start fio in guest again", test.log.info)
    bw_without_hv_vapic = _run_fio(session, drive_letter)

    error_context.context("Check the improvement of hv_vapic", test.log.info)
    improvement = (float)(bw_with_hv_vapic - bw_without_hv_vapic)
    improvement /= bw_without_hv_vapic
    if improvement < 0.05:
        test.fail(
            "Improvement not above 5%%."
            " bw with hv_vapic: %s,"
            " bw without hv_vapic: %s" % (bw_with_hv_vapic, bw_without_hv_vapic)
        )
