# ImpactGuard, containerized: a zero-install way to run the risk gate and
# structural decay gate in any CI system (GitLab, Jenkins, Buildkite, ...)
# that can run an arbitrary container.
#
# Build:
#   docker build -t impactguard .
#
# Run (repo mounted read-write — ImpactGuard needs `git` to inspect history,
# and read-only bind mounts can break `git diff` on some Docker/OverlayFS
# combinations):
#   docker run --rm -v "$PWD:/repo" -w /repo impactguard \
#     decay . --mode range --base origin/main --enforcement block
#
#   docker run --rm -v "$PWD:/repo" -w /repo impactguard \
#     check-commits origin/main HEAD --enforce-gate

FROM python:3.13-slim AS build

WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.13-slim

# git is a hard runtime dependency: decay_model.py and the check-commits /
# install-hooks paths all shell out to it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /install /usr/local

# Anything mounted at /repo is untrusted from git's point of view (owned by
# the host user, not the container's); without this, `git` refuses to run
# inside it ("detected dubious ownership").
RUN git config --system --add safe.directory '*'

WORKDIR /repo
ENTRYPOINT ["impactguard"]
CMD ["--help"]
