"""Verify Maximum transfer length and max_sector_kb in guest"""

import copy
import json
import time
from os.path import basename

from avocado.utils import process
from virttest import data_dir, env_process, utils_misc
from virttest.iscsi import Iscsi
from virttest.utils_misc import get_linux_drive_path


def run(test, params, env):
    """
    Verify Maximum transfer length and max_sector_kb in guest.

    Steps:
        1) Get max_sector_kb and segments of host target device.
        2) Pass-through host target device and Boot VM.
        3) Login guest and check the max_sector_kb and Maximum transfer length.
        4) Execute IO Check the VM still running.(optional)

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _verify_transfer_info(host_info, guest_info):
        errmsg = "The guest get unexpected transfer %s" % guest_info
        if guest_info["sectors_kb"] > host_info["sectors_kb"]:
            test.fail(errmsg)
        min_host = min(host_info["sectors_kb"], host_info["segments"] * 4)
        logger.debug(min_host)
        if guest_info["sectors_kb"] > min_host:
            test.fail(errmsg)
        if guest_info["tran_length"] > guest_info["sectors_kb"] * 2:
            test.fail(errmsg)

    def _get_target_devices(trans_type, size=None):
        devs = []
        cond = '$2=="%s"' % trans_type
        if size:
            cond += ' && $3=="%s"' % size
        cmd = "lsblk -Spo 'NAME,TRAN,SIZE' |awk '{if(%s) print $1}'" % cond
        logger.debug(cmd)
        status, output = process.getstatusoutput(cmd)
        devs_str = output.strip().replace("\n", " ")
        if devs_str:
            cmd = "lsblk -Jpo 'NAME,HCTL,SERIAL,TRAN,FSTYPE,WWN' %s" % devs_str
            status, output = process.getstatusoutput(cmd)
            devs = copy.deepcopy(json.loads(output)["blockdevices"])

        return devs

    def _run_cmd(cmd, conn=None):
        if conn:
            return conn.cmd_output(cmd)
        else:
            return process.getoutput(cmd)

    def _get_transfer_parameters(dev, conn=None):
        dev = basename(dev)
        info = {"tran_length": 0, "sectors_kb": 0, "segments": 0}
        cmd = params["get_tran_length_cmd"] % dev
        output = _run_cmd(cmd, conn)
        logger.debug(output)
        info["tran_length"] = int(output, 0)
        cmd = params["get_tran_params_cmd"] % dev
        output = _run_cmd(cmd, conn).split()
        logger.debug(output)
        info["sectors_kb"] = int(output[0], 0)
        info["segments"] = int(output[1], 0)
        return info

    vm = None
    iscsi = None
    logger = test.log
    set_max_sector_cmd = params.get("set_max_sector_cmd")

    try:
        tran_type = params["tran_type"]
        params["image_size"] = params.get("emulated_image_size", "")
        if tran_type == "iscsi":
            logger.debug("Create iscsi disk.")
            base_dir = data_dir.get_data_dir()
            iscsi = Iscsi.create_iSCSI(params, base_dir)
            iscsi.login()
            dev_name = utils_misc.wait_for(lambda: iscsi.get_device_name(), 60)
            if not dev_name:
                test.error("Can not get the iSCSI device.")
            logger.debug(dev_name)
            time.sleep(2)
            logger.debug(_run_cmd("lsblk -JO %s" % dev_name))

        target_devs = _get_target_devices(tran_type, params["image_size"])
        if not len(target_devs):
            if tran_type == "fc":
                test.cancel("No FC device:%s" % params["image_size"])
            else:
                test.error("No ISCSI device:%s" % params["image_size"])

        target_dev = target_devs[0]
        logger.debug(target_dev)
        dev_name = basename(target_dev["name"])
        if set_max_sector_cmd:
            logger.debug("Set max_sectors_kb of %s ", dev_name)
            set_max_sector_cmd = set_max_sector_cmd % dev_name
            _run_cmd(set_max_sector_cmd)

        vm = env.get_vm(params["main_vm"])
        timeout = float(params.get("timeout", 240))
        guest_cmd = params["guest_cmd"]

        params["image_name_stg1"] = target_dev["name"]
        if target_dev["fstype"] == "mpath_member" and "children" in target_dev:
            params["image_name_stg1"] = target_dev["children"][0]["name"]

        disk_wwn = target_dev["wwn"]
        if disk_wwn:
            disk_wwn = disk_wwn.replace("0x", "")
        else:
            test.fail("Why no wwn")

        logger.debug("Get host transfer info of %s ", dev_name)
        host_tran_info = _get_transfer_parameters(dev_name)
        params["start_vm"] = "yes"
        env_process.process(
            test, params, env, env_process.preprocess_image, env_process.preprocess_vm
        )

        session = vm.wait_for_login(timeout=timeout)

        target_path = get_linux_drive_path(session, disk_wwn)

        if not target_path:
            test.fail("Can not find device in guest.")

        logger.debug("Get guest transfer info of %s", target_path)
        guest_tran_info = _get_transfer_parameters(target_path, session)
        logger.debug("Verify transfer info of %s", target_path)
        _verify_transfer_info(host_tran_info, guest_tran_info)
        guest_cmd = guest_cmd % target_path
        logger.debug("Start IO: %s", guest_cmd)
        session.cmd(guest_cmd, timeout=360)
        vm.monitor.verify_status("running")

    finally:
        logger.info("Cleanup")
        if vm and vm.is_alive():
            vm.destroy()
        if iscsi:
            iscsi.cleanup()
