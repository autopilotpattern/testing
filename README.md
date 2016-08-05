# Testing the Autopilot Pattern

*Tooling for testing applications built using the Autopilot Pattern.*

This repo contains a Python module `testcases` which provides a Python `unittest.TestCase` subclass which can be used to create integration tests of applications by driving Docker Compose.

See the [API documentation](https://github.com/autopilotpattern/testing/blob/master/API.md) for details on the methods made available on the `AutopilotPatternTest` class.

## Test environments

The minimal environment for an application that uses the `testcases` module is:

- a Docker client.
- a Docker deployment target such as Triton or Docker for Mac.
- Python 3
- installing `requirements.txt` via `pip3` (this will include Docker Compose).

Typically Autopilot Pattern applications found on [GitHub](https://github.com/autopilotpattern) will have a Makefile with three different test configurations:

- Run the tests in a Docker container locally, using the local Docker Engine as the target of deployment
- Run the tests in a Docker container locally, using Triton as the target of deployment.
- Run the tests in a [Shippable](https://app.shippable.com) build container, using Triton as the target of deployment.

### Build containers

So that tests are identical whether run locally, against Triton, or on Shippable, it's a good idea for tests to run in a build container. An example Dockerfile for a build container can be found in this repo: [Dockerfile.example](https://github.com/autopilotpattern/testing/blob/master/Dockerfile.example). This Dockerfile assumes that your application has test code found at `/tests/tests.py` as well as a `docker-compose.yml` file.

### Testing against local Docker

For running the build container locally and deploying the tests against a local Docker Engine (for example, Docker for Mac), you'll create your build container and then mount the `docker.sock` to it.

```
docker run -it --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
	-e PATH=/root/venv/3.5/bin:/usr/bin:/usr/local/bin \
	-e COMPOSE_HTTP_TIMEOUT=300 \
	-w /src \
    example/myBuildContainer \
    python tests.py
```

This will start the build container, setup the Python3 environment, and then run your tests by sending Docker API commands along the `docker.sock` to the Docker engine on your laptop.

### Testing on Triton

For running the build container locally but deploying the tests against Triton, you'll create your build container and provide it with your credentials to Triton by mounting them to the test container and proving the appropriate environment variables. In the example below, the tests will be run on Joyent's Triton Cloud in the `us-sw-1` data center.

```
docker run -it --rm \
	-v ~/.triton:/root/.triton \
    -e DOCKER_TLS_VERIFY=1 \
    -e DOCKER_CERT_PATH=/root/.triton/docker/username@us-sw-1_api_joyent_com \
    -e DOCKER_HOST=tcp://us-sw-1.docker.joyent.com:2376 \
	-e PATH=/root/venv/3.5/bin:/usr/bin:/usr/local/bin \
	-e COMPOSE_HTTP_TIMEOUT=300 \
	-w /src \
    example/myBuildContainer \
    python tests.py

```

### Testing on Shippable

For running the tests on Shippable against Triton, there's a good deal more setup involved.

WIP

```
cp tests/tests.py . && \
    DOCKER_TLS_VERIFY=1 \
    DOCKER_CERT_PATH=/root/.triton/docker/timgross@us-sw-1_api_joyent_com \
    DOCKER_HOST=tcp://us-sw-1.docker.joyent.com:2376 \
    COMPOSE_HTTP_TIMEOUT=300 \
    PATH=/root/venv/3.5/bin:/usr/bin \
    $(PYTHON) tests.py
```
