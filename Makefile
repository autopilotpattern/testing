# Makefile for building and shipping the autopilotpattern/testing
# container image.

# we get these from shippable if available
COMMIT ?= $(shell git rev-parse --short HEAD)
BRANCH ?= $(shell git rev-parse --abbrev-ref HEAD)
TAG := $(BRANCH)-$(COMMIT)

build:
	docker build -t="autopilotpattern/testing:$(TAG)" .

ship:
	docker push autopilotpattern/testing:$(TAG)

# TODO: come back to this; I'm not wild about the format using pdoc
docs:
	echo '# API Documentation' > API.md
	echo >> API.md
	echo >> API.md
	docker run --rm \
		-v $(shell pwd):/src \
		autopilotpattern/testing pdoc testcases.py >> API.md
	echo >> API.md
