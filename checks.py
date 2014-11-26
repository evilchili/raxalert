import sys
import re
import sh
try:
    import cStringIO as StringIO
except:
    import StringIO


################
# BASE CLASSES #
################

class Alert(object):
    """
    Define an alert for the rackspace-monitor. Your check's alerts() method should return an array
    of these objects, which are used to generate the alerts section of the plugin configuration.
    """
    name = None
    label = None
    criteria = []
    notification_plan_id = 'npTechnicalContactsEmail'

    def __init__(self, **kwargs):
        for (k, v) in kwargs.items():
            setattr(self, k, v)


class RaxCheck(object):
    """
    Base class for rackspace monitoring plugin checks.
    """
    _config = {
        'type': 'agent.plugin',
        'period': 60,
        'timeout': 30,
        'disabled': False,
        'label': None,
    }

    # None, for all hosts, or a regex that matches hostnames to which the check should be deployed
    host_pattern = None

    # status values
    OK = 'OK'
    ERROR = 'ERROR'

    # common metric names
    CONFIG_ERROR = 'CONFIG_ERROR'
    EXCEPTION = 'EXCEPTION'
    STATUS = 'STATUS'

    metrics = ()
    status = OK

    def __init__(self):
        """
        Sugar: assign the value of any of the subclasses' attributes to the
        _config dict, if the attribute names are present in _config's keys.
        """
        for (k, v) in self._config.items():
            self._config[k] = getattr(self, k, v)

    @property
    def conf(self):
        """
        Sugar: make _config accessable as an object; self._config['foo'] == self.conf.foo
        """
        class O(object):
            pass
        o = O()
        for (k, v) in self._config.items():
            setattr(o, k, v)
        return o

    def error(self, msg, error_type=None):
        """
        Add an error to the metrics, and set status to ERROR.
        """
        if not error_type:
            error_type = self.CONFIG_ERROR
        self.metrics += ((error_type, 'check() not configured', 'string'), )
        self.status = self.ERROR
        return (self.status, self.metrics)

    def alerts(self):
        """
        Dummy alerts() method. If you want alerts for your checks, redefine this method in your
        subclass. The method should return None, for no alerts, or an array of Alert objects.
        """
        return None

    def shell(self, cmd, *args, **kwargs):
        """
        Run a shell command and return exit code, stdout and stderr.
        The cmd parameter must be a callable from sh. Example:

        (status, stdout, stderr) = self.shell(sh.ntpdate, "-q", "pool.ntp.org")

        """
        stdout = StringIO.StringIO()
        stderr = StringIO.StringIO()
        kwargs['_out'] = stdout
        kwargs['_err'] = stderr
        ret = cmd(*args, **kwargs)
        stdout.seek(0)
        stdout.seek(0)
        return ret.exit_code, stdout.read(), stderr.read()

    def check(self):
        """
        Dummy check() method; sub-classes should redefine this.

        Subclasses' check() methods should return a tuple consisting of the status, either
        self.OK or self.ERROR, and a set of tuples for metrics, of the form:

          (METRIC_NAME, METRIC_VALUE, METRIC_TYPE)

        More information on agent plugins:
        http://docs.rackspace.com/cm/api/v1.0/cm-devguide/content/appendix-check-types-agent.html

        """
        return self.error('check() not configured!')

    def run(self):
        """
        Run the check() method and print its results in the manner expected by rackspace-monitor.
        """
        try:
            self.check()
        except Exception as e:
            print >> sys.stderr, "Exception: %s" % e
            self.error("An error occurred: %s" % str(e).replace("\n", " "), self.EXCEPTION)
        print 'status %s' % self.status
        print '\n'.join(["metric %s %s %s" % (n, m, v) for (n, v, m) in self.metrics])


################
# BASIC CHECKS #
################
# The following classes implement simple checks that you can subclass for your own configs.


