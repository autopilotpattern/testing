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

For our tests running on Shippable against Triton, there's a good deal more setup involved. You must have a Shippable account, and configure it with a Docker Hub integration and an ssh key integration. The key you provide Shippable must have permissions to deploy as a user on Triton. These integrations get added to the `shippable.yml` file:

```yml
integrations:
  hub:
    - integrationName: DockerHub
      type: docker

  key:
    - integrationName: MyTritonTestingKey
      type: ssh-key
```

We can't mount our credentials on our laptops to the build container on Shippable, so we need to use the ssh key integration to create a Triton profile using that key. While we could create a Triton profile and commit it to the GitHub repo safely (the private key isn't in our repo), it's better to dynamically generate it when we run the build. This makes it easy for anyone to set up their own Shippable test pipeline without hard-coded users.

The following Makefile snippet ensures the Triton profile exists whenever we run `make test`:

```make
KEY := ~/.ssh/MyTritonTestingKey

# create a Triton profile from the ssh key
# Shippable injects the key into the directory /tmp/ssh/
~/.triton/profiles.d/us-sw-1.json:
	{ \
	  cp /tmp/ssh/MyTritonTestingKey $(KEY) ;\
	  ssh-keygen -y -f $(KEY) > $(KEY).pub ;\
	  FINGERPRINT=$$(ssh-keygen -l -f $(KEY) | awk '{print $$2}' | sed 's/MD5://') ;\
	  printf '{"url": "https://us-sw-1.api.joyent.com", "name": "TritonTesting", "account": "username", "keyId": "%s"}' $${FINGERPRINT} > profile.json ;\
	}
	cat profile.json | triton profile create -f -
	-rm profile.json

# we don't have control over the -w flag for the Shippable container
tests.py:
    cp tests/tests.py

test: ~/.triton/profiles.d/us-sw-1.json tests.py
    DOCKER_TLS_VERIFY=1 \
    DOCKER_CERT_PATH=/root/.triton/docker/username@us-sw-1_api_joyent_com \
    DOCKER_HOST=tcp://us-sw-1.docker.joyent.com:2376 \
    COMPOSE_HTTP_TIMEOUT=300 \
    PATH=/root/venv/3.5/bin:/usr/bin \
    python tests.py

```
