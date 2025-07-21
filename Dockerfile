ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python and dependencies
RUN apk add --no-cache python3 py3-pip python3-dev gcc musl-dev

# Copy requirements and install Python packages in a virtual environment
WORKDIR /app
COPY src/requirements.txt .
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Add virtual environment to PATH
ENV PATH="/opt/venv/bin:$PATH"

# Copy the application
COPY src/ .
COPY run.sh /
RUN chmod a+x /run.sh

# Labels
LABEL \
  io.hass.type="addon" \
  io.hass.arch="aarch64|amd64|armhf|armv7|i386"

CMD [ "/run.sh" ]