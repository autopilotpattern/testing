"""
The testcases module is for use by Autopilot Pattern application tests
to run integration tests using Docker's `compose` library as its driver.
"""
from __future__ import print_function
from collections import defaultdict
from functools import wraps
import inspect
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

import consul as pyconsul
from compose.cli.command import project_from_options, get_project
from compose.cli.main import TopLevelCommand, log_printer_from_project
from compose.cli import signals
import docker.client
from dockerpty.pty import PseudoTerminal, ExecOperation
from IPy import IP

# -----------------------------------------
# set up logging

logging.basicConfig(format='%(asctime)s %(levelname)s %(name)s %(message)s',
                    stream=sys.stdout,
                    level=logging.getLevelName(
                        os.environ.get('LOG_LEVEL', 'INFO')))
_requests_logger = logging.getLogger('requests')
_requests_logger.setLevel(logging.ERROR)


log = logging.getLogger('tests')
"""
Logger that should be used by test implementations so that the testcases
lib logging shares the same format as the tests. Accepts LOG_LEVEL from
environment variables.
"""

# -----------------------------------------
# monkey patch instrumentation into the Docker Client lib

def _instrument(r, *args, **kwargs):
    # TODO: export to a report at the end of a test run
    # `elapsed` measures the time between sending the request and
    # finishing parsing the response headers, not until the full
    # response has been transfered.
    msg = 'elapsed:{}, url:{}'.format(r.elapsed, r.url)
    log.debug(msg)

_unpatched_init = docker.client.Client.__init__

def _patched_init(self, *args, **kwargs):
    _unpatched_init(self, *args, **kwargs)
    self.hooks = dict(response=_instrument)

docker.client.Client.__init__ = _patched_init

# -----------------------------------------

