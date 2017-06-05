"""
The testcases module is for use by Autopilot Pattern application tests
to run integration tests using Docker and Compose as its driver.
"""
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
# helpers

COMPOSE = os.environ.get('COMPOSE', 'docker-compose')
""" Optionally override path to docker-compose via COMPOSE env var """

COMPOSE_FILE = os.environ.get('COMPOSE_FILE', 'docker-compose.yml')
""" Optionally override compose file name via COMPOSE_FILE env var """

DOCKER = os.environ.get('DOCKER', 'docker')
""" Optionally override path to docker via DOCKER env var """

Container = namedtuple('Container', ['name', 'command', 'state', 'ports'])
""" Named tuple describing a container from the output of docker-compose ps """

IP_REGEX = re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
""" Pre-compiled regex for getting IPv4 addresses. """

class WaitTimeoutError(Exception):
    """ Exception raised when a timeout occurs. """
    pass

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

# -----------------------------------------
# main functionality is defined here

class AutopilotPatternTest(unittest.TestCase):
    """
    AutopilotPatternTest serves as the base class for all tests and adds
    extra setup/teardown functionality.
    """

    project_name = ''
    """ Test subclasses should override this project_name """

    compose_file = COMPOSE_FILE
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

    def _setUp(self):
        """
        AutopilotPatternTest._setUp will be called after a subclass's
        own setUp. First asserts that there are not running containers,
        then starts the containers and waits for them all to be
        marked with Status 'Up'
        """
        self.load_triton_profile()
        self.instrumented_commands = []
        self.compose('stop')
        self.compose('rm', '-f')

        try:
            self.compose('up', '-d')
            self.wait_for_containers()
        except subprocess.CalledProcessError as ex:
            self.fail('{} failed: {}'.format(ex.cmd, ex.output))
            self.compose_logs()
            self.stop()
        except WaitTimeoutError as ex:
            self.fail(ex)
            self.compose_logs()
            self.stop()

    def _tearDown(self):
        """
        AutopilotPatternTest._tearDown will be called before a subclass's
        own tearDown. We don't teardown containers here so that we can
        pass --failfast to the test runner and leave the containers in place
        for postmortem debugging.
        """
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
        print('{}\n{}\n{}'.format(_bar,
                                  self.id().replace('__main__.', '', 1), _bar))
        _report.info('', extra=dict(elapsed='elapsed', task='task'))
        for cmd in self.instrumented_commands:
            if cmd[0] == 'run':
                task = " ".join([str(arg) for arg in cmd[1][0]])
            else:
                # we don't want check_output to appear for our external
                # calls to docker and docker-compose, but if a subclass
                # instruments a function we want to catch that name
                task = " ".join([str(arg) for arg in cmd[1]])
                task = '{}: {}'.format(cmd[0], task)
            _report.info('', extra=dict(elapsed=str(cmd[2]), task=task))

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
        if (len(args) == 1 and all(c in string.hexdigits for c in args[0])):
            return args[0]
        name = '_'.join([str(a) for a in args])

        if (name.startswith(self.project_name)
                and name.startswith('{0}_{0}_'.format(self.project_name))):
                # some projects have services with the same name
                return name
        return '{}_{}'.format(self.project_name, name)

    def compose(self, *args, **kwargs):
        """
        Runs `docker-compose` with the project and file flag set for this
        test run, using `args` as its parameters. Returns combined string
        of stdout, stderr of the process and allows CalledProcessError
        to bubble up. Subclasses should always call this method rather
        than calling `subprocess.run` so that the call is instrumented.
        Kwargs:
          - verbose=True: print stdout to console
        """
        _compose_args = [COMPOSE, '-f', self.compose_file]
        if self.project_name:
            _compose_args.extend(['-p', self.project_name])
            _compose_args = _compose_args + [arg for arg in args if arg]
        try:
            proc = self.instrument(subprocess.run, _compose_args,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,
                                   check=True, universal_newlines=True,
                                   env=os.environ.copy())
            if kwargs.get('verbose', False):
                print(proc.stdout)
            return proc.stdout
        except subprocess.CalledProcessError as ex:
            print(ex.output)
            self.fail(ex)


    def docker(self, *args, **kwargs):
        """
        Runs `docker` with `args` as its parameters. Returns combined
        string of stdout, stderr of the process and allows
        CalledProcessError to bubble up. Subclasses should always call
        this method rather than calling `subprocess.run` so that the
        call is instrumented.
        Kwargs:
          - verbose=True: print stdout to console
        """
        _docker_args = [DOCKER] + [arg for arg in args if arg]
        proc = self.instrument(subprocess.run, _docker_args,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               check=True, universal_newlines=True,
                               env=os.environ.copy())
        if kwargs.get('verbose', False):
            print(proc.stdout)
        return proc.stdout


    def compose_ps(self, service_name=None, verbose=False):
        """
        Runs `docker-compose ps`, filtered by `service_name` and dumping
        results to stdout if the `verbose` param is included. Returns a
        list of field dicts.
        """
        output = self.compose('ps', verbose=verbose)

        # trim header and any warning text
        lines = re.split('-+\n', output, re.S|re.M)[1].splitlines()

        # Because the output of `docker-compose ps` isn't line-oriented
        # we have to do a bunch of ugly parsing/regex to force it into lines.

        def _find_column_windows(line):
            """
            Figure out where compose split the column. we need to make
            sure we catch the last bit so add 2 trailing spaces to the line
            """
            segments = re.findall('.*?\s\s+', line+'  ')
            windows = [0]
            for i, seg in enumerate(segments):
                windows.append(windows[i] + len(seg))
            return windows

        def _find_rows_from_lines(lines):
            """
            Combined associated lines into rows (each 'row' is itself still
            a list of strings) which each represent one running container.
            """
            rows = []
            i = -1
            for line in lines:
                if not line.startswith(' '):
                    rows.append([line])
                    i += 1
                else:
                    rows[i].append(line)
            return rows

        def _find_fields_from_row(row, windows):
            """
            Takes a multi-line row of columized text output and returns the
            text grouped into a list of strings where each string is the
            cleaned-up text of a single column.
            """
            output = [''] * (len(windows) - 1)
            for line in row:
                for i in range(len(windows) - 1):
                    output[i] += line[windows[i]:windows[i+1]]

            # this last scrubbing makes sure we don't have big gaps or
            # split IP addresses with spaces
            return [re.sub('\. ', '.', re.sub('  +', ' ', field).strip())
                    for field in output]

        windows = _find_column_windows(lines[0])
        rows = _find_rows_from_lines(lines)
        return [Container(*_find_fields_from_row(row, windows)) for row in rows]


    def compose_scale(self, service_name, count, verbose=False):
        """
        Runs `docker-compose scale <service>=<count>`, dumping
        results to stdout
        """
        self.compose('scale',
                     '{}={}'.format(service_name, count), verbose=verbose)

    def compose_logs(self):
        try:
            print(self.compose('logs'))
        except docker.errors.APIError as ex:
            # TODO: figure out why this gets cut off
            print(ex)

    def docker_exec(self, container, command_line, verbose=False):
        """
        Runs `docker exec <command_line>` on the container and returns
        the combined stdout/stderr. The `command_line` parameter can be
        a list of arguments of a single string.
        """
        name = self.get_container_name(container)
        try:
            args = command_line.split()
        except AttributeError:
            args = command_line
        args = ['exec', name] + args
        return self.docker(*args, verbose=verbose)

    def docker_stop(self, container, verbose=False):
        """ Stops a specific instance. """
        name = self.get_container_name(container)
        return self.docker('stop', name, verbose=verbose)

    def docker_logs(self, container, since=None, verbose=True):
        """ Returns logs from a given container. """
        name = self.get_container_name(container)
        args = ['logs', name] + \
               (['--since', since] if since else [])
        return self.docker(*args, verbose=verbose)

    def docker_inspect(self, container):
        """
        Runs `docker inspect` on a given container and parses the JSON.
        """
        name = self.get_container_name(container)
        output = self.docker('inspect', name)
        return json.loads(output)

    def get_service_ips(self, service, ignore_errors=False):
        """
        Gets a list of IPs for a service by checking each of its containers.
        Returns a pair of lists (public, private).
        """
        out = self.compose('ps', '-q', service)
        containers = out.splitlines()
        private_ips = []
        public_ips = []

        for container in containers:
            # we have the "real" name here and not the container-only name
            try:
                public_ip, private_ip = self.get_ips(container)
                if private_ip:
                    private_ips.append(private_ip)
                if public_ip:
                    public_ips.append(public_ip)
            except subprocess.CalledProcessError:
                if not ignore_errors:
                    # sometimes we've stopped an instance or have updated
                    # the service a container reports to Consul so we want
                    # to skip CalledProcessError. In this case the caller
                    # should be comparing the length of the lists returned
                    # vs the expected length.
                    raise

        return public_ips, private_ips

    def get_ips(self, container):

        out = self.docker_exec(container, 'ip -o addr')
        ips = set(IP_REGEX.findall(out))
        ips.discard('127.0.0.1')
        ips.discard('0.0.0.0')
        ips = [IP(ip) for ip in ips]
        private = None
        public = None
        for ip in ips:
            if ip.iptype() == 'PRIVATE':
                private = ip
            elif ip.iptype() == 'PUBLIC':
                public = ip
        return public, private

    def watch_docker_logs(self, name, val, timeout=60):
        """ TODO """
        pass

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

    def get_consul_key(self, key):
        """
        Return the Value field for a given Consul key. Handles None
        results safely but lets all other exceptions just bubble up.
        """
        result = self.consul.kv.get(key)
        if result[1]:
            return result[1]['Value']
        return None

    def get_service_instances_from_consul(self, service_name):
        """
        Asks Consul for list of containers for a service. Relies on
        the naming convention for services done by ContainerPilot
        which injects the container hostname into the service ID.
        """
        # https://www.consul.io/docs/agent/http/health.html#health_service
        nodes = self.consul.health.service(service_name, passing=True)[1]
        if nodes:
            prefix = '{}-'.format(service_name)
            node_ids = [service['Service']['ID'].replace(prefix, '', 1)
                        for service in nodes]
            return node_ids
        return []

    def get_service_addresses_from_consul(self, service_name):
        """
        Asks Consul for a list of addresses for a service (compare to
        `get_service_ips` which asks the containers via `inspect`).
        """
        # https://www.consul.io/docs/agent/http/health.html#health_service
        nodes = self.consul.health.service(service_name, passing=True)[1]
        if nodes:
            ips = [service['Service']['Address'] for service in nodes]
            return ips
        return []

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
        Runs an external script and returns the stdout/stderr as a single
        string. Allows subprocess.CalledProcessError to bubble up to caller.
        """
        proc = subprocess.run(args,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              check=True, universal_newlines=True)
        return proc.stdout

    def load_triton_profile(self):
        """
        Loads the Triton profile specified in the 'TRITON_PROFILE' and
        sets those environment variables in this process.
        """
        profile = os.environ['TRITON_PROFILE']
        subprocess.run(
            'triton profile docker-setup -y {}'.format(profile).split(' '))
        subprocess.run(
            'triton profile set-current {}'.format(profile).split(' '))

        proc = subprocess.run(['triton', 'env', profile],
                            universal_newlines=True,
                            stdout=subprocess.PIPE)
        lines = proc.stdout.split('\n')
        env = read_env(lines)
        cert_path = env['DOCKER_CERT_PATH']
        _, suffix = cert_path.split('.triton')
        env['DOCKER_CERT_PATH'] = '{}/.triton{}'.format(os.environ['HOME'], suffix)
        for k, v in env.items():
            os.environ[k] = v


    def read_env_file(self, filename):
        """
        Reads the environment file and returns a dict of {variables: values}
        """
        env = {}
        with open(filename, 'r') as source:
            lines = source.readlines()
        return read_env(lines)

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
# helpers

def read_env(lines):
    env = {}
    for line in lines:
        if line and not line.startswith('#') and line != "\n":
            try:
                var, val = line.strip().split('=', 1)
                var = var.replace('export ', '', 1)
            except ValueError:
                if line.startswith('unset'):
                    line = line.replace('unset ', '', 1)
                    env[line] = ''
                else:
                    log.error('env file line "%s" is invalid, skipping' % line)
            env[var] = val
    return env


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
_report_handler.setFormatter(logging.Formatter('{elapsed:<8.8} | {task}',
                                               style="{"))
_report.addHandler(_report_handler)

log = logging.getLogger('tests')
"""
Logger that should be used by test implementations so that the testcases
lib logging shares the same format as the tests. Accepts LOG_LEVEL from
environment variables.
"""
