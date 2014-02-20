from virttest.tests import unattended_install


def run(test, params, env):
    """
    Unattended install test:
    1) Starts a VM with an appropriated setup to start an unattended OS install.
    2) Wait until the install reports to the install watcher its end.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    unattended_install.run(test, params, env)
