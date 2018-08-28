import re
import logging

from avocado.utils import process

from virttest import error_context
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    QEMU support options check test

    Test Step:
        1) Get qemu support device options
        2) Check whether qemu have output

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def get_qemu_support_device(qemu_binary):
        """
        Get qemu support device list
        """
        support_device = process.system_output("%s -device ? 2>&1"
                                               % qemu_binary, timeout=10,
                                               ignore_status=True, shell=True)
        if not support_device:
            test.cancel("Can not get qemu support device list")
        device_list = re.findall(r'name\s+"(.*)",', support_device)
        device_list_alias = re.findall(r'alias\s+"(.*?)"', support_device)
        device_list.extend(device_list_alias)
        return device_list

    def get_device_option(qemu_binary, device_name):
        """
        Get qemu device 'device_name' support options
        """
        if device_name not in get_qemu_support_device(qemu_binary):
            err_msg = "Oops, Your qemu version doesn't support devic '%s', "
            err_msg += "make sure you have inputted a correct device name"
            test.cancel(err_msg % device_name)
        device_support_option = process.run("%s -device %s,? 2>&1" %
                                            (qemu_binary, device_name),
                                            timeout=10,
                                            ignore_status=True, shell=True)
        if device_support_option.exit_status:
            test.error("Oops, output status is wrong")
        if not re.findall(r"%s\.(.*)=(.*)" % device_name,
                          device_support_option.stdout):
            test.fail("Qemu option check Failed")
        logging.info("Qemu options check successful. output is:\n%s" %
                     device_support_option.stdout)

    device_name = params.get("device_name")
    qemu_binary = utils_misc.get_qemu_binary(params)

    error_context.context("Get qemu support %s device options" % device_name,
                          logging.info)
    get_device_option(qemu_binary, device_name)
