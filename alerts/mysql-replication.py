#!/usr/bin/env python

from checks import MySQLReplicationCheck
import sh
import re


class Check(MySQLReplicationCheck):

    # We name our db nodes like 'label-db-\d\d'
    host_pattern = re.compile(r'-db-\d+\b', re.IGNORECASE)

    def is_master(self):
        """
        We add an entry in /etc/hosts pointing the service net IP to the name 'db-master',
        if the current host is currently the master in the replica set. Adjust to taste.
        """

        # get the service net IP from ifconfig
        (status, stdout, stderr) = self.shell(sh.ifconfig, 'eth2')
        if status != 0:
            raise Exception("Could not get network configuration for eth2: %s" % stderr)

        # eg: inet addr:192.168.5.2  Bcast:192.168.5.255  Mask:255.255.255.0
        ip = stdout.split('\n')[1].split()[1].split(':')[1]

        # determine if the current host is supposed to be the master, or not.
        with open('/etc/hosts', 'r') as f:
            for l in f:
                if '%s db-master # fabric' % ip in l:
                    return True
        return False


if __name__ == '__main__':
    Check().run()
