import logging

from virttest import utils_test
from virttest import env_process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    [pci-bridge]Check stress when 31 block devices attached to 1 pci-bridge, this case will:
    1) Attach one pci-bridge to guest.
    2) Create 31 disks to this pci-bridge.
    3) Start the guest.
    4) Check 'info block'.
    5) Read and write data on disks under pci bridge.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Modify params!", logging.info)
    image_parent_bus = params.get("image_parent_bus")
    image_num = int(params.get("image_num", 0))
    if image_num != 0:
        for index in xrange(image_num):
            image = "stg%s" % index
            params["images"] = ' '.join([params["images"], image])
            params["disk_pci_bus_%s" % image] = image_parent_bus
            params["image_name_%s" % image] = "images/%s" % image
            params["image_size_%s" % image] = "100M"
            params["force_create_image_%s" % image] = "yes"
            params["remove_image_%s" % image] = "yes"
            params["blk_extra_params_%s" % image] = "serial=TARGET_DISK%s" % index

    env_process.process_images(env_process.preprocess_image, test, params)
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    error_context.context("Get the main VM!", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    error_context.context("Check 'info block'!", logging.info)
    monitor_info_block = vm.monitor.info_block(False)
    if image_num + 1 != len(monitor_info_block.keys()):
        raise error.TestFail("Check 'info block' failed!")
    logging.info("Check 'info block' succeed!")

    error_context.context("Read and write data on all disks!", logging.info)
    sub_test_type = params.get("sub_test_type", "dd_test")
    images = params["images"]
    images = images.split()
    images.pop(0)
    for image in images:
        if params.get("dd_if") == "ZERO":
            params["dd_of"] = image
        else:
            params["dd_if"] = image
        utils_test.run_virt_sub_test(test, params, env, sub_test_type)

    logging.info("Read and write data on all disks succeed!")
    session.close()
