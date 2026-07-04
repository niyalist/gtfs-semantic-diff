# gtfs-semdiff

複数世代の GTFS フィードを比較し、変化を「人間が認識できる意味」(路線廃止・減便・区間短縮・乗り場変更など) の ChangeEvent として抽出する CLI ツール。GTFSデータリポジトリ (gtfs-data.jp) の世代管理 API と連携。

- 設計原則・開発ルール: `CLAUDE.md`
- 変化イベント定義: `docs/design/ontology.md`
- アーキテクチャ: `docs/design/architecture.md`
- 開発計画: `docs/design/roadmap.md`
- 旧プロジェクトからの移植: `docs/PORTING.md`

## 状態

設計フェーズ完了、実装は M0 から (roadmap.md 参照)。
