# The Python tools of the demo (exporters, probes, seed, lab) need pymongo and numpy.
# Installing them when a container starts needs the internet, so they are installed once, here.
# The pip lines in docker-compose.yml then find the exact same versions and download nothing.
FROM python:3.12-slim
RUN pip install --no-cache-dir pymongo==4.10.1 numpy==2.1.3
