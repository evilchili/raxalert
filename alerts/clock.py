from checks import RaxCheck, Alert
import sys
import sh
import re


class Check(RaxCheck):
    """
    Check the system clock for drift, using ntpdate.
    """

    label = 'Clock'
    drift_warning = 5
    drift_critical = 10

    def check(self):

        # run ntpdate and query the time server pool
        (status, stdout, stderr) = self.shell(sh.ntpdate, "-q", "pool.ntp.org")

        # if ntpdate has a non-zero exit status, complain about it
        if status != 0:
            print >> sys.stderr, "There was an error (%d): \n" % status
            print >> sys.stderr, stderr if stderr else 'Unknown error'
            status = self.ERROR
            self.error('Could not execute ntpdate!')

        # ntpdate exited cleanly, so parse the output
        else:
            # extract the offset as an absolute float from the last line of ntpdate output.
            # we use a regex here because different implementations of ntpdate may yield
            # slightly different output, but all contain the phrase 'offset <some number>'
            try:
                last_line = stdout.split("\n")[:1][0]
                m = re.search('.*offset\s([-\d\.]+)', last_line)
                offset = abs(float(m.group(1)))
            except Exception as e:
                print >> sys.stderr, e
                self.error('Could not parse ntpdate output!')

            # we got the offset, so return it as a metric
            else:
                status = self.OK
                self.metrics = (('offset', offset, 'double'), )

    def alerts(self):
        """
        Set up alerts for offset values that cross the warning and critical thresholds.
        """
        return [
            Alert(name='techs', label='clock drift', criteria=[
                "if (metric['offset'] >= %s) {\n"
                "    return new AlarmStatus(WARNING, 'Clock drift is #{offset}s.');\n"
                "}" % self.drift_warning,
                "if (metric['offset'] >= %s) {\n"
                "    return new AlarmStatus(CRITICAL, 'Clock drift is #{offset}s!');\n"
                "}" % self.drift_critical,
                "return new AlarmStatus(OK, 'Offset is #{offset}s, "
                "below your warning threshold of %s');" % self.drift_warning
            ]),
        ]


if __name__ == '__main__':
    Check().run()
