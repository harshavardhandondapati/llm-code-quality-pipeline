FROM python:3.10-bullseye

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1     PIPELINE_TOOLS_DIRECTORY=/app/tools     PIPELINE_ALLOW_LOCAL_FALLBACK=false

WORKDIR /app

RUN apt-get update     && apt-get install -y --no-install-recommends        git subversion openjdk-11-jdk perl make unzip curl cpanminus     && rm -rf /var/lib/apt/lists/*

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

RUN chmod +x scripts/prepare_benchmark_tools.sh     && python -m pip install --upgrade pip     && python -m pip install -r requirements.txt

ARG INSTALL_BENCHMARK_TOOLS=true
RUN if [ "$INSTALL_BENCHMARK_TOOLS" = "true" ]; then scripts/prepare_benchmark_tools.sh /app/tools; fi

ENV PIPELINE_BUGSINPY_EXECUTABLE_DIRECTORY=/app/tools/BugsInPy/framework/bin     PIPELINE_DEFECTS4J_EXECUTABLE_DIRECTORY=/app/tools/defects4j/framework/bin     PATH=/app/tools/BugsInPy/framework/bin:/app/tools/defects4j/framework/bin:$PATH

EXPOSE 8501

CMD ["sh", "-c", "python -m streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT:-8501}"]