class FileSystemCheck(RaxCheck):
    """
    Collect metrics about a mounted filesystem.

    Example:

    class Check(FileSystemCheck):
        label = 'shared storage'
        device = '/dev/xvdd1'
        usage_warning = 80
        usage_critical = 90
        inode_warning = 80
        inode_critical = 90
    """

    label = 'File System'
    device = None

    usage_warning = 80
    usage_critical = 90

    inode_warning = 80
    inode_critical = 90

    def check(self):

        self.status = self.OK

        # look up the mount
        (fs_dev, fs_mount, fs_type, fs_opts, dummy1, dummy2) = (None, None, None, None, None, None)
        with open('/proc/mounts', 'r') as f:
            for l in f:
                (fs_dev, fs_mount, fs_type, fs_opts, dummy1, dummy2) = l.split()
                if fs_dev == self.device:
                    self.metrics += (
                        ('fs.mount_point', fs_mount, 'string'),
                        ('fs.type', fs_type, 'string'),
                    )
                    for opt in fs_opts.split(','):
                        metric_type = 'string'
                        if '=' in opt:
                            (metric_name, metric_value) = opt.split('=')
                        elif opt in ['rw', 'ro']:
                            metric_value = opt
                            metric_name = 'mode'
                        else:
                            metric_name = opt
                            metric_value = 1
                            metric_type = 'int32'
                        self.metrics += (('fs.option.%s' %
                                         metric_name, metric_value, metric_type), )
                    break
        if not fs_dev:
            return self.error('%s is not mounted!' % self.device)

        # get the disk usage from df
        (status, stdout, stderr) = self.shell(sh.df, '-B1', fs_mount)
        if status != 0:
            return self.error("Could not get usage data: %s" % stderr)

        (fs_dev, fs_size, fs_used, fs_avail, dummy1, dummy2) = stdout.split('\n')[1].split()
        self.metrics += (
            ('fs.storage.size', int(fs_size) or 1, 'uint64'),
            ('fs.storage.used', fs_used, 'uint64'),
            ('fs.storage.avail', fs_avail, 'uint64'),
        )

        # get inode usage info
        (status, stdout, stderr) = self.shell(sh.df, '-i', fs_mount)
        if status != 0:
            return self.error("Could not get usage data: %s" % stderr)

        (in_dev, in_total, in_used, in_avail, dummy1, dummy2) = stdout.split('\n')[1].split()
        self.metrics += (
            ('fs.inodes.total', int(in_total) or 1, 'uint64'),
            ('fs.inodes.used', in_used, 'uint64'),
            ('fs.inodes.avail', in_avail, 'uint64'),
        )

    def alerts(self):
        """
        Default alerts for this check; redefine in subclass if necessary.
        """
        return [
            Alert(name='disk-usage', label='disk usage', criteria=[
                "if (percentage(metric['fs.storage.used'], metric['fs.storage.size']) > %s) {\n"
                "   return new AlarmStatus(WARNING, 'Disk usage is greater than %s precent');\n"
                "}" % (self.usage_warning, self.usage_warning),
                "if (percentage(metric['fs.storage.used'], metric['fs.storage.size']) > %s) {\n"
                "   return new AlarmStatus(CRITICAL, 'Disk usage is greater than %s precent');\n"
                "}" % (self.usage_critical, self.usage_critical),
            ]),
            Alert(name='inode-usage', label='inode usage', criteria=[
                "if (percentage(metric['fs.inodes.used'], metric['fs.inodes.total']) > %s) {\n"
                "   return new AlarmStatus(WARNING, 'Disk usage is greater than %s precent');\n"
                "}" % (self.inode_warning, self.inode_warning),
                "if (percentage(metric['fs.inodes.used'], metric['fs.inodes.total']) > %s) {\n"
                "   return new AlarmStatus(CRITICAL, 'Disk usage is greater than %s precent');\n"
                "}" % (self.inode_critical, self.inode_critical),
            ]),
        ]


