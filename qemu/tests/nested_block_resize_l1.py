import logging
import time

from virttest import error_context
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
        logging.info("Receive exit msg:%s", msg)
        obj.set_msg_loop(False)
        obj.send_message("exit:0")

    def _on_status(obj, msg):
        logging.info("Receive status msg:%s", msg)
        vm_status = dict(vm.monitor.get_status())

        logging.info(str(vm_status['status']))
        obj.send_message("status-rsp:" + vm_status['status'])
        logging.info("Finish handle on_status")

    # Error contexts are used to give more info on what was
    # going on when one exception happened executing test code.
    error_context.context("Get the main VM", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    host = params.get("mq_publisher")
    mq_port = params.get("mq_port", 5000)
    logging.info("host:{} port:{}".format(host, mq_port))
    client = message_queuing.MQClient(host, mq_port)
    time.sleep(2)
    cmd_dd = params["cmd_dd"]
    error_context.context('Do dd writing test on the data disk.',
                          logging.info)
    session.sendline(cmd_dd)
    time.sleep(2)

    try:
        client.send_message("resize")
        client.register_msg("status-req", _on_status)
        client.register_msg("exit", _on_exit)
        client.msg_loop(timeout=180)
        logging.debug("Finish msg_loop")
    except message_queuing.MessageNotFoundError:
        # Notify L1
        client.send_message("exit:1")
        test.fail("Nested block resize can not get expected message.")
    finally:
        client.close()
        logging.debug("MQ closed")
