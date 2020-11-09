import logging
import time

from avocado.utils import process

from virttest import error_context
import re
import logging
import random
import re
import string
import tempfile
from math import ceil
# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU 'Hello, world!' test

    1) Boot the main vm, or just grab it if it's already booted.
    2) Echo "Hello, world!" in guest and get the output.
    3) Compare whether the return matches our expectations.
    4) Send a monitor command and log its output.
    5) Verify whether the vm is running through monitor.
    6) Echo "Hello, world!" in the host using shell.
    7) Compare whether the return matches our expectations.
    8) Get a sleep_time parameter from the config file and sleep
       during the specified sleep_time.

    This is a sample QEMU test, so people can get used to some of the test APIs.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _online_disk_windows(session, index, timeout=360):
        """
        Online disk in windows guest.

        :param session: Session object connect to guest.
        :param index: Physical disk index.
        :param timeout: Timeout for cmd execution in seconds.
        :return: The output of cmd
        """

        disk = "disk_" + ''.join(
            random.sample(string.ascii_letters + string.digits, 4))
        online_cmd = "echo select disk %s > " + disk
        online_cmd += " && echo online disk noerr >> " + disk
        online_cmd += " && echo clean >> " + disk
        online_cmd += " && echo attributes disk clear readonly >> " + disk
        online_cmd += " && echo detail disk >> " + disk
        online_cmd += " && diskpart /s " + disk
        online_cmd += " && del /f " + disk
        return session.cmd(online_cmd % index, timeout=timeout)

    def _get_drive_path( image):
        """
        Get the disk name by image serial in guest.

        :param session: Session object connect to guest.
        :param params: params of running ENV.
        :param image: image name of disk in qemu.
        :return: The disk path in guest
        """

        image_params = params.object_params(image)
        os_type = params['os_type']
        extra_params = image_params["blk_extra_params"]
        serial = re.search(r"(serial|wwn)=(\w+)", extra_params, re.M).group(2)
        if os_type == "windows":
            cmd = "wmic diskdrive where SerialNumber='%s' get Index,Name"
            disks = session.cmd_output(cmd % serial)
            info = disks.splitlines()
            if len(info) > 1:
                attr = info[1].split()
                _online_disk_windows(session, attr[0])
                print(attr[1])
                return attr[1]

        return get_linux_drive_path(session, serial)

    def _parse_eta_data(output):
        """parse read/write iops """
        print(output)
        if len(output.split("]["))<4:
            return 0
        data = output.split("][")[-2].split(" ")[0]
        if len(data.split("/")) > 1:  # windows
            rw_data = data.split("/")
            return int(rw_data[0]) + int(rw_data[1])
        else:
            if data.find(",") == -1:  # read/write
                val = int(data.split("=")[1])
                # if data.find("r=") == -1:
                #     return 0,val
                return val
            else:
                rw_data = data.split(",")
                read_data = int(rw_data[0].split("=")[1])
                write_data = int(rw_data[1].split("=")[1])
                return read_data + write_data
    # Error contexts are used to give more info on what was
    # going on when one exception happened executing test code.
    error_context.context("Get the main VM", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    # Each test has a params dict, with lots of
    # key = value pairs. Values are always strings
    # In this case, we'll convert login_timeout to int
    timeout = int(params.get("login_timeout", 360))
    # This represents an SSH session. You can end it calling
    # session.close(), but you don't need to since the framework
    # takes care of closing all sessions that were opened by a test.
    session = vm.wait_for_login(timeout=timeout)

    _get_drive_path("stg0")
    # Send command to the guest, using session command.
    error_context.context("Echo 'Hello, world!' in guest and get the output",
                          logging.info)
    # Here, timeout was passed explicitly to show it can be tweaked
    cmd = "\"C:\Program Files (x86)\\fio\\fio\\fio.exe\" --direct=1 --name=test --iodepth=1 --thread --eta=always --eta-newline=3 --rw=randrw --bs=4096 --size=1g --runtime=15 --filename=\\.\PHYSICALDRIVE1 --output=stg1 > stg1.tpm && type stg1.tmp"
    output = session.cmd(cmd, timeout=60)
    print(output)
    # cmd = "fio --direct=1 --name=test --iodepth=1 --thread --eta=always --eta-interval=2 --eta-newline=2  --rw=read --bs=4096 --runtime=10  --filename=/dev/sdb --output=stg1 > stg1.tmp"
    # cmd = "echo 'fio --direct=1 --name=test --iodepth=1 --thread --eta=always --eta-interval=3 --eta-newline=3 --rw=randrw --bs=4096 --runtime=10  --filename=/dev/sdb --output=stg1'>x.sh;chmod 755 x.sh"
    # output = session.sendline(guest_cmd)

    # time.sleep(20)
    # vm.copy_files_from("stg1.tmp","/tmp/")
    # # if params.get("os_type") == 'linux':
    # cmd= "cat /tmp/stg1.tmp"
    # # cmd = "echo 'hel'"
    # # cmd= "cat stg1.tmp"
    # # output = session.cmd(cmd, timeout=60)
    # output = process.system_output(cmd, shell=True).decode()
    # output=output.splitlines()
    logging.info("Host cmd output '%s'", output)
    for o in output.splitlines():
        logging.info("%d", _parse_eta_data(o))

    # guest_cmd_output = session.cmd(cmd, timeout=60)
    # # The output will contain a newline, so strip()
    # # it for the purposes of pretty printing and comparison
    # guest_cmd_output = guest_cmd_output.strip()
    # logging.info("Guest cmd output: '%s'", guest_cmd_output)
    #
    # # Here, we will fail a test if the guest outputs something unexpected
    # if guest_cmd_output != 'Hello, world!':
    #     test.fail("Unexpected output from guest")
    #
    # # Send command to the guest, using monitor command.
    # error_context.context("Send a monitor command", logging.info)
    #
    # monitor_cmd_ouput = vm.monitor.info("status")
    # logging.info("Monitor returns '%s'", monitor_cmd_ouput)
    #
    # # Verify whether the VM is running. This will throw an exception in case
    # # it is not running, failing the test as well.
    # vm.verify_status("running")
    #
    # # Send command to host
    # error_context.context("Echo 'Hello, world!' in the host using shell",
    #                       logging.info)
    # # If the command fails, it will raise a process.CmdError exception
    # host_cmd_output = process.system_output("echo 'Hello, world!'", shell=True)
    # logging.info("Host cmd output '%s'", host_cmd_output)
    #
    # # Here, we will fail a test if the host outputs something unexpected
    # if host_cmd_output != 'Hello, world!':
    #     test.fail("Unexpected output from guest")
    #
    # # An example of getting a required parameter from the config file
    # error_context.context("Get a required parameter from the config file",
    #                       logging.info)
    # sleep_time = int(params["sleep_time"])
    # logging.info("Sleep for '%d' seconds", sleep_time)
    # time.sleep(sleep_time)
