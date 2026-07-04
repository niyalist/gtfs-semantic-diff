"""CLI エントリポイント (click)。docs/design/architecture.md の CLI 仕様参照."""

from __future__ import annotations

import logging

import click
from rich.console import Console
from rich.table import Table

from .config import Config
from .load import GtfsDataRepository, load_snapshot
from .load.repository import rid_order

console = Console()


@click.group()
@click.option("--config", "config_path", type=click.Path(exists=True), default=None,
              help="設定 TOML のパス (既定: config/default.toml)")
@click.option("-v", "--verbose", is_flag=True, help="詳細ログ")
@click.pass_context
def main(ctx: click.Context, config_path: str | None, verbose: bool) -> None:
    """gtfs-semdiff: 複数世代 GTFS の意味的差分抽出."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    ctx.obj = Config.load(config_path)


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
        # 既定の prev_1/current が揃わないフィード (例: 有効期限切れで current 不在) は
        # 利用可能な最新2世代に読み替える
        new_rid, old_rid = sorted(files.keys(), key=rid_order)[:2]
        console.print(
            f"[yellow]'current' が存在しないため最新2世代 "
            f"{old_rid} → {new_rid} を取得します[/yellow]"
        )

    table = Table(title=f"{org}/{feed}")
    for col in ("RID", "有効期間", "取得元", "ローカル", "tables", "routes", "stops", "trips"):
        table.add_column(col)

    for rid in (old_rid, new_rid):
        fetched = repo.download(files[rid], force=force)
        snapshot = load_snapshot(
            fetched.path, config=config, meta=fetched.info.snapshot_meta(fetched.path)
        )
        counts = snapshot.row_counts()
        table.add_row(
            rid,
            f"{fetched.info.from_date} 〜 {fetched.info.to_date}",
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
        console.print(f"[dim]{rid}: day_types = {day_type_counts}[/dim]")

    console.print(table)
    console.print("[green]2世代の取得と Snapshot 読み込みに成功しました。[/green]")


def _max_prev(*rids: str) -> int:
    return max((int(r.split("_")[1]) for r in rids if r.startswith("prev_")), default=1)


if __name__ == "__main__":
    main()
