ARG MELLOA_RESTIC_IMAGE=restic/restic:0.19.1@sha256:136600b6ff6843d61d355f7f71f460a166429f35de6fd11b568fece3c9a4d510
ARG MELLOA_POSTGRES_IMAGE=pgvector/pgvector:0.8.6-pg18-trixie@sha256:78bf48b801e792f99e3ac62b5036fd3876e9be48afda16c1e331af1c75ceb2ff

FROM ${MELLOA_RESTIC_IMAGE} AS restic

FROM ${MELLOA_POSTGRES_IMAGE}
ARG MELLOA_SOURCE_REVISION=uncommitted
LABEL org.opencontainers.image.title="Melloa encrypted backup runtime" \
      org.opencontainers.image.source="https://github.com/melloa-project/melloa" \
      org.opencontainers.image.revision="${MELLOA_SOURCE_REVISION}"
COPY --from=restic /usr/bin/restic /usr/local/bin/restic
COPY --chmod=0555 infra/server/backup.sh /usr/local/bin/melloa-backup
ENTRYPOINT ["/usr/local/bin/melloa-backup"]
CMD ["run"]