class FileSizeCheck(RaxCheck):
    """
    Check that the size of a given file is between min_file_size and max_file_size.

    Example:

    class Check(FileSizeCheck):
        # alert if log size exceeds 20MB
        label = 'MyProc Log Size'
        file = '/var/log/myproc/myproc.log"
        max_file_size = 20 * 1024 * 1024

    """

    label = 'File Size'
    file = None

    # a value of None causes the min or max threshold to be ignored.
    min_file_size = None
    max_file_size = 5 * 1024 * 1024

    def check(self):
        """
        Implement the file size check.
        """
        import os

        self.status = self.OK

        fs = os.path.getsize(self.file)
        self.metrics = (('size', fs, 'uint64'), )
        if self.max_file_size and fs > self.max_file_size:
            self.error('maximum file size (%s) exceeded!' % self.max_file_size)
        elif self.min_file_size and fs < self.min_file_size:
            self.error('minimum file size (%s) not met!' % self.min_file_size)
        else:
            self.metrics += ((self.STATUS, 'File Size OK', 'string'), )

    def alerts(self):
        """
        Default alerts for this check; redefine in subclass if necessary.
        """
        return [
            Alert(name='file-size', label='file size', criteria=[
                "if (percentage(metric['size'], %s) > 90) {\n"
                "   return new AlarmStatus(WARNING, 'File size is in the 90th pecentile.');\n"
                "}" % self.max_file_size,
                "if (percentage(metric['size'], %s) >= 100) {\n"
                "    return new AlarmStatus(CRITICAL, 'Maximum file size exceeded!');\n"
                "}" % self.max_file_size,
                "return new AlarmStatus(OK, 'File size is #{size} bytes.');",
            ]),
        ]


class ProcessCheck(RaxCheck):
    """
    Check that a given process name is in the process tree. If pidfile is not None, also
    check the contents of the pidfile against the process ID(s) of the named process.

    Resource utilization alerts can be triggered by defining the max_* attributes.

    Usage:

    class Check(ProcessCheck):
        pidfile = '/var/run/someproc.pid'
        name = 'myprocd'
        user = 'root'  # raise an alert if not running as root
        max_cpu = 50  # raise an alert if using more than 50% cpu
    """

    pidfile = None
    name = None

    max_cpu = None
    max_memory = None
    max_vsize = None
    max_rsize = None
    user = None

    def check(self):

        running = False
        self.status = self.ERROR

        try:
            if self.pidfile:
                with open(self.pidfile) as f:
                    pidfile_pid = f.read()
                pidfile_pid = pidfile_pid.strip()
                self.metrics += (('pidfile_pid', pidfile_pid, 'int32'), )
            else:
                pidfile_pid = None
        except Exception as e:
            return self.error('Could not read pidfile: %s' % e)

        for line in sh.ps('auwx', _tty_out=False):
            [user, pid, cpu, mem, vsz, rss, tt, stat, started, time, cmd] = line.split()[:11]
            if cmd.startswith(self.name) or re.search(r'/%s\b' % self.name, cmd):
                running = True
                self.metrics += (
                    ('user', user, 'string'),
                    ('pid', pid, 'uint32'),
                    ('cpu', cpu, 'double'),
                    ('memory', mem, 'double'),
                    ('vsize', vsz, 'uint64'),
                    ('rsize', rss, 'uint64'),
                    ('command', cmd, 'string'),
                )
                break

        if running:
            self.status = self.OK
        else:
            self.metrics += (('pid', 0, 'uint32'), )

    def alerts(self):
        criteria = [
            "if (metric['pid'] == 0) {\n"
            "   return new AlarmStatus(CRITICAL, 'Process is not running.');\n"
            "}",
        ]
        if self.max_cpu:
            criteria.append(
                "if (metric['cpu'] > %s) {\n"
                "    return new AlarmStatus(WARNING, 'Maximum CPU usage exceeded!');\n"
                "}" % self.max_cpu
            )
        if self.max_memory:
            criteria.append(
                "if (metric['memory'] > %s) {\n"
                "    return new AlarmStatus(WARNING, 'Maximum memory usage exceeded!');\n"
                "}" % self.max_memory
            )
        if self.max_vsize:
            criteria.append(
                "if (metric['vsize'] > %s) {\n"
                "    return new AlarmStatus(WARNING, 'Maximum VSIZE usage exceeded!');\n"
                "}" % self.max_vsize
            )
        if self.max_rsize:
            criteria.append(
                "if (metric['rsize'] > %s) {\n"
                "    return new AlarmStatus(WARNING, 'Maximum RSIZE usage exceeded!');\n"
                "}" % self.max_rsize
            )
        if self.user:
            criteria.append(
                "if (metric['user'] != '%s') {\n"
                "    return new AlarmStatus(WARNING, 'Not running as %s!');\n"
                "}" % (self.user, self.user)
            )

        return [
            Alert(name='techs', label='%s is running' % self.name, criteria=criteria),
        ]


