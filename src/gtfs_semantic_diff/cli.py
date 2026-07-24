"""CLI エントリポイント (click)。docs/design/architecture.md の CLI 仕様参照."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .config import Config
from .load import GtfsDataRepository, load_snapshot
from .load.repository import GtfsFileInfo, rid_order

console = Console()


@click.group()
@click.option("--config", "config_path", type=click.Path(exists=True), default=None,
              help="設定 TOML のパス (既定: config/default.toml)")
@click.option("-v", "--verbose", is_flag=True, help="詳細ログ")
@click.pass_context
def main(ctx: click.Context, config_path: str | None, verbose: bool) -> None:
    """gtfs-semantic-diff: 複数世代 GTFS の意味的差分抽出."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    ctx.obj = Config.load(config_path)


def _resolve_pair(
    ctx: click.Context,
    repo: GtfsDataRepository,
    org: str,
    feed: str,
    old_rid: str,
    new_rid: str,
) -> tuple[GtfsFileInfo, GtfsFileInfo]:
    """(old, new) の世代ファイル情報を解決する。

    rid 未指定 (既定の prev_1/current) で 'current' が存在しないフィード
    (有効期限切れ等) は、利用可能な最新2世代に読み替える。
    """
    max_prev = max(_max_prev(old_rid, new_rid), 9)
    files = {f.rid: f for f in repo.get_feed_files(org, feed, max_prev=max_prev)}

    rid_explicit = any(
        ctx.get_parameter_source(p) == click.core.ParameterSource.COMMANDLINE
        for p in ("old_rid", "new_rid")
    )
    missing = [r for r in (old_rid, new_rid) if r not in files]
    if missing:
        if rid_explicit or len(files) < 2:
            raise click.ClickException(
                f"rid {missing} が見つかりません (利用可能: {sorted(files.keys(), key=rid_order)})"
            )
        new_rid, old_rid = sorted(files.keys(), key=rid_order)[:2]
        console.print(
            f"[yellow]'current' が存在しないため最新2世代 "
            f"{old_rid} → {new_rid} を対象にします[/yellow]"
        )
    return files[old_rid], files[new_rid]


def _max_prev(*rids: str) -> int:
    return max((int(r.split("_")[1]) for r in rids if r.startswith("prev_")), default=1)


def _load_snapshot_pair(
    ctx: click.Context,
    config: Config,
    inputs: tuple[str, ...],
    org: str | None,
    feed: str | None,
    old_rid: str,
    new_rid: str,
):
    """compare / identity 共通の入力解決: ローカル zip 2つ or gtfs-data.jp。"""
    if len(inputs) == 2:
        return (
            load_snapshot(inputs[0], config=config),
            load_snapshot(inputs[1], config=config),
        )
    if len(inputs) == 0 and org and feed:
        repo = GtfsDataRepository(config=config)
        old_info, new_info = _resolve_pair(ctx, repo, org, feed, old_rid, new_rid)
        old_fetched = repo.download(old_info)
        new_fetched = repo.download(new_info)
        return (
            load_snapshot(
                old_fetched.path, config=config, meta=old_info.snapshot_meta(old_fetched.path)
            ),
            load_snapshot(
                new_fetched.path, config=config, meta=new_info.snapshot_meta(new_fetched.path)
            ),
        )
    raise click.ClickException(
        "入力を指定してください: ローカル zip 2つ、または --org と --feed"
    )


