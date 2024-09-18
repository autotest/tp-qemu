from avocado.utils import process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    1) Boot a guest with the specified GIC version
    2) Check the GIC version in the guest

    :param test: QEMU test object.
    :type  test: avocado_vt.test.VirtTest
    :param params: Dictionary with the test parameters.
    :type  params: virttest.utils_params.Params
    :param env: Dictionary with test environment.
    :type  env: virttest.utils_env.Env
    """
    gic_version = params["gic_version"]
    irq_cmd = params["irq_cmd"]
    gic_version = (
        gic_version if gic_version != "host" else process.getoutput(irq_cmd).strip()
    )

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    error_context.context("Get GIC version in the guest", test.log.info)
    guest_gic_version = session.cmd_output(irq_cmd).strip()
    test.log.info("Guest GIC version: %s", guest_gic_version)

    if guest_gic_version != gic_version:
        test.fail(
            f'GIC version mismatch, expected version is "{gic_version}" '
            f'but the guest GIC version is "{guest_gic_version}"'
        )
    test.log.info("GIC version match")
