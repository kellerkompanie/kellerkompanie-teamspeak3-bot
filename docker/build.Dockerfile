FROM debian:trixie-slim

# Non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    debhelper \
    devscripts \
    python3-dev \
    binutils \
    patchelf \
    libmariadb-dev \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/mariadb_config /usr/local/bin/mariadb_config

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Copy project files
WORKDIR /build
COPY . /build/

# Fix Windows line endings (CRLF -> LF) and permissions
RUN find . -type f \( -name "*.yaml" -o -name "*.toml" -o -name "*.service" -o -name "install" -o -name "rules" -o -name "postinst" -o -name "prerm" -o -name "postrm" \) -exec sed -i 's/\r$//' {} \;
RUN chmod -x debian/install debian/*.service configs/* 2>/dev/null || true
RUN chmod +x debian/rules debian/postinst debian/prerm debian/postrm 2>/dev/null || true

# Build by default
CMD ["dpkg-buildpackage", "-us", "-uc", "-b"]
