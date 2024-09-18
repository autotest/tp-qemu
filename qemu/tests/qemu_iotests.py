import os

from avocado.utils import git, process
from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Fetch from git and run qemu-iotests using the qemu binaries under test.

    1) Fetch qemu-io from git
    3) Run test for the file format detected
    4) Report any errors found to test

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    # First, let's get qemu-io
    std = "http://git.kernel.org/pub/scm/virt/kvm/qemu-kvm.git"
    uri = params.get("qemu_io_uri", std)
    branch = params.get("qemu_io_branch", "master")
    lbranch = params.get("qemu_io_lbranch", "master")
    commit = params.get("qemu_io_commit", None)
    base_uri = params.get("qemu_io_base_uri", None)
    iotests_dir = params.get("qemu_iotests_dir", "tests/qemu-iotests")
    destination_dir = os.path.join(test.workdir, "qemu_io_tests")
    git.get_repo(
        uri=uri,
        branch=branch,
        lbranch=lbranch,
        commit=commit,
        destination_dir=destination_dir,
        base_uri=base_uri,
    )

    # Then, set the qemu paths for the use of the testsuite
    os.environ["QEMU_PROG"] = utils_misc.get_qemu_binary(params)
    os.environ["QEMU_IMG_PROG"] = utils_misc.get_qemu_img_binary(params)
    os.environ["QEMU_IO_PROG"] = utils_misc.get_qemu_io_binary(params)

    # qemu-iotests has merged into tests/qemu_iotests folder
    os.chdir(os.path.join(destination_dir, iotests_dir))
    image_format = params["qemu_io_image_format"]
    extra_options = params.get("qemu_io_extra_options", "")

    cmd = "./check"
    if extra_options:
        cmd += extra_options

    error_context.context("running qemu-iotests for image format %s" % image_format)
    process.system("%s -%s" % (cmd, image_format), shell=True)
