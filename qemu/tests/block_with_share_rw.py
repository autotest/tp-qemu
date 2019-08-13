import logging

from virttest import error_context
from virttest import env_process
from virttest import virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    Test the scsi device with "share-rw" option.

    Steps:
      1. Boot up a guest with a data disk which image format is raw and
         "share-rw" option is "off" or "on".
      2. Run another vm with the data images:
        2.1 Failed to execute the qemu commands due to fail to get "write" lock
            with "share-rw=off"
        2.2 Could execute the qemu commands with "share-rw=on".
      3. Repeat step 1~2 with the drive format is "scsi-block" and "scsi-generic".

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    msgs = ['"write" lock', 'Is another process using the image']
    vm1 = env.get_vm(params["main_vm"])
    vm1.verify_alive()
    vm1.wait_for_login(timeout=360)

    try:
        error_context.context('Start another vm with the data image.', logging.info)
        params['images'] = params['images'].split()[-1]
        env_process.preprocess_vm(test, params, env, "avocado-vt-vm2")
        vm2 = env.get_vm("avocado-vt-vm2")
        vm2.verify_alive()
    except virt_vm.VMCreateError as e:
        if params['share_rw'] == 'off':
            if not all(msg in str(e) for msg in msgs):
                test.fail("Image lock information is not as expected.")
        else:
            test.error(str(e))
    else:
        vm2.destroy(False, False)
