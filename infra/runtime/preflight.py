"""XL2: 投入前の規模プリフライト (純ロジック、boto3 非依存)。

アップロードされた GTFS zip の central directory から stop_times の
非圧縮サイズを読み、Web 版 (Lambda worker) の処理上限を超えるものは
投入前に ja/en の理由付きで断る。閾値の根拠は docs/perf/XL1_lambda_limits.md。
S3 とのつなぎ (Range GET の file-like) は handler.py 側。
"""
from __future__ import annotations

import logging
import zipfile

logger = logging.getLogger(__name__)

CLI_GUIDE_URL = "https://diff.gtfs.jp/developers.html"


def zip_scale_mb(fileobj) -> dict | None:
    """zip 内の非圧縮サイズ (MB 単位の int)。stop_times が処理規模の支配項。

    読めない zip は None を返す (ゲートは働かせず、worker 側の通常の
    入力エラー処理に任せる — 誤って正当な投入を弾かないため)。"""
    try:
        with zipfile.ZipFile(fileobj) as zf:
            out = {"stop_times": 0, "total": 0}
            for info in zf.infolist():
                out["total"] += info.file_size
                if info.filename.rsplit("/", 1)[-1].lower() == "stop_times.txt":
                    out["stop_times"] += info.file_size
        return {k: int(v / 1048576) for k, v in out.items()}
    except Exception:
        logger.warning("preflight: zip 走査に失敗 (ゲート素通し)", exc_info=True)
        return None


def gate_message(scales: dict[str, dict | None], limit_mb: int
                 ) -> tuple[str, str] | None:
    """上限超過なら (ja, en) のエラーメッセージ、以内なら None。"""
    over = {side: sc for side, sc in scales.items()
            if sc and sc.get("stop_times", 0) > limit_mb}
    if not over:
        return None
    detail = " / ".join(
        f"{side}: {sc['stop_times']}MB" for side, sc in sorted(over.items()))
    ja = (f"この GTFS は Web 版の処理規模の上限を超えています "
          f"(stop_times 非圧縮 {detail}、上限 {limit_mb}MB/世代)。"
          f"オープンソースの CLI 版なら同じレポートをローカルで生成できます — "
          f"導入方法: {CLI_GUIDE_URL}")
    en = (f"This GTFS exceeds the size limit of the web service "
          f"(uncompressed stop_times {detail}; limit {limit_mb}MB per"
          f" version). The open-source CLI produces the same report locally"
          f" without limits — see {CLI_GUIDE_URL}")
    return ja, en


def failure_message(scale_mb: dict, limit_mb: int) -> tuple[str, str, str | None]:
    """worker が結果を残さず死んだとき (OOM/timeout) の (ja, en, error_kind)。

    「時間超過」と断定しない (OOM でも同じ経路に来る)。規模が上限の半分を
    超えていれば規模起因と明示して CLI へ誘導する。"""
    biggest = max((int(v) for v in (scale_mb or {}).values()), default=0)
    if biggest > limit_mb // 2:
        ja = (f"処理が完了しませんでした (制限時間15分またはメモリ上限)。"
              f"この規模 (stop_times 非圧縮 最大 {biggest}MB) は Web 版の"
              f"処理上限付近です。オープンソースの CLI 版ならローカルで"
              f"同じレポートを生成できます — {CLI_GUIDE_URL}")
        en = (f"The job did not finish (15-minute or memory limit). At this"
              f" size (uncompressed stop_times up to {biggest}MB) the feed is"
              f" near the web service's limit. The open-source CLI produces"
              f" the same report locally — {CLI_GUIDE_URL}")
        return ja, en, "input"
    ja = ("処理が完了しませんでした (制限時間15分またはメモリ上限)。"
          "時間をおいて再試行してください")
    en = ("The job did not finish (15-minute or memory limit)."
          " Please retry later")
    return ja, en, None
