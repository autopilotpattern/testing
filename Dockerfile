FROM alpine:latest

# for Python dependencies
COPY requirements.txt /tmp/

# Install Node.js and the Triton CLI tools
# Also, install Python and libraries we need for Compose, Docker, Consul, Manta.
# Because we're using Alpine we need to get most of the native dependencies
# from the Alpine package manager.
RUN apk update && apk add \
    docker \
    bash \
    curl \
    nodejs \
    build-base \
    python-dev \
    py-pip \
    py-cffi \
    py-paramiko \
    && pip install -r /tmp/requirements.txt \
    && npm install -g triton json \
    && apk del build-base \
    && rm -rf /var/cache/apk/*

# Install the testcases library to site-packages so our tests can import
# it via `import testcases`
COPY *.py /tmp/
RUN cd /tmp && python setup.py install

# Set a working directory so that derived images will be able to drop
# Python code in /src and then run it without setting PYTHONPATH or
# running setuptools
WORKDIR /src
