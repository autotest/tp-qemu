import os
import re
import time
import logging

from virttest import data_dir
from virttest import env_process
from avocado.utils import process
from avocado.core import exceptions
from autotest.client.shared import error
from qemu.tests import thin_provisioning


@error.context_aware
def run(test, params, env):
    """
      'thin-provisioning' functions test using sg_utils:
      1) Boot up the guest with the scsi disk
      2) using sg_utils to do some test
      3) In guest, check the sha1 value of the guest disk
      4) In host, check the sha1 value of the disk image

      :param test: QEMU test object
      :param params: Dictionary with the test parameters
      :param env: Dictionary with test environment.
      """

    def get_excution_time(session, cmd):
        """
          This function is used to measure the real execution time of
          the command in guest through shell command "time".

          :param session: Guest session
          :param cmd: Commands to execute
          :return: The real execution time
        """
        out = session.cmd_output(cmd)
        try:
            return float(re.search(r"real\s+\dm(.*)s", out).group(1))
        except:
            exceptions.TestError("Unable to read realtime, cmd output: %s" % out)

    def run_sg_utils(disk_name, session):
        """
          This function is used do to some test on the disk using sg_utils package.

          :param disk_name: The Guest disk name
          :param session: Guest Session
          :return: None
        """
        yesfile = "/home/buf"
        cmd = """yes | head -n2048 > {0};"""
        cmd += "sg_write_same --in {0} --num=32 --lba=80 {1};"
        cmd += "sg_write_same --in /dev/zero --num=96 --lba=0 {1};"
        cmd += "sg_write_same -U --in /dev/zero --num=16 --lba=0 {1};"
        cmd = cmd.format(yesfile, disk_name)
        session.cmd(cmd)

        fetch_data_from_file = "sg_write_same --in {:s} --num=65536 --lba=131074 {:s}".format(yesfile, disk_name)
        fetch_data_from_file = "(time {:s})".format(fetch_data_from_file)
        realtime1 = get_excution_time(session, fetch_data_from_file)
        logging.info("The real execution time of the command is:{:f}".format(realtime1))
        if params.get("disk_type") == "scsi_debug":
            bitmap = thin_provisioning.get_allocation_bitmap()
            logging.debug("Block allocation bitmap is: {}".format(bitmap))
        else:
            output = process.system_output("qemu-img map --output=json {:s}".format(disk_name))
            logging.debug("json map: {}".format(output))

        time.sleep(0.1)
        fetch_data_from_zero_device = "sg_write_same --in /dev/zero --num=65534 --lba=196608 {:s}".format(disk_name)
        fetch_data_from_zero_device = "(time {:s})".format(fetch_data_from_zero_device)
        realtime2 = get_excution_time(session, fetch_data_from_zero_device)
        logging.info("The real execution time of the command is {:f}".format(realtime2))
        out3 = session.cmd_output("sg_write_same --in /dev/zero --num=0 --lba=128 {:s}".format(disk_name))
        logging.debug(out3)
        if re.search(r"bad field in Write same", out3) is None:
            raise exceptions.TestFail("sg_write_same command fails. output is {}".format(out3))
        if realtime2 > realtime1:
            raise exceptions.TestFail("time used is much longger")

    thin_provisioning.destroy_vm(env)
    if params.get("disk_type") == "scsi_debug":
        disk_name = thin_provisioning.get_scsi_disk()[1]
        params["image_name_image_test"] = disk_name
    else:
        disk_name = os.path.join(data_dir.get_data_dir(), params.get("image_name_image_test"))
        disk_name = "{:s}.raw".format(disk_name)
    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    guest_disk_name = thin_provisioning.get_scsi_disk(session)[1]
    run_sg_utils(guest_disk_name, session)
    guest_sha1 = session.cmd_output("sha1sum {:s}".format(guest_disk_name)).split()[0]
    host_sha1 = process.system_output("sha1sum {:s}".format(disk_name)).split()[0]

    if guest_sha1 != host_sha1:
        raise exceptions.TestFail("after sg_writesame, image hash value becomes different between guest and host ")

    session.close()
    if vm:
        vm.destroy()
