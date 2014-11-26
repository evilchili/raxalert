#!/usr/bin/env python

import os
import sys
import imp
import click
import yaml
import tempfile
import socket
from glob import iglob

# let dynamically-loaded modules find the current package
sys.path.append(os.path.join(os.path.abspath(__file__), '..', '..'))

# look up our currnet hostname
hostname = socket.gethostname()


def dump_config(check, path):
    """
    Return a YAML dump of the check configuration.
    """

    # helpers
    class literal(str):
        """
        Stupid YAML
        """
        pass

    def literal_presenter(dumper, data):
        """
        Stupid YAML
        """
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')

    def alert_format(a):
        """
        Returns a dict of the attributes defined on the specified Alert object,
        both instance and class, as well as casting the criteria as a literal object
        such that the pyyaml dumper will render it as a literal string. Stupid YAML.
        """
        d = {}
        for k in [v for v in dir(a) if not v.startswith('__') and not callable(getattr(a, v))]:
            d[k] = getattr(a, k)
        del d['name']
        d['criteria'] = literal('\n'.join(a.criteria))
        return d

    # add the configured (not None) atributes from the check
    config = dict([(k, v) for (k, v) in check._config.items() if v is not None])

    # tell rackspace-monitor how to invoke the check, which is done by invoking the bash wrapper
    # script which is installed as a rackspace-monitoring-agent plugin, which in turn loads the
    # virtual env and executes this script.
    config['details'] = {'file': 'alert-wrapper.sh', 'args': [os.path.abspath(path)]}

    # add the alerts, if there are any
    alerts = check.alerts()
    if alerts:
        config['alarms'] = dict([(a.name, alert_format(a)) for a in alerts])

    yaml.add_representer(literal, literal_presenter)
    return yaml.dump(config, default_flow_style=False)


def load(path):
    """
    dynamically load the 'Check' class from the specified file, and instantiate it
    """
    mod_name, file_ext = os.path.splitext(os.path.split(path)[-1])
    module = imp.load_source(mod_name, path)
    check = getattr(module, 'Check')()
    return check


@click.group()
def main():
    pass


@main.command()
@click.argument('path', type=click.Path(exists=True))
def run(path):
    """
    Run a check and print its metrics on STDOUT, errors on STDERR.
    """
    check = load(path)
    if check.conf.disabled:
        print "Check is disabled; skipping.\n"
    else:
        check.run()


@main.command()
@click.argument('path', type=click.Path(exists=True))
def dump(path):
    """
    Print a plugin configuration for the specified check, in YAML. Stupid YAML.
    """
    check = load(path)
    print dump_config(check, path)


@main.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--outdir', help='specify output directory (default is a random tmpdir)')
def collect(path, outdir):
    """
    Collect all checks in the specified path, loads them, verifies their configs, and
    writes .yaml configuration files in the specified output directory, or a random tmpdir.
    """

    tmpdir = tempfile.mkdtemp(prefix='alerts_')

    if outdir and not os.path.exists(outdir):
        os.makedirs(outdir)

    count = 0
    for check_file in iglob('%s/*.py' % path):
        cfgfile = os.path.basename(check_file.replace('.py', '.yaml'))
        tmpfile = os.path.join(tmpdir, cfgfile)

        try:
            check = load(check_file)
        except AttributeError:
            continue

        # if the check has a host_pattern defined, and the current hostname
        # does not match said pattern, do not deploy this check.
        if check.host_pattern is not None and not check.host_pattern.search(hostname):
            print "%s: %s does not match '%s'; skipping" % (
                check.label, hostname, check.host_pattern.pattern
            )
            continue

        config = dump_config(check, check_file)

        # if the output isn't well-formed YAML, don't write it to disk.
        try:
            yaml.load(config)
        except:
            raise Exception("Invalid plugin config for %s!\n%s" %
                            (check, config))

        # write the config to a temporary file
        with open(tmpfile, 'wb') as f:
            f.write(config)

        count += 1

        # move the temporary file into place and make sure it is readable
        if outdir:
            outfile = os.path.join(outdir, cfgfile)
            os.rename(tmpfile, outfile)
            os.chmod(outfile, 0644)
    if outdir:
        os.rmdir(tmpdir)

    print "Wrote %s configs to %s" % (count, outdir or tmpdir)


if __name__ == '__main__':
    main()
