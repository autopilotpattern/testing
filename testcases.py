"""
The testcases module is for use by Autopilot Pattern application tests
to run integration tests using Docker and Compose as its driver.
"""
from __future__ import print_function
from collections import defaultdict, namedtuple
from functools import wraps
import inspect
import json
import logging
import os
import re
import subprocess
import string
import sys
import tempfile
import time
import unittest

import consul as pyconsul
from IPy import IP

# -----------------------------------------

Container = namedtuple('Container', ['name', 'command', 'state', 'ports'])

class WaitTimeoutError(Exception):
    """ Exception raised when a timeout occurs. """
    pass

class ClientException(Exception):
    """
    Exception raised when running the Compose or Docker client
    subprocess returns a non-zero exit code.
    """
    pass

def debug(fn):
    """
    Function/method decorator to trace calls via debug logging.
    Is a pass-thru if we're not at LOG_LEVEL=DEBUG. Normally this
    would have a lot of perf impact but this application doesn't
    have significant throughput.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # magic number 10 == roughly top of stack for this module
        name = '{}{}'.format(((len(inspect.stack())-10) * " "), fn.__name__)
        log.debug('%s: %s, %s' % (name, args, kwargs))
        out = apply(fn, args, kwargs)
        log.debug('%s: %s' % (name, str(out)[:50]))
        return out
    return wrapper

def dump_environment_to_file(filepath):
    """
    Takes the container's environment and dumps it out to a file
    that can be loaded as an env_file by Compose or bash. You'll
    need to call this before calling unittest.main in a tests.py
    if you want it to be available to Compose.
    """
    with open(filepath, 'w') as env_file:
        for k, v in os.environ.items():
            line = '{}={}\n'.format(k, v)
            env_file.write(line)


__pdoc__ = {}


class AutopilotPatternTest(unittest.TestCase):
    """
    AutopilotPatternTest serves as the base class for all tests and adds
    extra setup/teardown functionality.
    """

    project_name = ''
    """ Test subclasses should override this project_name """

    compose_file = 'docker-compose.yml'
    """
    Field for an alternate compose file (default: docker-compose.yml).
    Test subclasses generally won't need to override the compose file name.
    """

    _consul = None

    # futzes with pdoc fields so that we don't dump all the methods
    # for unittest.TestCase when we generate docs.
    for _field in unittest.TestCase.__dict__.keys():
        __pdoc__['AutopilotPatternTest.%s' % _field] = None

    @classmethod
    def setUpClass(cls):
        """
        Ensure that the base class setUp/tearDown is called in all child
        TestCases so that the caller doesn't have to worry about creating
        and tearing down containers between test runs.
        """
        child_setUp = cls.setUp
        def setUp_override(self, *args, **kwargs):
            val = child_setUp(self, *args, **kwargs)
            AutopilotPatternTest._setUp(self)
            return val
        cls.setUp = setUp_override

        child_tearDown = cls.tearDown
        def tearDown_override(self, *args, **kwargs):
            AutopilotPatternTest._tearDown(self)
            return child_tearDown(self, *args, **kwargs)
        cls.tearDown = tearDown_override

    @debug
    def _setUp(self):
        """
        AutopilotPatternTest._setUp will be called after a subclass's
        own setUp. Starts the containers and waits for them all to be
        marked with Status 'Up'
        """
        self.instrumented_commands = []
        self.compose('up', '-d')
        self.wait_for_containers()

    @debug
    def _tearDown(self):
        """
        AutopilotPatternTest._tearDown will be called before a subclass's
        own tearDown. Stops all the containers.
        """
        self.compose('stop')
        self.compose('rm', '-f')
        self._report()
        self.instrumented_commands = []

    def instrument(self, fn, *args, **kwargs):
        start = time.time()
        try:
            return fn(*args, **kwargs)
        except Exception as ex:
            raise
        finally:
            end = time.time()
            elapsed = end - start
            self.instrumented_commands.append((fn.__name__, args, elapsed))

    def _report(self):
        """
        Prints a simple timing report at the end of a test run
        """
        _bar = '-' * 70
        print('{}\n{}\n{}'.format(_bar, self.id().lstrip('__main__.'), _bar))
        _report.info('', extra=dict(elapsed='elapsed', task='task'))
        for cmd in self.instrumented_commands:
            task = " ".join([arg[:30] for arg in cmd[1][0]])
            if cmd[0] != 'check_output':
                # we don't want check_output to appear for our external
                # calls to docker and docker-compose, but if a subclass
                # instruments a function we want to catch that name
                task = '{}: {}'.format(cmd[0], task)
            _report.info('', extra=dict(elapsed=cmd[2], task=task))

    @property
    def consul(self):
        """
        Lazily constructs a Consul client pointing to the first Consul
        instance. We can't configure Consul during `setupClass` because
        we don't necessarily have Consul up and running at that point.
        """
        if not self._consul:
            insp = self.docker_inspect('consul_1')
            ip = insp[0]['NetworkSettings']['IPAddress']
            consul_host = ip if ip else os.environ.get('CONSUL', 'consul')
            self._consul = pyconsul.Consul(host=consul_host)
        return self._consul


    def get_container_name(self, *args):
        """
        Given an incomplete container identifier, construct the name
        with the project name included. Args can be a string like 'nginx_1'
        or an iterable like ('nginx', 2). If the arg is the container ID
        then it will be returned unchanged.
        """
        if (len(args) == 1 and len(args[0]) == 64 and
                all(c in string.hexdigits for c in args[0])):
            return args[0]
        name = '_'.join([str(a) for a in args])

        if (name.startswith(self.project_name)
                and name.startswith('{0}_{0}_'.format(self.project_name))):
                # some projects have services with the same name
                return name
        return '{}_{}'.format(self.project_name, name)

    def compose(self, *args, **kwargs):
        """
        Runs `docker-compose` with the appropriate project and file flag
        set for this test run, using `args` as its parameters. Pass the
        kwarg `verbose=True` to force printing the output.
        """
        try:
            _compose_args = ['docker-compose', '-f', self.compose_file]
            if self.project_name:
                _compose_args.extend(['-p', self.project_name])
                _compose_args = _compose_args + [arg for arg in args if arg]
            output = self.instrument(subprocess.check_output, _compose_args)
            #,
             #                        stderr=subprocess.STDOUT)
            if kwargs.get('verbose', False):
                print(output)
            return output
        except subprocess.CalledProcessError as ex:
            raise ClientException(ex)

    @debug
    def compose_ps(self, service_name=None, verbose=False):
        """
        Runs `docker-compose ps`, filtered by `service_name` and dumping
        results to stdout if the `verbose` param is included. Returns a
        list of field dicts.
        """
        output = self.compose('ps', verbose=verbose)

        # Because the output of `docker-compose ps` isn't line-oriented
        # we have to do a bunch of ugly regex to force it into lines.
        # Match up to first newline w/o space after it, but don't
        # consume that last character because it goes into the next line
        patt = '(.*?\\n)(?=\S)'
        rows = re.findall(patt, output)[2:] # trim header after regex
        return [Container(*self._decolumize_row(row)) for row in rows]


    def _decolumize_row(self, row):
        """
        Takes a multi-line row of columized text output and returns the
        text grouped into a list of strings where each string is the
        cleaned-up text of a single column.
        """
        lines = row.splitlines()
        # need to make sure we catch the last bit so add 2 trailing
        # spaces to each line
        segments = re.findall('.*?\s\s+', lines[0]+'  ')
        windows = [0]
        for i, seg in enumerate(segments):
            windows.append(windows[i] + len(seg))

        output = [seg for seg in segments]
        for line in lines[1:]:
            for i in range(len(segments)):
                output[i] += line[windows[i]:windows[i+1]]

        # this last scrubbing makes sure we don't have big gaps or
        # split IP addresses with spaces
        return [re.sub('\. ', '.', re.sub('  +', ' ', field).strip())
                for field in output]

    @debug
    def compose_scale(self, service_name, count):
        """
        Runs `docker-compose scale <service>=<count>`, dumping
        results to stdout
        """
        self.compose('scale', '{}={}'.format(service_name, count))

    @debug
    def docker_exec(self, container, command_line):
        """
        Runs `docker exec <command_line>` on the container and
        returns a tuple: (exit code, output). The `command_line`
        parameter can be a list of arguments of a single string.
        """
        try:
            name = self.get_container_name(container)
            output = self.instrument(subprocess.check_output,
                                     (['docker', 'exec', name] +
                                      command_line.split()))
            return (0, output)
        except subprocess.CalledProcessError as ex:
            return (ex.returncode, 'call %s failed: %s' % (ex.cmd, ex.output))

    @debug
    def docker_stop(self, container):
        """ Stops a specific instance. """
        try:
            name = self.get_container_name(container)
            output = self.instrument(subprocess.check_output,
                                     ['docker', 'stop', name])
            print(output)
        except subprocess.CalledProcessError as ex:
            raise ClientException(ex)

    @debug
    def docker_logs(self, container, since=None):
        """
        Returns logs from a given container.
        """
        try:
            name = self.get_container_name(container)
            args = ['docker', 'logs', name] + \
                   (['--since', since] if since else [])
            output = self.instrument(subprocess.check_output, args)
            print(output)
        except subprocess.CalledProcessError as ex:
            raise ClientException(ex)

    @debug
    def docker_inspect(self, container):
        """
        Runs `docker inspect` on a given container and parses the JSON.
        """
        try:
            name = self.get_container_name(container)
            output = self.instrument(subprocess.check_output,
                                     ['docker', 'inspect', name])
        except subprocess.CalledProcessError as ex:
            raise ClientException(ex)
        return json.loads(output)

    @debug
    def get_service_ips(self, service):
        """
        Asks the service a list of IPs for that service by checking each
        of its containers. Returns a pair of lists (public, private).
        """
        containers = self.compose('ps', '-q', service).splitlines()
        regex = re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
        private = []
        public = []

        for container in containers:
            # we have the "real" name here and not the container-only name
            _, out = self.docker_exec(container, 'ip -o addr')
            ips = set(regex.findall(out))
            ips.discard('127.0.0.1')
            ips.discard('0.0.0.0')
            ips = [IP(ip) for ip in ips]
            log.debug(ips)
            for ip in ips:
                if ip.iptype() == 'PRIVATE':
                    private.append(ip)
                elif ip.iptype() == 'PUBLIC':
                    public.append(ip)

        return public, private

    @debug
    def watch_docker_logs(self, name, val, timeout=60):
        """ TODO """
        pass

    @debug
    def wait_for_containers(self, timeout=30):
        """
        Waits for all containers to be marked as 'Up' for all services.
        """
        while timeout > 0:
            containers = self.compose_ps()
            if all([container.state == 'Up'
                    for container in containers]):
                break
            time.sleep(1)
            timeout -= 1
        else:
            raise WaitTimeoutError("Timed out waiting for containers to start.")

    @debug
    def wait_for_service(self, service_name, count=0, timeout=30):
        """
        Polls Consul for the service to become healthy, and optionally
        for a particular `count` of container instances to be healthy.
        """
        while timeout > 0:
            try:
                nodes = self.consul.health.service(service_name, passing=True)[1]
                if nodes:
                    if not count or len(nodes) == count:
                        break
            except (ValueError, IndexError):
                pass
            timeout -= 1
            time.sleep(1)
        else:
            raise WaitTimeoutError("Timeout waiting for {} to be started"
                                   .format(service_name))
        return nodes

    @debug
    def get_consul_key(self, key):
        """
        Return the Value field for a given Consul key. Handles None
        results safely but lets all other exceptions just bubble up.
        """
        result = self.consul.kv.get(key)
        if result[1]:
            return result[1]['Value']
        return None

    @debug
    def get_service_addresses_from_consul(self, service_name):
        """
        Asks Consul for a list of addresses for a service (compare to
        `get_service_ips` which asks the containers via `inspect`).
        """
        nodes = self.consul.health.service(service_name, passing=True)[1]
        if nodes:
            ips = [service['Service']['Address'] for service in nodes]
            return ips
        return []

    @debug
    def is_check_passing(self, key):
        """
        Queries consul for whether a check is passing.
        """
        check = self.consul.agent.checks()[key]
        if check['Status'] == 'passing':
            return True
        return False

    def assertHttpOk(self, container_id, path, port):
        """ TODO """
        pass

    @debug
    def wait_for_service_removed(self, service_name, timeout=30):
        """
        Polls Consul for the service to be removed.
        """
        while timeout > 0:
            nodes = self.consul.health.service(service_name, passing=True)[1]
            if not nodes:
                break
            timeout -= 1
            time.sleep(1)
        else:
            raise WaitTimeoutError("Timeout waiting for {} to be removed"
                                   .format(service_name))
        return True

    def run_script(self, *args):
        """
        Runs an external script and returns the output. Allows
        subprocess.CalledProcessError or OSError to bubble up to caller.
        """
        return subprocess.check_output(args)


    def update_env_file(self, filename, substitutions):
        """
        For each pair of substitutions, replace all cases of
        `variable=value` in the environment file. Ex.

        update_env_file('_env',
                       (('MYSQL_PASSWORD', 'password1'),
                        ('MYSQL_USER', 'me'))
        )
        """
        fns = []
        for sub in substitutions:
            variable = sub[0]
            value = '{}={}\n'.format(variable, sub[1])
            fn = lambda line, var=variable, val=value: \
                 val if line.startswith(var) else line
            fns.append(fn)

        with open(filename, 'r') as source:
            lines = source.readlines()

        with open(filename, 'w') as source:
            for line in lines:
                for fn in fns:
                    line = fn(line)
                source.write(line)


# -----------------------------------------
# set up logging

logging.basicConfig(format='%(asctime)s %(levelname)s %(name)s %(message)s',
                    stream=sys.stdout,
                    level=logging.getLevelName(
                        os.environ.get('LOG_LEVEL', 'INFO')))
_requests_logger = logging.getLogger('requests')
_requests_logger.setLevel(logging.ERROR)

# dummy logger so that we can print w/o interleaving
_print = logging.getLogger('testcases.print')
_print.propagate = False
_print_handler = logging.StreamHandler()
_print.setLevel(logging.INFO)
_print_handler.setFormatter(logging.Formatter('%(message)s'))
_print.addHandler(_print_handler)

def print(message):
    _print.info(message)

_report = logging.getLogger('testcases.report')
_report.propagate = False
_report_handler = logging.StreamHandler()
_report.setLevel(logging.INFO)
_report_handler.setFormatter(logging.Formatter('%(elapsed)-15s | %(task)s'))
_report.addHandler(_report_handler)

log = logging.getLogger('tests')
"""
Logger that should be used by test implementations so that the testcases
lib logging shares the same format as the tests. Accepts LOG_LEVEL from
environment variables.
"""
