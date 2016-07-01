# API Documentation


Module testcases
----------------
The testcases module is for use by Autopilot Pattern application tests
to run integration tests using Docker and Compose as its driver.

Variables
---------
COMPOSE
    Optionally override path to docker-compose via COMPOSE env var

DOCKER
    Optionally override path to docker via DOCKER env var

log
    Logger that should be used by test implementations so that the testcases
    lib logging shares the same format as the tests. Accepts LOG_LEVEL from
    environment variables.

Functions
---------
dump_environment_to_file(filepath)
    Takes the container's environment and dumps it out to a file
    that can be loaded as an env_file by Compose or bash. You'll
    need to call this before calling unittest.main in a tests.py
    if you want it to be available to Compose.

print(message)

Classes
-------
AutopilotPatternTest 
    AutopilotPatternTest serves as the base class for all tests and adds
    extra setup/teardown functionality.

    Ancestors (in MRO)
    ------------------
    testcases.AutopilotPatternTest
    unittest.case.TestCase
    __builtin__.object

    Class variables
    ---------------
    compose_file
        Field for an alternate compose file (default: docker-compose.yml).
        Test subclasses generally won't need to override the compose file name.

    project_name
        Test subclasses should override this project_name

    Instance variables
    ------------------
    consul
        Lazily constructs a Consul client pointing to the first Consul
        instance. We can't configure Consul during `setupClass` because
        we don't necessarily have Consul up and running at that point.

    Methods
    -------
    assertHttpOk(self, container_id, path, port)
        TODO

    compose(self, *args, **kwargs)
        Runs `docker-compose` with the appropriate project and file flag
        set for this test run, using `args` as its parameters. Pass the
        kwarg `verbose=True` to force printing the output. Subclasses
        should always call `self.compose` rather than running
        `subprocess.check_output` themselves so that we include them in
        instrumentation.

    compose_ps(self, service_name=None, verbose=False)
        Runs `docker-compose ps`, filtered by `service_name` and dumping
        results to stdout if the `verbose` param is included. Returns a
        list of field dicts.

    compose_scale(self, service_name, count, verbose=False)
        Runs `docker-compose scale <service>=<count>`, dumping
        results to stdout

    docker(self, *args, **kwargs)
        Runs `docker` with the appropriate arguments, using args as its
        parameters. Pass the kwarg `verbose=True` to force printing the
        output. Subclasses should always call `self.docker` rather than
        running `subprocess.check_output` themselves so that we include
        them in instrumentation.

    docker_exec(self, container, command_line, verbose=False)
        Runs `docker exec <command_line>` on the container and
        returns a tuple: (exit code, output). The `command_line`
        parameter can be a list of arguments of a single string.

    docker_inspect(self, container)
        Runs `docker inspect` on a given container and parses the JSON.

    docker_logs(self, container, since=None, verbose=True)
        Returns logs from a given container.

    docker_stop(self, container, verbose=False)
        Stops a specific instance.

    get_consul_key(self, key)
        Return the Value field for a given Consul key. Handles None
        results safely but lets all other exceptions just bubble up.

    get_container_name(self, *args)
        Given an incomplete container identifier, construct the name
        with the project name included. Args can be a string like 'nginx_1'
        or an iterable like ('nginx', 2). If the arg is the container ID
        then it will be returned unchanged.

    get_service_addresses_from_consul(self, service_name)
        Asks Consul for a list of addresses for a service (compare to
        `get_service_ips` which asks the containers via `inspect`).

    get_service_ips(self, service)
        Asks the service a list of IPs for that service by checking each
        of its containers. Returns a pair of lists (public, private).

    instrument(self, fn, *args, **kwargs)

    is_check_passing(self, key)
        Queries consul for whether a check is passing.

    run_script(self, *args)
        Runs an external script and returns the output. Allows
        subprocess.CalledProcessError or OSError to bubble up to caller.

    update_env_file(self, filename, substitutions)
        For each pair of substitutions, replace all cases of
        `variable=value` in the environment file. Ex.

        update_env_file('_env',
                       (('MYSQL_PASSWORD', 'password1'),
                        ('MYSQL_USER', 'me'))
        )

    wait_for_containers(self, timeout=30)
        Waits for all containers to be marked as 'Up' for all services.

    wait_for_service(self, service_name, count=0, timeout=30)
        Polls Consul for the service to become healthy, and optionally
        for a particular `count` of container instances to be healthy.

    wait_for_service_removed(self, service_name, timeout=30)
        Polls Consul for the service to be removed.

    watch_docker_logs(self, name, val, timeout=60)
        TODO

ClientException 
    Exception raised when running the Compose or Docker client
    subprocess returns a non-zero exit code.

    Ancestors (in MRO)
    ------------------
    testcases.ClientException
    exceptions.Exception
    exceptions.BaseException
    __builtin__.object

    Class variables
    ---------------
    args

    message

Container 
    Container(name, command, state, ports)

    Ancestors (in MRO)
    ------------------
    testcases.Container
    __builtin__.tuple
    __builtin__.object

    Instance variables
    ------------------
    command
        Alias for field number 1

    name
        Alias for field number 0

    ports
        Alias for field number 3

    state
        Alias for field number 2

WaitTimeoutError 
    Exception raised when a timeout occurs.

    Ancestors (in MRO)
    ------------------
    testcases.WaitTimeoutError
    exceptions.Exception
    exceptions.BaseException
    __builtin__.object

    Class variables
    ---------------
    args

    message

