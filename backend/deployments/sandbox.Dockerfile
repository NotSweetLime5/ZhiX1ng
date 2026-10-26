# Optional user-code sandbox; the FastAPI backend itself only requires Python.
# Keep the Go toolchain for the existing code_exec(language="go") tool.
FROM golang:1.26-bookworm AS go
FROM python:3.12-slim-bookworm
COPY --from=go /usr/local/go /usr/local/go
ENV PATH="/usr/local/go/bin:$PATH" GOCACHE=/tmp/gocache
USER 65534:65534
WORKDIR /tmp