@main.command()
@click.option("--org", required=True, help="gtfs-data.jp の組織 ID (例: nagai-unyu)")
@click.option("--feed", required=True, help="フィード ID (例: Nagaibus)")
@click.option("--old", "old_rid", default="prev_1", show_default=True, help="旧世代の RID")
@click.option("--new", "new_rid", default="current", show_default=True, help="新世代の RID")
@click.option("--force", is_flag=True, help="キャッシュを無視して再ダウンロード")
@click.pass_context
def fetch(ctx: click.Context, org: str, feed: str, old_rid: str, new_rid: str, force: bool) -> None:
    """gtfs-data.jp から2世代の zip を取得・キャッシュし、Snapshot として読めることを確認する."""
    config: Config = ctx.obj
    repo = GtfsDataRepository(config=config)
    old_info, new_info = _resolve_pair(ctx, repo, org, feed, old_rid, new_rid)

    table = Table(title=f"{org}/{feed}")
    for col in ("RID", "有効期間", "取得元", "ローカル", "tables", "routes", "stops", "trips"):
        table.add_column(col)

    for info in (old_info, new_info):
        fetched = repo.download(info, force=force)
        snapshot = load_snapshot(
            fetched.path, config=config, meta=fetched.info.snapshot_meta(fetched.path)
        )
        counts = snapshot.row_counts()
        table.add_row(
            info.rid,
            f"{info.from_date} 〜 {info.to_date}",
            "cache" if fetched.from_cache else "download",
            str(fetched.path),
            str(len(snapshot.tables)),
            str(counts.get("routes", 0)),
            str(counts.get("stops", 0)),
            str(counts.get("trips", 0)),
        )
        day_type_counts: dict[str, int] = {}
        for dt in snapshot.day_types.values():
            day_type_counts[dt] = day_type_counts.get(dt, 0) + 1
        console.print(f"[dim]{info.rid}: day_types = {day_type_counts}[/dim]")

    console.print(table)
    console.print("[green]2世代の取得と Snapshot 読み込みに成功しました。[/green]")


@main.command()
@click.argument("inputs", nargs=-1, type=click.Path(exists=True))
@click.option("--org", default=None, help="gtfs-data.jp の組織 ID")
@click.option("--feed", default=None, help="フィード ID")
@click.option("--old", "old_rid", default="prev_1", show_default=True, help="旧世代の RID")
@click.option("--new", "new_rid", default="current", show_default=True, help="新世代の RID")
@click.option("-o", "--output", type=click.Path(), default=None,
              help="ChangeEventSet JSON の出力先")
@click.option("--rawdiffs", "rawdiffs_out", type=click.Path(), default=None,
              help="RawDiff 全件 JSON の出力先")
@click.option("--report", "report_out", type=click.Path(), default=None,
              help="Markdown レポートの出力先")
@click.option("--html", "html_out", type=click.Path(), default=None,
              help="自己完結 HTML レポートの出力先 (単一ファイル・全量同梱)")
@click.option("--html-lite", "html_lite_out", type=click.Path(), default=None,
              help="軽量 HTML の出力先 (Web 配信と同じ core バンドル — "
                   "evidence/生差分はサンプル+件数、RD1a)")
@click.option("--html-dir", "html_dir_out", type=click.Path(), default=None,
              help="分割出力先ディレクトリ (index.html + data.json、RD1b)。"
                   "http サーバー経由で閲覧する (file:// では fetch 不可)")
