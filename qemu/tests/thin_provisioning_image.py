import os
import re
import time
import logging

from virttest import env_process
from virttest import data_dir
from virttest import gluster
from virttest import qemu_storage
from virttest import utils_disk
from virttest import utils_misc
from avocado.utils import process
from avocado.core import exceptions
from autotest.client.shared import error
from autotest.client.shared import utils
from autotest.client.shared import data_dir as auto_data_dir
from qemu.tests import thin_provisioning



@error.context_aware
def run(test, params, env):
    """
      'thin-provisioning' functions test using local or gluster image:
      1) boot up guest with local/gluster disk
      2) get the block num stat
      3) dd a file
      4) get the block num stat
      5) delete the file
      6) fstrim
      7) get the block num stat
      8) check the block num stat

      :param test: QEMU test object
      :param params: Dictionary with the test parameters
      :param env: Dictionary with test environment.
      """

    def count_block_num(image_disk, gluster_mount_dir=None):
        """
        Get the block num of the disk,when i create a large file in guest,the content needs
        time to be written to the host disk,so when check using stat, you will find the block
        number changes all the time for a period of time, this is related with the host env,
        some machines is much faster,and some machines is slow, i test 3 host machines and finally
        find when i set the wait_time to 12 seconds,it works fine..

        :param image_disk: Image disk name.
        :return: The block number after the status is steady
        """
        wait_time = 20
        while True:
            if params.get("enable_gluster", "no") == "yes":
                image_disk = process.system_output("basename {}".format(image_disk))
                image_disk = os.path.join(gluster_mount_dir, image_disk)
            cmd = "stat {:s}".format(image_disk)
            pattern = r"Blocks:\s(\d+)"
            try:
                block_num = re.search(pattern, process.system_output(cmd)).groups()[0]
                time.sleep(wait_time)
                block_num_after_sec = re.search(pattern, process.system_output(cmd)).groups()[0]
                logging.info(
                    'Disk is not steady yet, block_num: {:s}, block_num_after_{}sec:{:s}'.format(
                        block_num, wait_time, block_num_after_sec))
                if block_num == block_num_after_sec:
                    return block_num
            except:
                error.context("Got block number failed,Please Check.")

    # Destroy all vms to avoid emulated disk marked drity before start test
    thin_provisioning.destroy_vm(env)

    vm_name = params["main_vm"]
    params["start_vm"] = "yes"
    enable_gluster = params.get("enable_gluster", "no")
    base_dir = params.get("images_base_dir", data_dir.get_data_dir())
    error.context("TEST STEP 1: Create test image disk.", logging.info)
    tempdir = ""
    gluster_volume_mount = ""

    if enable_gluster == "yes":
        gluster_volume_mount = gluster.create_gluster_uri(params)
        gluster_volume_mount = gluster_volume_mount.replace(":0", ":")
        gluster_volume_mount = gluster_volume_mount.replace("gluster://", "")
        gluster_volume_mount = gluster_volume_mount.rstrip('/')
        tempdir = auto_data_dir.get_tmp_dir()
        utils_misc.mount(gluster_volume_mount, tempdir, 'glusterfs')

        params["only_disk_enable_gluster"] = "yes"
        params["drive_format_gluster_disk"] = "scsi-hd"
        params["drv_extra_params_gluster_disk"] = "discard=on"
        params["image_name_gluster_disk"] = "gluster_disk"
        params["force_create_image_gluster_disk"] = "no"
        params["image_raw_device_gluster_disk"] = "yes"
        image_file_name = "{}".format(gluster.get_image_filename(
            params, params["image_name_gluster_disk"], params["image_format_gluster_disk"]))
        params["image_name_gluster_disk"] = image_file_name
        cmd = "qemu-img create -f {} {} {}".format(params["image_format_gluster_disk"],
                                                   image_file_name, params["image_size_gluster_disk"])
        try:
            process.system_output(cmd)
        except:
            raise error.TestError("Failed to create disk image in gluster server")
    else:
        params["image_name_local_disk"] = "local_disk"
        params["drive_format_local_disk"] = "scsi-hd"
        params["drv_extra_params_local_disk"] = "discard=on"
        object_params = params.object_params("local_disk")
        object_params["image_name"] = "images/{}".format(params["image_name_local_disk"])
        object_params["image_format"] = params["image_format_local_disk"]
        object_params["image_size"] = params["image_size_local_disk"]
        image = qemu_storage.QemuImg(object_params, base_dir, params["image_name_local_disk"])
        image_file_name = image.create(object_params)[0]
        params["image_name_local_disk"] = os.path.splitext(image_file_name)[0]

    error.context("TEST STEP 2: Boot guest with image disk {:s}".format(image_file_name), logging.info)
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    guest_device_name = thin_provisioning.get_guest_discard_disk(session)
    format_all_disk_cmd = params["format_all_disk_cmd"]
    format_all_disk_cmd = format_all_disk_cmd.replace("DISK1", guest_device_name)
    error.context("TEST STEP 3: Format disk '{:s}' in guest".format(guest_device_name), logging.info)
    session.cmd(format_all_disk_cmd)
    block_num_after_format = count_block_num(image_file_name, tempdir)
    error.context("block_num_after_format: {:s}".format(block_num_after_format), logging.info)

    mount_disk_cmd = params["mount_disk_cmd"]
    error.context("TEST STEP 4: Mount disk to {:s} in guest.".format(mount_disk_cmd), logging.info)
    mount_disk_cmd = mount_disk_cmd.replace("DISK1", guest_device_name)
    session.cmd(mount_disk_cmd)

    error.context("TEST STEP 5: Create a file in the mount directory.", logging.info)
    ddfile = "{:s}/file".format(params.get("mount_point"))
    rewrite_disk_cmd = "dd if=/dev/zero of={:s} bs=1M count=2000".format(ddfile)
    try:
        session.cmd(rewrite_disk_cmd, timeout=timeout)
    except:
        raise error.TestError("Create file in guest failed.")
    block_num_after_dd = count_block_num(image_file_name, tempdir)
    error.context("block_num_after_dd: {:s}".format(block_num_after_dd), logging.info)

    session.cmd("rm -rf %s" % ddfile)
    time.sleep(5)
    error.context("TEST STEP 6: Execute fstrim in guest", logging.info)
    fstrim_cmd = params["fstrim_cmd"]
    session.cmd(fstrim_cmd, timeout=timeout)
    block_num_after_trim = count_block_num(image_file_name, tempdir)
    error.context("block_num_after_trim: {:s}".format(block_num_after_trim), logging.info)
    if params.get("image_format_local_disk") == "qcow2" or params.get("image_format_gluster_disk") == "qcow2":
        if params.get("guest_filesystem") == "ext4":
            if block_num_after_trim != "277520":
                raise exceptions.TestFail("Expect 277520, but we got {:s}".format(block_num_after_trim))
        else:
            if block_num_after_trim != "23944":
                raise exceptions.TestFail("Expect 23944, but we got {:s}".format(block_num_after_trim))
    else:
        if params.get("guest_filesystem") == "ext4":
            if block_num_after_trim != "598504":
                raise exceptions.TestFail("Expect 598504, but we got {:s}".format(block_num_after_trim))
        else:
            if block_num_after_trim != "20704":
                raise exceptions.TestFail("Expect 20704, but we got {:s}".format(block_num_after_trim))

    process.system_output("rm -rf {:s}".format(image_file_name))
    session.close()
    if vm:
        vm.destroy()

    if os.path.exists(tempdir):
        utils_disk.umount(gluster_volume_mount, tempdir)
