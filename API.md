# API Documentation


Module testcases
----------------
The testcases module is for use by Autopilot Pattern application tests
to run integration tests using Docker's `compose` library as its driver.

Variables
---------
log
    Logger that should be used by test implementations so that the testcases
    lib logging shares the same format as the tests. Accepts LOG_LEVEL from
    environment variables.

Functions
---------
debug(fn)
    Function/method decorator to trace calls via debug logging.
    Is a pass-thru if we're not at LOG_LEVEL=DEBUG. Normally this
    would have a lot of perf impact but this application doesn't
    have significant throughput.

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
    compose
        Field for the compose.cli.main.TopLevelCommand instance associated
        with the project. This will be populated by the setupClass method.

    project
        Field for the compose.project.Project instance associated with the
        project. This will be populated by the setupClass method.

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

    container_name(self, *args)
        Given an incomplete container identifier, construct the name
        with the project name includes. Args can be a string like 'nginx_1'
        or an iterable like ('nginx', 2).

    docker_compose_exec(*args, **kwargs)
        Runs `docker-compose exec <command_line>` on the container and
        returns a tuple: (exit code, stdout, stderr). The `command_line`
        parameter can be a list of arguments of a single string.

    docker_compose_logs(*args, **kwargs)
        Returns logs as if running `docker-compose logs`. Takes an optional
        iterable of services to filter the logs by.

    docker_compose_ps(*args, **kwargs)
        Runs `docker-compose ps`, dumping results to stdout.
        # TODO: support `service_name` filter param

    docker_compose_rm(*args, **kwargs)
        Runs `docker-compose rm -f <service>`, dumping results to stdout.

    docker_compose_scale(*args, **kwargs)
        Runs `docker-compose scale <service>=<count>`, dumping
        results to stdout

    docker_compose_stop(*args, **kwargs)
        Runs `docker-compose stop <service>`, dumping results to stdout.
        # TODO: support `service_name` param

    docker_compose_up(*args, **kwargs)
        Runs `docker-compose up -d`, dumping results to stdout.
        # TODO: support `service_name` param

    docker_logs(*args, **kwargs)
        Returns logs from a given container in the Compose format.

    docker_stop(*args, **kwargs)
        Stops a specific instance.

    get_consul_key(*args, **kwargs)
        Return the Value field for a given Consul key. Handles None
        results safely but lets all other exceptions just bubble up.

    get_service_ips(*args, **kwargs)
        Asks the service a list of IPs for that service by checking each
        of its containers. Returns a pair of lists (public, private).

    is_check_passing(*args, **kwargs)
        Queries consul for whether a check is passing.

    run_script(self, script)
        Runs an external script and returns the output. Allows
        subprocess.CalledProcessError or OSError to bubble up to caller.

    update_env_file(self, filename, substitutions)
        For each pair of substitutions, replace all cases of
        `variable=value` in the environment file. Ex.

        update_env_file('_env',
                       (('MYSQL_PASSWORD', 'password1'),
                        ('MYSQL_USER', 'me'))
        )

    wait_for_containers(*args, **kwargs)
        Waits for all containers to be marked as 'Up' for all services.

    wait_for_service(*args, **kwargs)
        Polls Consul for the service to become healthy, and optionally
        for a particular `count` of container instances to be healthy.

    wait_for_service_removed(*args, **kwargs)
        Polls Consul for the service to be removed.

    watch_docker_logs(*args, **kwargs)
        TODO

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

