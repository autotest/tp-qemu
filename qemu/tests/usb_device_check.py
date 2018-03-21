import logging

from virttest import env_process
from virttest import error_context
from qemu.tests.usb_common import (parse_usb_topology,
                                   collect_usb_dev,
                                   verify_usb_device_in_monitor_qtree,
                                   verify_usb_device_in_guest)


@error_context.context_aware
def run(test, params, env):
    """
    Check the usb devices.

    1) Boot up guest with usb devices
    2) verify usb devices in monitor
    3) verify usb devices in guest

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    def _check_test_step_result(result, output):
        if result:
            logging.info(output)
        else:
            test.fail(output)

    # parse the usb topology from cfg
    parsed_devs = parse_usb_topology(params)

    logging.info("starting vm according to the usb topology")
    env_process.process(test, params, env,
                        env_process.preprocess_image,
                        env_process.preprocess_vm)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    # collect usb dev information for qemu check
    devs = collect_usb_dev(params, vm, parsed_devs, "for_qemu")

    error_context.context("verify usb devices information in qemu...",
                          logging.info)
    result, output = verify_usb_device_in_monitor_qtree(vm, devs)
    _check_test_step_result(result, output)

    # collect usb dev information for guest check
    devs = collect_usb_dev(params, vm, parsed_devs, "for_guest")
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    error_context.context("verify usb devices information in guest...",
                          logging.info)
    result, output = verify_usb_device_in_guest(params, session, devs)
    _check_test_step_result(result, output)

    session.close()
