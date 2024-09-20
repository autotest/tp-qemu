import re

from virttest import env_process, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    boot with different machine type:
    1) get supported machine type
    2) boot guest with different machine types

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Get supported machine type", test.log.info)
    qemu_binary = utils_misc.get_qemu_binary(params)
    machine_types = []
    machine_type_mapping = {
        "pc": ["i440FX", "RHEL 6"],
        "q35": ["Q35"],
        "pseries": ["pSeries"],
        "arm64-pci:virt": ["ARM"],
        "arm64-mmio:virt": ["ARM"],
        "s390-ccw-virtio": ["S390"],
    }
    for m_type, s_name in zip(*utils_misc.get_support_machine_type(qemu_binary)[:2]):
        for item in machine_type_mapping[params["machine_type"]]:
            if item in s_name:
                if "arm64" in params["machine_type"]:
                    m_type = re.sub(r"(?<=:)\w+", m_type, params["machine_type"])
                machine_types.append(m_type)
    if not machine_types:
        test.fail("Failed to get machine types")
    else:
        test.log.info(
            "Actual supported machine types are: %s", ", ".join(map(str, machine_types))
        )

        for m_type in machine_types:
            params["machine_type"] = m_type
            params["start_vm"] = "yes"
            vm_name = params["main_vm"]
            error_context.context(
                "Start vm with machine type '%s'" % m_type, test.log.info
            )
            env_process.preprocess(test, params, env)
            vm = env.get_vm(vm_name)
            vm.verify_alive()
            timeout = int(params.get("login_timeout", 360))
            session = vm.wait_for_login(timeout=timeout)
            if not session.is_responsive():
                session.close()
                test.fail("Start vm with machine type:%s fail" % m_type)

            session.close()
            error_context.context(
                "Quit guest and check the process quit normally", test.log.info
            )
            vm.destroy(gracefully=False)
