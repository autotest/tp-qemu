from avocado.utils import process
from virttest import data_dir
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    Image creation locking should be properly released.
    1. Create raw image and close it after 0.5 sec.
    2. Check there is no lock error of the CML.
    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    lock_test = params["images"]
    root_dir = data_dir.get_data_dir()
    test_image = QemuImg(params.object_params(lock_test), root_dir, lock_test)
    test_filename = test_image.image_filename
    lock_err_info = 'Failed to get "consistent read" lock'
    try:
        process.run(
            "qemu-img create -f raw -o preallocation=full %s 1G & "
            "sleep 0.5;qemu-io -c info -c close -r %s" % (test_filename, test_filename),
            shell=True,
        )
    except process.CmdError as err:
        if lock_err_info in err.result.stderr.decode():
            test.fail("Image lock not released: %s" % err)
        else:
            test.error("Command line failed: %s" % err)
