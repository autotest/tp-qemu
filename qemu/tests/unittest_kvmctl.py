import os

from avocado.utils import process


def run(test, params, env):
    """
    This is kvm userspace unit test, use kvm test harness kvmctl load binary
    test case file to test various functions of the kvm kernel module.
    The output of all unit tests can be found in the test result dir.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    case = params["case"]
    workdir = params.get("workdir", test.workdir)
    unit_dir = os.path.join(workdir, "kvm_userspace", "kvm", "user")
    if not os.path.isdir(unit_dir):
        os.makedirs(unit_dir)
    os.chdir(unit_dir)

    cmd = "./kvmctl test/x86/bootstrap test/x86/%s.flat" % case
    try:
        results = process.system_output(cmd, shell=True)
    except process.CmdError:
        test.fail("Unit test %s failed" % case)

    result_file = os.path.join(test.resultsdir, case)
    with open(result_file, "w") as file:
        file.write(results)
