from avocado.utils import process
from virttest import env_process, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    KVM Seabios bin file test:
    1) Get available bin files
    2) Get supported machine types
    3) Check bin file in use

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    bin_dict = {
        "rhel6": "bios.bin",
        "rhel7": "bios-256k.bin",
        "rhel8": "bios-256k.bin",
        "rhel9": "bios-256k.bin",
        "rhel10": "bios-256k.bin",
        "4.2": "bios-256k.bin",
        "2.11": "bios-256k.bin",
    }

    error_context.context("Get available bin files", test.log.info)
    output = process.system_output("ls /usr/share/seabios", shell=True).decode()
    bin_file_skip = params.get("bin_file_skip", "")
    for value in bin_dict.values():
        if value not in output and value != bin_file_skip:
            test.fail("%s is not available" % value)

    error_context.context("Get supported machine types", test.log.info)
    qemu_binary = utils_misc.get_qemu_binary(params)
    machine_type_cmd = qemu_binary + " -machine help | awk '{ print $1 }'"
    output = process.system_output(machine_type_cmd, shell=True).decode()
    machine_types = output.splitlines()
    machine_type_remove = params["machine_type_remove"].split()
    for i in machine_type_remove:
        machine_types.remove(i)
    test.log.info(machine_types)

    for machine in machine_types:
        error_context.context(
            "Check bin file with machine type: %s" % machine, test.log.info
        )
        for key in bin_dict:
            if key in machine:
                bin_file = bin_dict[key]
                break
        else:
            test.error("Uncertain which bin file in use for machine type: %s" % machine)

        params["machine_type"] = machine
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        vm = env.get_vm(params["main_vm"])
        info_roms = vm.monitor.info("roms")
        if bin_file not in info_roms:
            test.fail(
                "Checking bin file fails with %s, info roms: %s" % (machine, info_roms)
            )
        vm.destroy()
