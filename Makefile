# Makefile for building and shipping the autopilotpattern/testing
# container image.

build:
	docker build -t="testing" .

ship:
	docker tag -f testing autopilotpattern/testing
	docker push autopilotpattern/testing

# TODO: come back to this; I'm not wild about the format using pdoc
docs:
	echo '# API Documentation' > API.md
	echo >> API.md
	echo >> API.md
	docker run --rm \
		-v $(shell pwd):/src \
		autopilotpattern/testing pdoc testcases.py >> API.md
	echo >> API.md
