FROM golang:1.23-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/rag ./rag \
    && CGO_ENABLED=0 go build -trimpath -o /out/recall ./recall \
    && CGO_ENABLED=0 go build -trimpath -o /out/reindex ./reindex

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/ /usr/local/bin/
EXPOSE 8090 9948
ENTRYPOINT ["/usr/local/bin/rag"]
