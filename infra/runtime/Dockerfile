# gtfs-semantic-diff ジョブ実行 Lambda (api / worker 共用イメージ)
# ビルドコンテキストはリポジトリルート (CDK: file=infra/runtime/Dockerfile)
FROM public.ecr.aws/lambda/python:3.13

# パッケージ本体 (viewer_template.html は wheel に同梱される)
COPY pyproject.toml /build/
COPY src /build/src
RUN pip install --no-cache-dir /build "mcp~=2.0" && rm -rf /build

# 閾値設定 (Config.load は GTFS_SEMDIFF_CONFIG で参照)
COPY config ${LAMBDA_TASK_ROOT}/config
ENV GTFS_SEMDIFF_CONFIG=${LAMBDA_TASK_ROOT}/config/default.toml
# キャッシュ (~/.cache) を書き込み可能な /tmp に向ける
ENV HOME=/tmp

COPY infra/runtime/handler.py infra/runtime/versioning.py infra/runtime/webusers.py \
     infra/runtime/mcp_entry.py infra/runtime/mcp_tools.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.api"]