class WaitTimeoutError(Exception):
    """ Exception raised when a timeout occurs. """
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
        name = '{}{}'.format((len(inspect.stack()) * " "), fn.__name__)
        log.debug('%s' % name)
        out = apply(fn, args, kwargs)
        log.debug('%s: %s', name, out)
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
    compose = None
    """
    Field for the compose.cli.main.TopLevelCommand instance associated
    with the project. This will be populated by the setupClass method.
    """

    project = None
    """
    Field for the compose.project.Project instance associated with the
    project. This will be populated by the setupClass method.
    """

    project_name = ''
    """ Test subclasses should override this project_name """

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
        cls.project = project_from_options(
            '.',
            {"--project-name": cls.project_name})
        cls.compose = TopLevelCommand(cls.project)

        if cls is not AutopilotPatternTest and \
           cls.setUp is not AutopilotPatternTest.setUp:
            child_setUp = cls.setUp
            def setUp_override(self, *args, **kwargs):
                val = child_setUp(self, *args, **kwargs)
                AutopilotPatternTest.setUp(self)
                return val
            cls.setUp = setUp_override

        if cls is not AutopilotPatternTest and \
           cls.tearDown is not AutopilotPatternTest.tearDown:
            child_tearDown = cls.tearDown
            def tearDown_override(self, *args, **kwargs):
                AutopilotPatternTest.tearDown(self)
                return child_tearDown(self, *args, **kwargs)
            cls.tearDown = tearDown_override

    @property
    def consul(self):
        """
        Lazily constructs a Consul client pointing to the first Consul
        instance. We can't configure Consul during `setupClass` because
        we don't necessarily have Consul up and running at that point.
        """
        if not self._consul:
            insp = self.project.client.inspect_container(
                self.container_name('consul_1'))
            ip = insp['NetworkSettings']['IPAddress']
            consul_host = ip if ip else os.environ.get('CONSUL', 'consul')
            self._consul = pyconsul.Consul(host=consul_host)
        return self._consul

    @debug
    def setUp(self):
        """
        AutopilotPatternTest.setUp will be called after a subclass's
        own setUp. Starts the containers and waits for them all to be
        marked with Status 'Up'
        """
        self.docker_compose_up()
        self.wait_for_containers()

    @debug
    def tearDown(self):
        """
        AutopilotPatternTest.setUp will be called before a subclass's
        own tearDown. Stops all the containers.
        """
        self.docker_compose_stop()
        self.docker_compose_rm()

    def container_name(self, *args):
        """
        Given an incomplete container identifier, construct the name
        with the project name includes. Args can be a string like 'nginx_1'
        or an iterable like ('nginx', 2).
        """
        return '_'.join([self.project_name] + [str(a) for a in args])

    @debug
    def docker_compose_ps(self, service_name=None):
        """
        Runs `docker-compose ps`, dumping results to stdout.
        # TODO: support `service_name` filter param
        """
        options = defaultdict(str)
        self.compose.ps(options)

    @debug
    def docker_compose_up(self, service_name=None):
        """
        Runs `docker-compose up -d`, dumping results to stdout.
        # TODO: support `service_name` param
        """
        options = defaultdict(str)
        options['-d'] = True
        self.compose.up(options)

    @debug
    def docker_compose_stop(self, service_name=None):
        """
        Runs `docker-compose stop <service>`, dumping results to stdout.
        # TODO: support `service_name` param
        """
        options = defaultdict(str)
        self.compose.stop(options)

    @debug
    def docker_compose_rm(self, service_name=None):
        """
        Runs `docker-compose rm -f <service>`, dumping results to stdout.
        """
        options = defaultdict(str)
        options['--force'] = True
        self.compose.rm(options)

    @debug
    def docker_compose_scale(self, service_name, count):
        """
        Runs `docker-compose scale <service>=<count>`, dumping
        results to stdout
        """
        options = defaultdict(str)
        options['SERVICE=NUM'] = ['{}={}'.format(service_name, count)]
        self.compose.scale(options)

    @debug
    def docker_compose_exec(self, name, command_line):
        """
        Runs `docker-compose exec <command_line>` on the container and
        returns a tuple: (exit code, stdout, stderr). The `command_line`
        parameter can be a list of arguments of a single string.
        """
        try:
            command_line = command_line.split()
        except AttributeError:
            pass # was a list already

        name = self.container_name(name)

        containers = self.project.containers()
        for container in containers:
            if container.name == name:
                break

        # We can't just use compose.exec_command here because we
        # want to snag the stdout/stderr so we need to redirect this
        # all into temp files and clean up after ourselves.

        exec_opts = {
            "privileged": False,
            "user": None,
            "tty": False,
            "stdin": False
        }
        exec_id = container.create_exec(command_line, **exec_opts)

        signals.set_signal_handler_to_shutdown()
        try:
            _, out_path = tempfile.mkstemp()
            _, err_path = tempfile.mkstemp()
            operation = ExecOperation(self.project.client,
                                      exec_id,
                                      interactive=False,
                                      stdout=open(out_path, 'w'),
                                      stderr=open(err_path, 'w'))
            pty = PseudoTerminal(self.project.client, operation)
            pty.start()
        except signals.ShutdownException:
            log.info("received shutdown exception: closing")
        finally:
            # these get closed inside the ExecOperation so we need
            # to open them again for reading
            with open(err_path, 'r') as e:
                err = e.read()
            with open(out_path, 'r') as o:
                out = o.read()
            os.remove(err_path)
            os.remove(out_path)

        exit_code = self.project.client.exec_inspect(exec_id).get("ExitCode")
        return exit_code, out, err

    @debug
    def docker_stop(self, name):
        """ Stops a specific instance. """
        name = self.container_name(name)
        containers = self.project.containers()
        for container in containers:
            if container.name == name:
                print('Stopping {} ...'.format(name))
                container.stop()
                break

    @debug
    def docker_compose_logs(self, *services):
        """
        Returns logs as if running `docker-compose logs`. Takes an optional
        iterable of services to filter the logs by.
        """
        containers = self.project.containers(service_names=services,
                                             stopped=True)
        return self._get_logs(containers, services)

    @debug
    def docker_logs(self, name, since=None):
        """
        Returns logs from a given container in the Compose format.
        """
        name = self.container_name(name)
        containers = self.project.containers()
        for container in containers:
            if container.name == name:
                break
        return self._get_logs([container], [container.service], since)

    @debug
    def get_service_ips(self, service):
        """
        Asks the service a list of IPs for that service by checking each
        of its containers. Returns a pair of lists (public, private).
        """
        containers = self.project.containers(service_names=[service],
                                             stopped=False)
        regex = re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
        private = []
        public = []

        for container in containers:
            # we have the "real" name here and not the container-only name
            name = container.name.replace('{}_'.format(self.project_name), '', 1)
            _, out, _ = self.docker_compose_exec(name, 'ip -o addr')
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

    def _get_logs(self, containers, services, since=None):
        _, out_path =  tempfile.mkstemp()
        with open(out_path, 'w') as o:
            printer = log_printer_from_project(
                self.project,
                containers,
                True, # --no-color flag
                {'follow': False, 'tail': None,
                 'timestamps': True, 'since': since},
                event_stream=self.project.events(service_names=services)
            )
            printer.output = o
            printer.run()
        with open(out_path, 'r') as o:
            out = o.read()
        os.remove(out_path)

        return out

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
            if all([container.human_readable_state == 'Up'
                    for service in self.project.services
                    for container in service.containers()]):
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
