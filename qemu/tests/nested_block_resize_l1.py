import re
import time

from avocado.utils import process
from virttest import env_process, error_context
from virttest.utils_misc import get_linux_drive_path

from provider import message_queuing


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU nested block resize test of L1

    1) Boot the vm attach the disk from L1
    2) Run io on the data disk then notify L0
    3) Return status of L2 to host.


    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _on_exit(obj, msg):
        test.log.info("Receive exit msg:%s", msg)
        obj.set_msg_loop(False)
        obj.send_message("exit:0")

    def _on_status(obj, msg):
        test.log.info("Receive status msg:%s", msg)
        vm_status = dict(vm.monitor.get_status())

        test.log.info(str(vm_status["status"]))
        obj.send_message("status-rsp:" + vm_status["status"])
        test.log.info("Finish handle on_status")

    def _get_host_drive_path(did):
        """
        Get drive path in host by drive serial or wwn
        """
        cmd = "for dev_path in `ls -d /sys/block/*`; do "
        cmd += "echo `udevadm info -q property -p $dev_path`; done"
        status, output = process.getstatusoutput(cmd)
        if status != 0:
            return ""
        p = r"DEVNAME=([^\s]+)\s.*(?:ID_SERIAL|ID_SERIAL_SHORT|ID_WWN)=%s" % did
        dev = re.search(p, output, re.M)
        if dev:
            return dev.groups()[0]
        return ""

    # Error contexts are used to give more info on what was
    # going on when one exception happened executing test code.

    pass_path = _get_host_drive_path(params["serial_data_disk"])
    if not pass_path:
        test.fail("Can not find expected disk")
    params["image_name_stg"] = pass_path

    params["start_vm"] = "yes"
    test.log.info(pass_path)

    error_context.context("Boot the main VM", test.log.info)
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    guest_path = get_linux_drive_path(session, params["serial_data_disk"])
    test.log.info(guest_path)

    host = params.get("mq_publisher")
    mq_port = params.get("mq_port", 5000)
    test.log.info("host:%s port:%s", host, mq_port)
    client = message_queuing.MQClient(host, mq_port)
    time.sleep(2)
    cmd_dd = params["cmd_dd"] % guest_path
    error_context.context("Do dd writing test on the data disk.", test.log.info)
    session.sendline(cmd_dd)
    time.sleep(2)

    try:
        client.send_message("resize")
        client.register_msg("status-req", _on_status)
        client.register_msg("exit", _on_exit)
        client.msg_loop(timeout=180)
        test.log.debug("Finish msg_loop")
    except message_queuing.MessageNotFoundError:
        # Notify L1
        client.send_message("exit:1")
        test.fail("Nested block resize can not get expected message.")
    finally:
        client.close()
        test.log.debug("MQ closed")
