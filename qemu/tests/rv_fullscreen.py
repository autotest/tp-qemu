"""
rv_fullscreen.py - remote-viewer full screen
                   Testing the remote-viewer --full-screen option
                   If successful, the resolution of the guest will
                   take the resolution of the client.

Requires: connected binaries remote-viewer, Xorg, gnome session

"""

from aexpect import ShellCmdError


def run(test, params, env):
    """
    Tests the --full-screen option
    Positive test: full_screen param = yes, verify guest res = client res
    Negative test: full_screen param= no, verify guest res != client res

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    # Get the parameters needed for the test
    full_screen = params.get("full_screen")
    guest_vm = env.get_vm(params["guest_vm"])
    client_vm = env.get_vm(params["client_vm"])

    guest_vm.verify_alive()
    guest_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360))
    )

    client_vm.verify_alive()
    client_session = client_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360))
    )

    # Get the resolution of the client & guest
    test.log.info("Getting the Resolution on the client")
    client_session.cmd("export DISPLAY=:0.0")

    try:
        client_session.cmd("xrandr | grep '*' >/tmp/res")
        client_res_raw = client_session.cmd("cat /tmp/res|awk '{print $1}'")
        client_res = client_res_raw.split()[0]
    except ShellCmdError:
        test.fail("Could not get guest resolution, xrandr output: %s" % client_res_raw)
    except IndexError:
        test.fail("Could not get guest resolution, xrandr output: %s" % client_res_raw)

    test.log.info("Getting the Resolution on the guest")
    guest_session.cmd("export DISPLAY=:0.0")

    try:
        guest_session.cmd("xrandr | grep '*' >/tmp/res")
        guest_res_raw = guest_session.cmd("cat /tmp/res|awk '{print $1}'")
        guest_res = guest_res_raw.split()[0]
    except ShellCmdError:
        test.fail("Could not get guest resolution, xrandr output: %s" % guest_res_raw)
    except IndexError:
        test.fail("Could not get guest resolution, xrandr output: %s" % guest_res_raw)

    test.log.info("Here's the information I have: ")
    test.log.info("\nClient Resolution: %s", client_res)
    test.log.info("\nGuest Resolution: %s", guest_res)

    # Positive Test, verify the guest takes the resolution of the client
    if full_screen == "yes":
        if client_res == guest_res:
            test.log.info("PASS: Guest resolution is the same as the client")
        else:
            test.fail("Guest resolution differs from the client")
    # Negative Test, verify the resolutions are not equal
    elif full_screen == "no":
        if client_res != guest_res:
            test.log.info("PASS: Guest resolution differs from the client")
        else:
            test.fail("Guest resolution is the same as the client")
    else:
        test.fail("The test setup is incorrect.")

    client_session.close()
    guest_session.close()
