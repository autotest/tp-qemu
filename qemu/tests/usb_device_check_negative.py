from virttest import env_process, error_context, virt_vm

from qemu.tests.usb_common import parse_usb_topology


@error_context.context_aware
def run(test, params, env):
    """
    The usb devices negative test

    1) Boot guest with invalid usb devices
    2) Verify QEMU error info

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    # parse the usb topology from cfg
    parse_usb_topology(params)
    test.log.info("starting vm according to the usb topology")
    error_info = params["error_info"]
    error_context.context(
        ("verify [%s] is reported by QEMU..." % error_info), test.log.info
    )
    try:
        env_process.process(
            test, params, env, env_process.preprocess_image, env_process.preprocess_vm
        )
    except virt_vm.VMCreateError as e:
        if error_info not in e.output:
            test.fail("%s is not reported by QEMU" % error_info)