class MySQLReplicationCheck(RaxCheck):
    """
    Check on the status of a MySQL replica set. By default, only checks on the slave status,
    but can be made to auto-detect by overriding the is_master() method to return True if
    run on your master; see examples/mysql-replication.py.

    Example, presuming two db nodes, 'db-master' and 'db-slave':

    class Check(MySQLReplicationCheck):
        host_pattern = re.compile(r'\bdb-.+\b', re.IGNORECASE)

        def is_master(self):
            import socket
            hostname = socket.gethostname()
            return 'master' in socket.gethostname()
    """

    label = 'MySQL Replication'

    slave_behind_warning = 2
    slave_behind_critical = 5
    host_pattern = None

    def is_master(self):
        """
        Return True if the current host should be checked as the MySQL master; you
        should override this in your subclass if you want to auto-detect masters and slaves.
        """
        return False

    def _mysql(self, cmd):
        """
        Execute an sql command via the mysql CLI and parse the output rows into a list of dicts.
        """
        import csv

        # Note: do not use the defaults_file keyward arg here; it will cause mysql to exit with
        # error code 7 ("argument list too long"). Also: WTF?
        (status, stdout, stderr) = self.shell(
            sh.mysql,
            '--defaults-file=/root/.my.cnf',
            '-B',
            '-e %s' % cmd,
        )
        if status or not stdout:
            self.error('There was an error (%d):\n%s' % (status, stderr))
            return None
        return list(csv.DictReader(StringIO(stdout), delimiter='\t', quoting=csv.QUOTE_NONE))

    def check(self):
        """
        Determine whether the current host is the master or slave, and invoke the correct check.
        """
        return self.check_master() if self.is_master() else self.check_slave()

    def check_master(self):
        """
        Check on the status of the master node, by ensuring we have at least one slave connection.
        """
        rows = self._mysql('SHOW PROCESSLIST')
        if not rows:
            return
        slaves = []
        for row in rows:
            if 'Command' not in row or 'Binlog Dump' not in row['Command']:
                continue
            else:
                slaves.append(row['Host'])

        if slaves == []:
            self.error('No slave connections!')

        self.metrics += (
            ('slaves.hosts', ', '.join(slaves), 'string'),
            ('slaves.connected', len(slaves), 'uint32'),
        )
        return (self.status, self.metrics)

    def check_slave(self):
        """
        Check that the slave is running and successfully replicating the master.
        """
        rows = self._mysql('SHOW SLAVE STATUS')
        if not rows:
            return
        row = rows[0]

        if row['Slave_IO_Running'] == 'Yes' and row['Slave_SQL_Running'] == 'Yes':
            online = 'ONLINE'
        else:
            online = 'OFFLINE'
        self.metrics += (
            ('slave.status', online, 'string'),
            ('slave.seconds_behind', row['Seconds_Behind_Master'], 'int32'),
            ('slave.last_error', row['Last_Errno'], 'int32'),
        )

    def alerts(self):

        if self.is_master():
            alerts = [Alert(name='mysql-replication', label='MySQL master', criteria=[
                "if (metric['slaves.connected'] == 0) {\n"
                "    return new AlarmStatus(CRITICAL, 'All MySQL slaves are offline!');\n"
                "}\n",
                "return new AlarmStatus(OK, '#{slaves.connected} slave(s) connected');"
            ])]
        else:
            alerts = [Alert(name='mysql-replication', label='MySQL slave', criteria=[
                "if (metric['slave.status'] == 'OFFLINE') {\n"
                "    return new AlarmStatus(CRITICAL, 'MySQL slave is offline!');\n"
                "}\n",
                "if (metric['slave.seconds_behind'] >= %s) {\n"
                "    return new AlarmStatus(WARNING, 'Slave is #{slave.seconds_behind}ss behind.');\n"
                "}\n" % self.slave_behind_warning,
                "if (metric['slave.seconds_behind'] >= %s) {\n"
                "    return new AlarmStatus(CRITICAL, 'Slave is #{slave.seconds_behind}s behind!');\n"
                "}\n" % self.slave_behind_critical,
                "return new AlarmStatus(OK, 'MySQL slave is online.');"
            ])]
        return alerts
