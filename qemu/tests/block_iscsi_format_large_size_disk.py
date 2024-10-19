"""Format large size disk from pass-through lun"""

import time

from avocado.utils import process
from virttest import data_dir, env_process, utils_disk, utils_misc
from virttest.iscsi import Iscsi


def run(test, params, env):
    """
    Format large size disk from pass-through lun.

    Steps:
        1) Create iscsi disk and attach it on host.
        2) Boot vm with pass-through iscsi disk.
        3) Login guest and format the whole disk.
        4) Simple IO on the disk.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _get_window_disk_index_by_wwn(uid):
        cmd = 'powershell -command "get-disk| Where-Object'
        cmd += " {$_.UniqueId -eq '%s'}|select number|FL\"" % uid
        status, output = session.cmd_status_output(cmd)
        if status != 0:
            test.fail("execute command fail: %s" % output)
        output = "".join([s for s in output.splitlines(True) if s.strip()])
        logger.debug(output)
        info = output.split(":")
        if len(info) > 1:
            return info[1].strip()
        test.fail("Not find expected disk ")

    def _set_max_sector(dev):
        if params.get("set_max_sector"):
            cmd = params["cmd_set_max_sector"].format(dev.replace("/dev/", ""))
            process.run(cmd, shell=True)

    def _set_max_segment(dev):
        if params.get("set_max_segment"):
            cmd = params["cmd_get_max_segment"].format(dev.replace("/dev/", ""))
            out = process.getoutput(cmd, shell=True)
            logger.info("run check segment %s,%s", cmd, out)
            params["bus_extra_params_stg1"] = "max_sectors=%s" % out
            return out

    def _get_disk_serial(dev):
        if params.get("serial"):
            return params["serial"]
        cmd = "lsblk -dno wwn %s" % dev
        logger.info("run check serial %s", cmd)
        out = process.getoutput(cmd).replace("0x", "").strip()
        logger.info("serial : %s", out)
        if not out:
            test.error("Can not find serial of device")
        return out

    vm = None
    iscsi = None
    logger = test.log

    timeout = params.get_numeric("timeout", 180)
    clean_cmd = params["clean_cmd"]
    backend_image_name = params["image_name_stg1"]
    guest_cmd = params["guest_cmd"]
    try:
        logger.info("Create iscsi disk.")
        base_dir = data_dir.get_data_dir()
        params["image_size"] = params["emulated_image_size"]
        iscsi = Iscsi.create_iSCSI(params, base_dir)
        iscsi.login()
        dev_name = utils_misc.wait_for(lambda: iscsi.get_device_name(), 60)
        time.sleep(2)
        if not dev_name:
            test.error("Can not get the iSCSI device.")

        serial = _get_disk_serial(dev_name)
        _set_max_sector(dev_name)
        _set_max_segment(dev_name)

        clean_cmd = clean_cmd % dev_name
        logger.info("run clean cmd %s", clean_cmd)
        process.run(clean_cmd, shell=True)

        params["image_name_stg1"] = dev_name
        params["image_raw_device_stg1"] = "yes"
        params["start_vm"] = "yes"
        vm = env.get_vm(params["main_vm"])
        env_process.process(
            test, params, env, env_process.preprocess_image, env_process.preprocess_vm
        )
        session = vm.wait_for_login(timeout=timeout)
        img_size = params.get("image_size_stg1")
        os_type = params["os_type"]
        fstype = params.get("fstype")
        labeltype = params.get("labeltype", "msdos")

        guest_cmd = utils_misc.set_winutils_letter(session, guest_cmd)
        disk = _get_window_disk_index_by_wwn(serial)
        logger.info("Format disk %s", disk)
        utils_disk.update_windows_disk_attributes(session, disk)

        driver = utils_disk.configure_empty_disk(
            session, disk, img_size, os_type, fstype=fstype, labeltype=labeltype
        )[0]
        output_path = driver + ":\\test.dat"
        guest_cmd = guest_cmd.format(output_path)
        logger.info("Start IO: %s", guest_cmd)
        session.cmd(guest_cmd, timeout=360)

    finally:
        logger.info("cleanup")
        if vm and vm.is_alive():
            vm.destroy()
        if iscsi:
            iscsi.cleanup(True)
        params["image_name_stg1"] = backend_image_name
        params["image_raw_device_stg1"] = "no"
