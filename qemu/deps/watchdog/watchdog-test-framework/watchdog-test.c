/* watchdog-test framework
 * Copyright (C) 2014-2015 Red Hat Inc.
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <limits.h>
#include <time.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/watchdog.h>

#define WATCHDOG_DEVICE "/dev/watchdog"
#define WATCHDOG_TIMEOUT_DEFAULT 30

#define MIN(a,b) ((a)<(b)?(a):(b))

enum { HELP_OPTION = CHAR_MAX + 1 };

static const char *options = "";
static const struct option long_options[] = {
  { "timeout", 1, 0, 0 },
  { "yes", 0, 0, 0 },
  { 0, 0, 0, 0 }
};

static void
usage (int r)
{
  printf ("usage: watchdog-test [--timeout=TIMEOUT] [--yes]\n");
  exit (r);
}

int
main (int argc, char *argv[])
{
  int watchdog_timeout = WATCHDOG_TIMEOUT_DEFAULT;
  int ping_time;
  int fd;
  int timeout;
  char input[256];
  time_t start_t, t;
  int option_index, c, yes = 0;

  /* Parse the command line. */
  for (;;) {
    c = getopt_long (argc, argv, options, long_options, &option_index);
    if (c == -1) break;

    switch (c) {
    case 0:			/* options which are long only */
      if (strcmp (long_options[option_index].name, "timeout") == 0) {
        if (sscanf (optarg, "%d", &watchdog_timeout) != 1) {
          fprintf (stderr, "%s: invalid --timeout option\n", argv[0]);
          exit (EXIT_FAILURE);
        }
      } else if (strcmp (long_options[option_index].name, "yes") == 0) {
        yes = 1;
      } else {
        fprintf (stderr, "%s: unknown long option: %s (%d)\n",
                 argv[0], long_options[option_index].name, option_index);
        exit (EXIT_FAILURE);
      }
      break;

    case HELP_OPTION:
      usage (EXIT_SUCCESS);

    default:
      usage (EXIT_FAILURE);
    }
  }

  ping_time = MIN (watchdog_timeout * 2, 120);

  setvbuf (stdout, NULL, _IONBF, 0);

  printf ("\n");
  printf ("Welcome to the watchdog test framework.\n");
  printf ("You should read the README file and run this in the guest.\n");
  printf ("DO NOT RUN IT IN THE HOST!\n");
  printf ("\n");
  printf ("The test is as follows:\n");
  printf ("(1) I will set up the watchdog with a %d second timeout.\n",
          watchdog_timeout);
  printf ("(2) I will ping the watchdog for %d seconds.  During this time\n"
          "    the guest should run normally.\n",
          ping_time);
  printf ("(3) I will stop pinging the watchdog and just count up.  If the\n"
          "    virtual watchdog device is set correctly, then the watchdog\n"
          "    action (eg. reboot) should happen around the %d second mark.\n",
          watchdog_timeout);
  printf ("\n");

  if (!yes) {
    printf ("Do you want to start the test?  Type \"yes\" without quotes:\n");

    if (fgets (input, sizeof input, stdin) == NULL ||
        strncmp (input, "yes", 3) != 0) {
      printf ("Exiting the program.\n");
      exit (EXIT_SUCCESS);
    }

    printf ("\n");
  }

  printf ("Setting up the watchdog (%s) with a %d second timeout.\n",
          WATCHDOG_DEVICE, watchdog_timeout);

  sync ();
  fd = open (WATCHDOG_DEVICE, O_WRONLY);
  if (fd == -1) {
    perror (WATCHDOG_DEVICE);
    exit (EXIT_FAILURE);
  }

  timeout = watchdog_timeout;
  if (ioctl (fd, WDIOC_SETTIMEOUT, &timeout) == -1) {
    perror ("ioctl: WDIOC_SETTIMEOUT: error setting timeout");
    exit (EXIT_FAILURE);
  }

  if (ioctl (fd, WDIOC_GETTIMEOUT, &timeout) == -1)
    perror ("ioctl: WDIOC_GETTIMEOUT");
  else {
    printf ("Timeout is set to %d seconds.\n", timeout);
    if (timeout != watchdog_timeout)
      printf ("Note: some watchdog devices don't support setting exact timeout values.\n");
  }

  printf ("\n");
  printf ("Pinging the watchdog for %d seconds ...\n", ping_time);
  printf ("\n");

  time (&start_t);
  for (;;) {
    time (&t);
    if (t - start_t > ping_time)
      break;
    printf ("%d...\n", (int) (t - start_t));

    sync ();

    sleep (3);

    printf ("ping\n");
    if (ioctl (fd, WDIOC_KEEPALIVE, 0) == -1)
      perror ("\nioctl: WDIOC_KEEPALIVE");
  }

  printf ("\n");
  printf ("\n");
  printf ("Stopping pings.\n");
  printf ("The watchdog action should happen at approximately %d second mark.\n",
          watchdog_timeout);
  printf ("\n");

  time (&start_t);
  for (;;) {
    time (&t);
    printf ("%d...\n", (int) (t - start_t));
    sync ();
    sleep (3);
  }

  /*NOTREACHED*/
  exit (EXIT_SUCCESS);
}
