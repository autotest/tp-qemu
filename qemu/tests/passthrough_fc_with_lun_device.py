"""Pass-through fc device as lun device io test"""

import copy
import json
import random
import string
import time

from avocado.utils import process
from virttest import env_process, error_context, utils_disk, utils_misc, utils_test
from virttest.utils_disk import configure_empty_disk
from virttest.utils_misc import get_linux_drive_path


@error_context.context_aware
def run(test, params, env):
    """
    Test simple io on FC device pass-through to guest as lun device.

    Step:
     1. Find FC device on host.
     2. Boot a guest with FC disk as scsi-block device for guest.
     3. Access guest then do io on the data disk.
     4. Check vm status.
     5. repeat step 2-4 but as scsi-generic
    """

    def _clean_disk_windows(index):
        tmp_file = "disk_" + "".join(
            random.sample(string.ascii_letters + string.digits, 4)
        )
        online_cmd = "echo select disk %s > " + tmp_file
        online_cmd += " && echo clean >> " + tmp_file
        online_cmd += " && echo rescan >> " + tmp_file
        online_cmd += " && echo detail disk >> " + tmp_file
        online_cmd += " && diskpart /s " + tmp_file
        online_cmd += " && del /f " + tmp_file
        return session.cmd(online_cmd % index, timeout=timeout)

    def _get_window_disk_index_by_wwn(uid):
        cmd = 'powershell -command "get-disk| Where-Object'
        cmd += " {$_.UniqueId -eq '%s'}|select number|FL\"" % uid
        status, output = session.cmd_status_output(cmd)
        if status != 0:
            test.fail("execute command fail: %s" % output)
        output = "".join([s for s in output.splitlines(True) if s.strip()])
        test.log.debug(output)
        info = output.split(":")
        if len(info) > 1:
            return info[1].strip()
        test.fail("Not find expected disk ")

    def _get_fc_devices():
        devs = []
        cmd = "lsblk -Spo 'NAME,TRAN' |awk '{if($2==\"fc\") print $1}'"
        status, output = process.getstatusoutput(cmd)
        devs_str = output.strip().replace("\n", " ")
        if devs_str:
            cmd = "lsblk -Jpo 'NAME,HCTL,SERIAL,TRAN,FSTYPE,WWN' %s" % devs_str
            status, output = process.getstatusoutput(cmd)
            devs = copy.deepcopy(json.loads(output)["blockdevices"])

        for dev in devs:
            cmd = "lsscsi -gb %s|awk '{print $3}'" % dev["hctl"]
            status, output = process.getstatusoutput(cmd)
            dev["sg_dev"] = output
        test.log.debug(devs)
        return devs

    fc_devs = _get_fc_devices()
    if not len(fc_devs):
        test.cancel("No FC device")
    fc_dev = fc_devs[0]
    test.log.debug(fc_dev)

    vm = env.get_vm(params["main_vm"])
    timeout = float(params.get("timeout", 240))
    drive_type = params.get("drive_type")
    os_type = params["os_type"]
    driver_name = params.get("driver_name")
    guest_cmd = params["guest_cmd"]
    clean_cmd = params["clean_cmd"]

    if drive_type == "scsi_block":
        params["image_name_stg0"] = fc_dev["name"]
        if fc_dev["fstype"] == "mpath_member" and "children" in fc_dev:
            params["image_name_stg0"] = fc_dev["children"][0]["name"]
    else:
        params["image_name_stg0"] = fc_dev["sg_dev"]

    clean_cmd = clean_cmd % params["image_name_stg0"]
    error_context.context("run clean cmd %s" % clean_cmd, test.log.info)
    process.getstatusoutput(clean_cmd)

    params["start_vm"] = "yes"
    env_process.process(
        test, params, env, env_process.preprocess_image, env_process.preprocess_vm
    )

    session = vm.wait_for_login(timeout=timeout)

    disk_wwn = fc_dev["wwn"]
    disk_wwn = disk_wwn.replace("0x", "")
    if os_type == "windows" and driver_name:
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name, timeout
        )

    if os_type == "windows":
        part_size = params["part_size"]
        guest_cmd = utils_misc.set_winutils_letter(session, guest_cmd)
        did = _get_window_disk_index_by_wwn(disk_wwn)
        utils_disk.update_windows_disk_attributes(session, did)
        test.log.info("Clean partition disk:%s", did)
        _clean_disk_windows(did)
        try:
            driver = configure_empty_disk(session, did, part_size, os_type)[0]
        except Exception as err:
            test.log.warning("configure_empty_disk again due to:%s", err)
            time.sleep(10)
            _clean_disk_windows(did)
            driver = configure_empty_disk(session, did, part_size, os_type)[0]
            test.log.debug("configure_empty_disk over")
        output_path = driver + ":\\test.dat"
    else:
        output_path = get_linux_drive_path(session, disk_wwn)

    if not output_path:
        test.fail("Can not get output file path in guest.")

    test.log.debug("Get output file path %s", output_path)
    guest_cmd = guest_cmd.format(output_path)

    error_context.context("Start io test...", test.log.info)
    session.cmd(guest_cmd, timeout=360)
    if not vm.monitor.verify_status("running"):
        test.fail("Guest not run after dd")