@click.pass_context
def compare(
    ctx: click.Context,
    inputs: tuple[str, ...],
    org: str | None,
    feed: str | None,
    old_rid: str,
    new_rid: str,
    output: str | None,
    rawdiffs_out: str | None,
    report_out: str | None,
    html_out: str | None,
    html_lite_out: str | None,
    html_dir_out: str | None,
) -> None:
    """2世代の GTFS を比較し ChangeEvent JSON / Markdown / HTML レポートを出力する。

    入力はローカル zip 2つ (古い方が先) か、--org/--feed による API 取得。
    """
    from .events.pipeline import compare_snapshots_with_artifacts

    config: Config = ctx.obj
    old_snap, new_snap = _load_snapshot_pair(ctx, config, inputs, org, feed, old_rid, new_rid)

    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old_snap, new_snap, config
    )

    table = Table(title=f"L0 RawDiff: {old_snap.meta.label()} → {new_snap.meta.label()}")
    table.add_column("ファイル")
    table.add_column("件数", justify="right")
    for filename, count in rawdiffs.count_by_file().items():
        table.add_row(filename, str(count))
    table.add_row("[bold]合計[/bold]", f"[bold]{len(rawdiffs)}[/bold]")
    console.print(table)

    acc = event_set.accounting
    console.print(
        f"イベント: {len(event_set.events)} 件 / "
        f"explained_ratio = [bold]{acc.explained_ratio:.4f}[/bold] "
        f"({acc.explained} / {acc.rawdiff_total})"
    )

    if output:
        Path(output).write_text(
            json.dumps(event_set.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"ChangeEventSet JSON: [cyan]{output}[/cyan]")
    if rawdiffs_out:
        payload = {"rawdiffs": [d.to_dict() for d in rawdiffs.diffs]}
        Path(rawdiffs_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"RawDiff JSON: [cyan]{rawdiffs_out}[/cyan]")
    if report_out:
        from .report import render_markdown

        Path(report_out).write_text(
            render_markdown(event_set.to_dict()), encoding="utf-8"
        )
        console.print(f"Markdown レポート: [cyan]{report_out}[/cyan]")
    if html_out or html_lite_out or html_dir_out:
        from .report.bundle import build_bundle, write_html, write_html_split

        template_path = Path(__file__).parent / "report" / "viewer_template.html"
        if not template_path.exists():
            raise click.ClickException(
                "ビューアテンプレートがありません。scripts/build_viewer.sh でビルドしてください"
            )
        template = template_path.read_text(encoding="utf-8")
        if html_out:
            bundle = build_bundle(
                old_snap, new_snap, config, event_set, rawdiffs, identity, trip_delta
            )
            write_html(bundle, template, html_out)
            console.print(f"HTML レポート: [cyan]{html_out}[/cyan]")
        if html_lite_out or html_dir_out:
            bundle = build_bundle(
                old_snap, new_snap, config, event_set, rawdiffs, identity,
                trip_delta, core=True,
            )
            if html_lite_out:
                write_html(bundle, template, html_lite_out)
                console.print(f"HTML レポート (軽量): [cyan]{html_lite_out}[/cyan]")
            if html_dir_out:
                out_dir = Path(html_dir_out)
                out_dir.mkdir(parents=True, exist_ok=True)
                write_html_split(
                    bundle, template, out_dir / "index.html",
                    out_dir / "data.json", "./data.json", gzip_data=False,
                )
                console.print(f"HTML レポート (分割): [cyan]{out_dir}/[/cyan]")


@main.command()
@click.argument("inputs", nargs=-1, type=click.Path(exists=True))
@click.option("--org", default=None, help="gtfs-data.jp の組織 ID")
@click.option("--feed", default=None, help="フィード ID")
@click.option("--old", "old_rid", default="prev_1", show_default=True, help="旧世代の RID")
@click.option("--new", "new_rid", default="current", show_default=True, help="新世代の RID")
@click.option("-o", "--output", type=click.Path(), default=None, help="統計 JSON の出力先")
@click.pass_context
def identity(
    ctx: click.Context,
    inputs: tuple[str, ...],
    org: str | None,
    feed: str | None,
    old_rid: str,
    new_rid: str,
    output: str | None,
) -> None:
    """L1 世代間同定を実行し、MatchGraph の対応率と confidence 分布を表示する。"""
    from .identity import build_identity, identity_stats

    config: Config = ctx.obj
    old_snap, new_snap = _load_snapshot_pair(ctx, config, inputs, org, feed, old_rid, new_rid)

    result = build_identity(old_snap, new_snap, config)
    stats = identity_stats(result)

    table = Table(title=f"MatchGraph: {old_snap.meta.label()} → {new_snap.meta.label()}")
    for col in ("エンティティ", "旧", "新", "エッジ", "旧対応率", "新対応率",
                "conf=1.0", "0.75+", "0.5+", "<0.5"):
        table.add_column(col, justify="right")
    for entity, s in stats.items():
        hist = s["confidence_hist"]
        table.add_row(
            entity,
            str(s["old_count"]),
            str(s["new_count"]),
            str(s["edges"]),
            f"{s['match_rate_old']:.1%}",
            f"{s['match_rate_new']:.1%}",
            str(hist["1.0"]),
            str(hist["0.75-1.0"]),
            str(hist["0.5-0.75"]),
            str(hist["<0.5"]),
        )
    console.print(table)

    if output:
        Path(output).write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"統計 JSON: [cyan]{output}[/cyan]")


if __name__ == "__main__":
    main()
