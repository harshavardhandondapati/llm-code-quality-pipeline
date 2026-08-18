FROM python:3.10-bullseye

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIPELINE_TOOLS_DIRECTORY=/app/tools \
    PIPELINE_ALLOW_LOCAL_FALLBACK=false \
    D4J_HOME=/app/tools/defects4j

WORKDIR /app

ENV PYENV_ROOT=/opt/pyenv
ENV PATH=/opt/pyenv/bin:/opt/pyenv/shims:$PATH

RUN git clone --depth 1 https://github.com/pyenv/pyenv.git /opt/pyenv \
    && pyenv install -s 3.10.20 \
    && pyenv global 3.10.20 \
    && python --version \
    && pip --version


RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git \
       subversion \
       openjdk-11-jdk \
       perl \
       make \
       unzip \
       curl \
       wget \
       ca-certificates \
       cpanminus \
       build-essential \
       python3-venv \
       python3-dev \
       dos2unix \
       zlib1g-dev \
       libssl-dev \
       libbz2-dev \
       libreadline-dev \
       libsqlite3-dev \
       llvm \
       libncursesw5-dev \
       xz-utils \
       tk-dev \
       libxml2-dev \
       libxmlsec1-dev \
       libffi-dev \
       liblzma-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md requirements.txt UI_REQUIREMENTS.txt ./
COPY src ./src
COPY scripts ./scripts
COPY tests ./tests
COPY results ./results
COPY evidence ./evidence
COPY .streamlit ./.streamlit
COPY tools ./tools
COPY app.py ./app.py
COPY .env.example ./.env.example

RUN chmod +x scripts/prepare_benchmark_tools.sh \
    && python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && python -m pip install virtualenv

ARG INSTALL_BENCHMARK_TOOLS=true

RUN if [ "$INSTALL_BENCHMARK_TOOLS" = "true" ]; then scripts/prepare_benchmark_tools.sh /app/tools; fi

ENV BUGSINPY_HOME=/app/tools/BugsInPy \
    PIPELINE_BUGSINPY_EXECUTABLE_DIRECTORY=/app/tools/BugsInPy/framework/bin \
    PIPELINE_DEFECTS4J_EXECUTABLE_DIRECTORY=/app/tools/defects4j/framework/bin \
    PATH=/app/tools/BugsInPy/framework/bin:/app/tools/defects4j/framework/bin:$PATH

RUN /app/tools/defects4j/framework/bin/defects4j info -p Chart >/tmp/defects4j_final_verify.txt

EXPOSE 8501

CMD ["sh", "-c", "python -m streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT:-8501} --server.headless true --server.fileWatcherType none"]
